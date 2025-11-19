import sys
import pytest
from unittest.mock import Mock

from src.app import app

app_module = sys.modules["src.app"]


@pytest.fixture
def client():
    """Flask test client fixture."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


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


class DummyValidationError:
    def __init__(self, code="invalid", message="Invalid input", field=None):
        self.code = code
        self.message = message
        self.field = field

    def to_dict(self):
        data = {"code": self.code, "message": self.message}
        if self.field is not None:
            data["field"] = self.field
        return data


def test_health_check_ok(client):
    """Test that GET /health returns healthy status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


@pytest.mark.parametrize(
    "payload",
    [
        None,  # Missing body
        {},  # Empty JSON object
    ],
)
def test_review_code_missing_body(client, payload):
    """Test POST /review returns 400 for missing or empty body."""
    if payload is None:
        resp = client.post("/review")
    else:
        resp = client.post("/review", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data
    assert data["error"] == "Missing request body"


def test_review_code_validation_errors(client, monkeypatch):
    """Test POST /review returns 422 with validation errors."""
    errors = [
        DummyValidationError(code="required", message="content is required", field="content"),
        DummyValidationError(code="invalid", message="language not supported", field="language"),
    ]
    monkeypatch.setattr(app_module, "validate_review_request", lambda d: errors)
    sanitize_mock = Mock(return_value={})
    monkeypatch.setattr(app_module, "sanitize_request_data", sanitize_mock)

    resp = client.post("/review", json={"content": "", "language": "unknown"})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"] == [e.to_dict() for e in errors]
    # sanitize should not be called when validation fails
    assert sanitize_mock.call_count == 0


def test_review_code_success(client, monkeypatch):
    """Test POST /review succeeds and returns structured response."""
    # No validation errors
    monkeypatch.setattr(app_module, "validate_review_request", lambda d: [])
    posted_payload = {"content": "print('hi')", "language": "python"}
    sanitized = {"content": "print('hi')", "language": "python"}
    sanitize_mock = Mock(return_value=sanitized)
    monkeypatch.setattr(app_module, "sanitize_request_data", sanitize_mock)

    # Mock reviewer and result
    mock_reviewer = Mock()
    issues = [
        DummyIssue("high", 1, "Avoid print in production", "Use logging instead"),
        DummyIssue("low", 2, "Trailing whitespace", "Remove trailing spaces"),
    ]
    review_result = DummyReviewResult(
        score=85,
        issues=issues,
        suggestions=["Consider using f-strings"],
        complexity_score=3.2,
    )
    mock_reviewer.review_code.return_value = review_result
    monkeypatch.setattr(app_module, "reviewer", mock_reviewer)

    resp = client.post("/review", json=posted_payload)
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["score"] == 85
    assert data["suggestions"] == ["Consider using f-strings"]
    assert data["complexity_score"] == 3.2
    assert isinstance(data.get("issues"), list)
    assert data["issues"][0]["severity"] == "high"
    assert data["issues"][0]["line"] == 1
    assert data["issues"][0]["message"] == "Avoid print in production"
    assert data["issues"][0]["suggestion"] == "Use logging instead"
    assert "correlation_id" in data

    sanitize_mock.assert_called_once()
    assert sanitize_mock.call_args[0][0] == posted_payload
    mock_reviewer.review_code.assert_called_once_with(
        sanitized["content"], sanitized["language"]
    )


@pytest.mark.parametrize(
    "payload",
    [
        None,  # Missing body entirely
        {},  # Missing 'function_code' field
    ],
)
def test_review_function_missing_input(client, payload):
    """Test POST /review/function returns 400 for missing input."""
    if payload is None:
        resp = client.post("/review/function")
    else:
        resp = client.post("/review/function", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing 'function_code' field"


def test_review_function_success(client, monkeypatch):
    """Test POST /review/function returns reviewer output."""
    mock_reviewer = Mock()
    result = {"ok": True, "issues": 0, "notes": ["Looks fine"]}
    mock_reviewer.review_function.return_value = result
    monkeypatch.setattr(app_module, "reviewer", mock_reviewer)

    payload = {"function_code": "def add(a,b): return a+b"}
    resp = client.post("/review/function", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == result
    mock_reviewer.review_function.assert_called_once_with(payload["function_code"])


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
    ],
)
def test_statistics_missing_body(client, payload):
    """Test POST /statistics returns 400 when body is missing or empty."""
    if payload is None:
        resp = client.post("/statistics")
    else:
        resp = client.post("/statistics", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing request body"


def test_statistics_validation_errors(client, monkeypatch):
    """Test POST /statistics returns 422 when validation fails."""
    errors = [DummyValidationError(code="required", message="'files' is required", field="files")]
    monkeypatch.setattr(app_module, "validate_statistics_request", lambda d: errors)
    sanitize_mock = Mock(return_value={})
    monkeypatch.setattr(app_module, "sanitize_request_data", sanitize_mock)

    resp = client.post("/statistics", json={"files": None})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"] == [e.to_dict() for e in errors]
    assert sanitize_mock.call_count == 0


def test_statistics_success(client, monkeypatch):
    """Test POST /statistics succeeds and returns aggregated stats."""
    monkeypatch.setattr(app_module, "validate_statistics_request", lambda d: [])
    sanitized = {
        "files": [
            {"content": "print('hi')", "language": "python"},
            {"content": "x=1", "language": "python"},
        ]
    }
    sanitize_mock = Mock(return_value=sanitized)
    monkeypatch.setattr(app_module, "sanitize_request_data", sanitize_mock)

    mock_aggregator = Mock()
    stats_obj = DummyStats(
        total_files=2,
        average_score=90.5,
        total_issues=3,
        issues_by_severity={"low": 2, "high": 1},
        average_complexity=2.1,
        files_with_high_complexity=["file1.py"],
        total_suggestions=4,
    )
    mock_aggregator.aggregate_reviews.return_value = stats_obj
    monkeypatch.setattr(app_module, "statistics_aggregator", mock_aggregator)

    resp = client.post("/statistics", json={"files": ["dummy"]})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_files"] == 2
    assert data["average_score"] == 90.5
    assert data["total_issues"] == 3
    assert data["issues_by_severity"] == {"low": 2, "high": 1}
    assert data["average_complexity"] == 2.1
    assert data["files_with_high_complexity"] == ["file1.py"]
    assert data["total_suggestions"] == 4
    assert "correlation_id" in data

    sanitize_mock.assert_called_once()
    mock_aggregator.aggregate_reviews.assert_called_once_with(sanitized["files"])


def test_list_traces_success(client, monkeypatch):
    """Test GET /traces returns all traces with count."""
    traces = [
        {"correlation_id": "abc", "event": "start"},
        {"correlation_id": "def", "event": "end"},
    ]
    monkeypatch.setattr(app_module, "get_all_traces", lambda: traces)

    resp = client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == len(traces)
    assert data["traces"] == traces


def test_get_trace_not_found(client, monkeypatch):
    """Test GET /traces/<correlation_id> returns 404 when no traces found."""
    monkeypatch.setattr(app_module, "get_traces", lambda cid: [])

    resp = client.get("/traces/unknown-id")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["error"] == "No traces found for correlation ID"


def test_get_trace_success(client, monkeypatch):
    """Test GET /traces/<correlation_id> returns traces for the given ID."""
    traces = [{"event": "start"}, {"event": "step1"}, {"event": "end"}]
    monkeypatch.setattr(app_module, "get_traces", lambda cid: traces)

    cid = "abc-123"
    resp = client.get(f"/traces/{cid}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] == cid
    assert data["trace_count"] == len(traces)
    assert data["traces"] == traces


def test_list_validation_errors(client, monkeypatch):
    """Test GET /validation/errors returns current validation errors."""
    errors = [
        {"code": "required", "field": "content"},
        {"code": "invalid", "field": "language"},
    ]
    monkeypatch.setattr(app_module, "get_validation_errors", lambda: errors)

    resp = client.get("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == len(errors)
    assert data["errors"] == errors


def test_delete_validation_errors(client, monkeypatch):
    """Test DELETE /validation/errors clears errors and returns confirmation."""
    clear_mock = Mock()
    monkeypatch.setattr(app_module, "clear_validation_errors", clear_mock)

    resp = client.delete("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["message"] == "Validation errors cleared"
    clear_mock.assert_called_once()