import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.app import app


@pytest.fixture
def client():
    """Provide a Flask test client for the app."""
    app.testing = True
    with app.test_client() as client:
        yield client


def test_health_check_returns_ok(client):
    """Test GET /health returns healthy status and service name."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


@pytest.mark.parametrize("payload", [None, {}])
def test_review_code_missing_body_returns_400(client, payload):
    """Test POST /review returns 400 when body is missing or empty."""
    if payload is None:
        resp = client.post("/review")
    else:
        resp = client.post("/review", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing request body"


def test_review_code_validation_error_returns_422(client, monkeypatch):
    """Test POST /review returns 422 when validation fails."""
    class FakeError:
        def __init__(self, field):
            self.field = field

        def to_dict(self):
            return {"field": self.field, "message": "Invalid value"}

    monkeypatch.setattr("src.app.validate_review_request", lambda data: [FakeError("content"), FakeError("language")])
    resp = client.post("/review", json={"content": "print('hi')", "language": "python"})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert isinstance(data["details"], list)
    assert len(data["details"]) == 2
    assert {"field": "content", "message": "Invalid value"} in data["details"]


@pytest.mark.parametrize(
    "sanitized, expected_language",
    [
        ({"content": "print('ok')"}, "python"),
        ({"content": "console.log('ok')", "language": "javascript"}, "javascript"),
    ],
)
def test_review_code_success_returns_result_and_calls_reviewer(client, monkeypatch, sanitized, expected_language):
    """Test POST /review happy path returns computed review result and calls reviewer with correct args."""
    # Arrange validator and sanitizer
    monkeypatch.setattr("src.app.validate_review_request", lambda data: [])
    monkeypatch.setattr("src.app.sanitize_request_data", lambda data: sanitized)

    # Arrange reviewer return value
    issues = [
        SimpleNamespace(severity="high", line=10, message="Bad practice", suggestion="Do better"),
        SimpleNamespace(severity="low", line=5, message="Nitpick", suggestion="Optional"),
    ]
    review_result = SimpleNamespace(
        score=87,
        issues=issues,
        suggestions=["Refactor function foo"],
        complexity_score=3.7,
    )
    reviewer_mock = MagicMock()
    reviewer_mock.review_code.return_value = review_result
    monkeypatch.setattr("src.app.reviewer", reviewer_mock)

    # Also patch g to inject a correlation id explicitly
    monkeypatch.setattr("src.app.g", SimpleNamespace(correlation_id="cid-123"), raising=False)

    # Act
    req_payload = {"content": sanitized.get("content", ""), "language": sanitized.get("language")}
    resp = client.post("/review", json=req_payload)

    # Assert
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["score"] == 87
    assert data["complexity_score"] == 3.7
    assert len(data["issues"]) == 2
    assert data["issues"][0]["severity"] == "high"
    assert data["issues"][1]["line"] == 5
    assert data["suggestions"] == ["Refactor function foo"]
    assert data["correlation_id"] == "cid-123"

    # Ensure reviewer called with sanitized inputs
    reviewer_mock.review_code.assert_called_once_with(sanitized.get("content", ""), expected_language)


@pytest.mark.parametrize(
    "payload, expected_status",
    [
        (None, 400),
        ({}, 400),
        ({"wrong_key": "def f(): pass"}, 400),
    ],
)
def test_review_function_missing_field_returns_400(client, payload, expected_status):
    """Test POST /review/function returns 400 when 'function_code' is missing."""
    if payload is None:
        resp = client.post("/review/function")
    else:
        resp = client.post("/review/function", json=payload)
    assert resp.status_code == expected_status
    data = resp.get_json()
    assert "error" in data


def test_review_function_success_returns_result(client, monkeypatch):
    """Test POST /review/function happy path returns reviewer output."""
    result = {"score": 95, "issues": [], "suggestions": ["Add type hints"]}
    reviewer_mock = MagicMock()
    reviewer_mock.review_function.return_value = result
    monkeypatch.setattr("src.app.reviewer", reviewer_mock)

    resp = client.post("/review/function", json={"function_code": "def foo(): pass"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == result
    reviewer_mock.review_function.assert_called_once_with("def foo(): pass")


def test_get_statistics_missing_body_returns_400(client):
    """Test POST /statistics returns 400 when body is missing."""
    resp = client.post("/statistics")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing request body"


def test_get_statistics_validation_error_returns_422(client, monkeypatch):
    """Test POST /statistics returns 422 when validation fails."""
    class FakeError:
        def __init__(self, field):
            self.field = field

        def to_dict(self):
            return {"field": self.field, "message": "Invalid stats payload"}

    monkeypatch.setattr("src.app.validate_statistics_request", lambda data: [FakeError("files")])
    resp = client.post("/statistics", json={"files": []})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"] == [{"field": "files", "message": "Invalid stats payload"}]


def test_get_statistics_success_returns_aggregated_stats(client, monkeypatch):
    """Test POST /statistics happy path returns aggregated statistics and includes correlation id."""
    monkeypatch.setattr("src.app.validate_statistics_request", lambda data: [])
    sanitized = {"files": [{"content": "print(1)"}, {"content": "print(2)"}]}
    monkeypatch.setattr("src.app.sanitize_request_data", lambda data: sanitized)

    stats_result = SimpleNamespace(
        total_files=2,
        average_score=88.5,
        total_issues=4,
        issues_by_severity={"high": 1, "medium": 2, "low": 1},
        average_complexity=2.3,
        files_with_high_complexity=["a.py"],
        total_suggestions=3,
    )
    aggregator_mock = MagicMock()
    aggregator_mock.aggregate_reviews.return_value = stats_result
    monkeypatch.setattr("src.app.statistics_aggregator", aggregator_mock)

    monkeypatch.setattr("src.app.g", SimpleNamespace(correlation_id="stat-cid"), raising=False)

    resp = client.post("/statistics", json={"files": ["ignored"]})
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["total_files"] == 2
    assert data["average_score"] == 88.5
    assert data["total_issues"] == 4
    assert data["issues_by_severity"]["medium"] == 2
    assert data["average_complexity"] == 2.3
    assert data["files_with_high_complexity"] == ["a.py"]
    assert data["total_suggestions"] == 3
    assert data["correlation_id"] == "stat-cid"

    aggregator_mock.aggregate_reviews.assert_called_once_with(sanitized["files"])


def test_list_traces_returns_all_traces(client, monkeypatch):
    """Test GET /traces returns all traces and total count."""
    traces = [{"id": "t1"}, {"id": "t2"}, {"id": "t3"}]
    monkeypatch.setattr("src.app.get_all_traces", lambda: traces)
    resp = client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == 3
    assert data["traces"] == traces


def test_get_trace_found_returns_trace_info(client, monkeypatch):
    """Test GET /traces/<id> returns trace info when found."""
    monkeypatch.setattr("src.app.get_traces", lambda cid: ["ev1", "ev2"] if cid == "abc" else [])
    resp = client.get("/traces/abc")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] == "abc"
    assert data["trace_count"] == 2
    assert data["traces"] == ["ev1", "ev2"]


@pytest.mark.parametrize("lookup_result", [None, [], ()])
def test_get_trace_not_found_returns_404(client, monkeypatch, lookup_result):
    """Test GET /traces/<id> returns 404 when no traces are found."""
    monkeypatch.setattr("src.app.get_traces", lambda cid: lookup_result)
    resp = client.get("/traces/missing")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["error"] == "No traces found for correlation ID"


def test_list_validation_errors_returns_errors(client, monkeypatch):
    """Test GET /validation/errors returns total count and error list."""
    errors = [
        {"field": "content", "message": "Missing"},
        {"field": "language", "message": "Unsupported"},
    ]
    monkeypatch.setattr("src.app.get_validation_errors", lambda: errors)
    resp = client.get("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == 2
    assert data["errors"] == errors


def test_delete_validation_errors_clears_and_returns_message(client, monkeypatch):
    """Test DELETE /validation/errors clears errors and returns confirmation."""
    clear_mock = MagicMock()
    monkeypatch.setattr("src.app.clear_validation_errors", clear_mock)
    resp = client.delete("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["message"] == "Validation errors cleared"
    clear_mock.assert_called_once()