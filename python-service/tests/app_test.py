import pytest
from unittest.mock import MagicMock
import types

from src.app import app
import src.app as app_module


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def make_error(code, message):
    class Err:
        def __init__(self, c, m):
            self.c = c
            self.m = m

        def to_dict(self):
            return {"code": self.c, "message": self.m}

    return Err(code, message)


class DummyIssue:
    def __init__(self, severity, line, message, suggestion):
        self.severity = severity
        self.line = line
        self.message = message
        self.suggestion = suggestion


class DummyReviewResult:
    def __init__(self, score, issues, suggestions, complexity_score):
        self.score = score
        self.issues = issues
        self.suggestions = suggestions
        self.complexity_score = complexity_score


class DummyStats:
    def __init__(
        self,
        total_files,
        average_score,
        total_issues,
        issues_by_severity,
        average_complexity,
        files_with_high_complexity,
        total_suggestions,
    ):
        self.total_files = total_files
        self.average_score = average_score
        self.total_issues = total_issues
        self.issues_by_severity = issues_by_severity
        self.average_complexity = average_complexity
        self.files_with_high_complexity = files_with_high_complexity
        self.total_suggestions = total_suggestions


def test_health_check_ok(client):
    """Test that /health returns a healthy status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


@pytest.mark.parametrize("endpoint", ["/review", "/statistics"])
def test_post_endpoints_missing_body_returns_400(client, endpoint):
    """Test that POST endpoints return 400 when request body is missing or empty."""
    resp = client.post(endpoint, json={})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing request body"


def test_review_code_validation_errors(client, monkeypatch):
    """Test /review returns 422 when validation fails with proper error details."""
    errors = [make_error("E001", "Missing content"), make_error("E002", "Invalid language")]
    monkeypatch.setattr(app_module, "validate_review_request", lambda data: errors)

    resp = client.post("/review", json={"content": "print(1)", "language": "python"})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"] == [e.to_dict() for e in errors]


@pytest.mark.parametrize(
    "sanitized_data, expected_language",
    [
        ({"content": "print(1)", "language": "javascript"}, "javascript"),
        ({"content": "x = 1"}, "python"),  # language omitted -> default to python
    ],
)
def test_review_code_success_with_sanitization_and_correlation_id(client, monkeypatch, sanitized_data, expected_language):
    """Test /review happy path with sanitization and correlation id included in response."""
    # No validation errors
    monkeypatch.setattr(app_module, "validate_review_request", lambda data: [])
    # Sanitized data returned by sanitizer
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: sanitized_data)

    # Mock reviewer
    issues = [
        DummyIssue("high", 1, "Use of print", "Use logging instead"),
        DummyIssue("low", 2, "Trailing whitespace", "Remove trailing spaces"),
    ]
    review_result = DummyReviewResult(score=85.5, issues=issues, suggestions=["Refactor foo"], complexity_score=7.2)

    mock_reviewer = MagicMock()
    mock_reviewer.review_code.return_value = review_result
    monkeypatch.setattr(app_module, "reviewer", mock_reviewer)

    # Correlation id
    monkeypatch.setattr(app_module, "g", types.SimpleNamespace(correlation_id="cid-123"))

    resp = client.post("/review", json={"content": "ignored"})
    assert resp.status_code == 200
    data = resp.get_json()

    # Verify call and payload
    mock_reviewer.review_code.assert_called_once_with(sanitized_data["content"], expected_language)

    assert data["score"] == review_result.score
    assert data["complexity_score"] == review_result.complexity_score
    assert data["suggestions"] == review_result.suggestions
    assert data["correlation_id"] == "cid-123"
    # Verify issues serialized correctly
    assert isinstance(data["issues"], list)
    assert data["issues"][0]["severity"] == "high"
    assert data["issues"][0]["line"] == 1
    assert data["issues"][0]["message"] == "Use of print"
    assert data["issues"][0]["suggestion"] == "Use logging instead"


def test_review_code_success_without_correlation_id(client, monkeypatch):
    """Test /review returns null correlation_id when not set."""
    monkeypatch.setattr(app_module, "validate_review_request", lambda data: [])
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: {"content": "pass"})

    review_result = DummyReviewResult(score=90, issues=[], suggestions=[], complexity_score=1.0)
    mock_reviewer = MagicMock()
    mock_reviewer.review_code.return_value = review_result
    monkeypatch.setattr(app_module, "reviewer", mock_reviewer)

    # g without correlation_id
    class EmptyG:
        pass

    monkeypatch.setattr(app_module, "g", EmptyG())

    resp = client.post("/review", json={"content": "ignored"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] is None


def test_review_function_missing_field(client):
    """Test /review/function returns 400 when 'function_code' field is missing."""
    resp = client.post("/review/function", json={"code": "def foo(): pass"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing 'function_code' field"


def test_review_function_success(client, monkeypatch):
    """Test /review/function happy path returns reviewer output."""
    mock_reviewer = MagicMock()
    mock_reviewer.review_function.return_value = {"status": "ok", "issues": [{"line": 1}]}
    monkeypatch.setattr(app_module, "reviewer", mock_reviewer)

    payload = {"function_code": "def foo():\n    return 1"}
    resp = client.post("/review/function", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"status": "ok", "issues": [{"line": 1}]}
    mock_reviewer.review_function.assert_called_once_with(payload["function_code"])


def test_statistics_validation_errors(client, monkeypatch):
    """Test /statistics returns 422 when validation fails."""
    errors = [make_error("S001", "Files required")]
    monkeypatch.setattr(app_module, "validate_statistics_request", lambda data: errors)

    resp = client.post("/statistics", json={"files": []})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"] == [e.to_dict() for e in errors]


def test_statistics_success_with_correlation_id(client, monkeypatch):
    """Test /statistics happy path returns aggregated stats and correlation id."""
    monkeypatch.setattr(app_module, "validate_statistics_request", lambda data: [])
    sanitized = {"files": [{"content": "print(1)", "language": "python"}]}
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: sanitized)

    stats_obj = DummyStats(
        total_files=3,
        average_score=88.2,
        total_issues=5,
        issues_by_severity={"low": 3, "high": 2},
        average_complexity=3.14,
        files_with_high_complexity=["a.py", "b.py"],
        total_suggestions=4,
    )

    mock_stats = MagicMock()
    mock_stats.aggregate_reviews.return_value = stats_obj
    monkeypatch.setattr(app_module, "statistics_aggregator", mock_stats)

    monkeypatch.setattr(app_module, "g", types.SimpleNamespace(correlation_id="cid-stats"))

    resp = client.post("/statistics", json={"files": [{"content": "ignored"}]})
    assert resp.status_code == 200
    data = resp.get_json()

    mock_stats.aggregate_reviews.assert_called_once_with(sanitized["files"])

    assert data["total_files"] == stats_obj.total_files
    assert data["average_score"] == stats_obj.average_score
    assert data["total_issues"] == stats_obj.total_issues
    assert data["issues_by_severity"] == stats_obj.issues_by_severity
    assert data["average_complexity"] == stats_obj.average_complexity
    assert data["files_with_high_complexity"] == stats_obj.files_with_high_complexity
    assert data["total_suggestions"] == stats_obj.total_suggestions
    assert data["correlation_id"] == "cid-stats"


def test_list_traces_returns_all(client, monkeypatch):
    """Test /traces returns total_traces and the list of traces."""
    traces = [{"id": "t1"}, {"id": "t2"}]
    monkeypatch.setattr(app_module, "get_all_traces", lambda: traces)

    resp = client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == 2
    assert data["traces"] == traces


def test_get_trace_not_found(client, monkeypatch):
    """Test /traces/<correlation_id> returns 404 when no traces exist for the ID."""
    monkeypatch.setattr(app_module, "get_traces", lambda cid: [])

    resp = client.get("/traces/unknown-id")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["error"] == "No traces found for correlation ID"


def test_get_trace_success(client, monkeypatch):
    """Test /traces/<correlation_id> returns trace details when found."""
    trace_list = [{"event": "start"}, {"event": "end"}]
    monkeypatch.setattr(app_module, "get_traces", lambda cid: trace_list)

    resp = client.get("/traces/corr-123")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] == "corr-123"
    assert data["trace_count"] == len(trace_list)
    assert data["traces"] == trace_list


def test_list_validation_errors_returns_all(client, monkeypatch):
    """Test /validation/errors returns total error count and all errors."""
    errors = [{"code": "E1"}, {"code": "E2"}, {"code": "E3"}]
    monkeypatch.setattr(app_module, "get_validation_errors", lambda: errors)

    resp = client.get("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == len(errors)
    assert data["errors"] == errors


def test_delete_validation_errors_clears_and_returns_message(client, monkeypatch):
    """Test DELETE /validation/errors clears stored errors and returns confirmation."""
    mock_clear = MagicMock()
    monkeypatch.setattr(app_module, "clear_validation_errors", mock_clear)

    resp = client.delete("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["message"] == "Validation errors cleared"
    mock_clear.assert_called_once()