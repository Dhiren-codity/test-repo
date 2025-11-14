import pytest
from unittest.mock import Mock
from types import SimpleNamespace

from src.app import app as flask_app
import src.app as app_module


class DummyValidationError:
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message

    def to_dict(self):
        return {"field": self.field, "message": self.message}


@pytest.fixture
def app_client():
    """Provide a Flask test client with testing configuration."""
    flask_app.config.update({"TESTING": True})
    with flask_app.test_client() as client:
        with flask_app.app_context():
            yield client


def test_health_check_ok(app_client):
    """Test the health_check endpoint returns expected status payload."""
    resp = app_client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


@pytest.mark.parametrize(
    "endpoint",
    [
        "/review",
        "/statistics",
    ],
)
def test_post_endpoints_missing_body_returns_400(app_client, endpoint):
    """Test that POST endpoints return 400 when the request body is missing."""
    resp = app_client.post(endpoint)
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing request body"


def test_review_code_validation_error_returns_422(app_client, monkeypatch):
    """Test review_code endpoint returns validation error with details."""
    monkeypatch.setattr(
        app_module,
        "validate_review_request",
        lambda data: [DummyValidationError("content", "Content is required")],
    )

    resp = app_client.post("/review", json={"content": "", "language": "python"})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert isinstance(data["details"], list)
    assert data["details"][0]["field"] == "content"
    assert data["details"][0]["message"] == "Content is required"


def test_review_code_happy_path_returns_review_data(app_client, monkeypatch):
    """Test review_code endpoint returns formatted review results."""
    # Mock validation and sanitization
    monkeypatch.setattr(app_module, "validate_review_request", lambda data: [])
    monkeypatch.setattr(
        app_module,
        "sanitize_request_data",
        lambda data: {"content": "print(1)", "language": "python"},
    )

    # Mock reviewer with expected attributes in result
    issue = SimpleNamespace(severity="low", line=1, message="Test issue", suggestion="Fix it")
    result = SimpleNamespace(
        score=95,
        issues=[issue],
        suggestions=["Use better naming"],
        complexity_score=1.23,
    )
    reviewer_mock = Mock()
    reviewer_mock.review_code.return_value = result
    monkeypatch.setattr(app_module, "reviewer", reviewer_mock)

    resp = app_client.post("/review", json={"content": "ignored", "language": "ignored"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["score"] == 95
    assert data["issues"][0]["severity"] == "low"
    assert data["issues"][0]["line"] == 1
    assert data["issues"][0]["message"] == "Test issue"
    assert data["issues"][0]["suggestion"] == "Fix it"
    assert data["suggestions"] == ["Use better naming"]
    assert data["complexity_score"] == 1.23
    assert "correlation_id" in data  # May be None if middleware not setting it


def test_review_function_missing_field_returns_400(app_client):
    """Test review_function endpoint returns 400 when function_code is missing."""
    resp = app_client.post("/review/function", json={"foo": "bar"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing 'function_code' field"


def test_review_function_happy_path(app_client, monkeypatch):
    """Test review_function endpoint returns the reviewer's response."""
    reviewer_mock = Mock()
    reviewer_mock.review_function.return_value = {"summary": "ok", "issues": []}
    monkeypatch.setattr(app_module, "reviewer", reviewer_mock)

    payload = {"function_code": "def f():\n    return 1"}
    resp = app_client.post("/review/function", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"summary": "ok", "issues": []}
    reviewer_mock.review_function.assert_called_once_with(payload["function_code"])


def test_statistics_validation_error_returns_422(app_client, monkeypatch):
    """Test statistics endpoint returns 422 with details when validation fails."""
    monkeypatch.setattr(
        app_module,
        "validate_statistics_request",
        lambda data: [DummyValidationError("files", "Files list is required")],
    )

    resp = app_client.post("/statistics", json={"files": []})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"][0]["field"] == "files"
    assert data["details"][0]["message"] == "Files list is required"


def test_statistics_happy_path_returns_aggregates(app_client, monkeypatch):
    """Test statistics endpoint returns aggregated review statistics."""
    monkeypatch.setattr(app_module, "validate_statistics_request", lambda data: [])
    monkeypatch.setattr(
        app_module,
        "sanitize_request_data",
        lambda data: {"files": [{"path": "a.py", "content": "print(1)", "language": "python"}]},
    )

    stats_obj = SimpleNamespace(
        total_files=1,
        average_score=90.5,
        total_issues=3,
        issues_by_severity={"low": 2, "high": 1},
        average_complexity=1.1,
        files_with_high_complexity=["a.py"],
        total_suggestions=4,
    )
    aggregator_mock = Mock()
    aggregator_mock.aggregate_reviews.return_value = stats_obj
    monkeypatch.setattr(app_module, "statistics_aggregator", aggregator_mock)

    resp = app_client.post("/statistics", json={"files": []})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_files"] == 1
    assert data["average_score"] == 90.5
    assert data["total_issues"] == 3
    assert data["issues_by_severity"] == {"low": 2, "high": 1}
    assert data["average_complexity"] == 1.1
    assert data["files_with_high_complexity"] == ["a.py"]
    assert data["total_suggestions"] == 4
    assert "correlation_id" in data


def test_list_traces_returns_all(app_client, monkeypatch):
    """Test traces listing returns total and items."""
    traces = [{"id": "t1"}, {"id": "t2"}]
    monkeypatch.setattr(app_module, "get_all_traces", lambda: traces)

    resp = app_client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == 2
    assert data["traces"] == traces


def test_get_trace_not_found_returns_404(app_client, monkeypatch):
    """Test get_trace returns 404 when no traces found for the given correlation ID."""
    monkeypatch.setattr(app_module, "get_traces", lambda cid: [])

    resp = app_client.get("/traces/abc123")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["error"] == "No traces found for correlation ID"


def test_get_trace_found_returns_traces(app_client, monkeypatch):
    """Test get_trace returns traces and count for a valid correlation ID."""
    sample_traces = [{"step": "init"}, {"step": "review"}]
    monkeypatch.setattr(app_module, "get_traces", lambda cid: sample_traces)

    correlation_id = "corr-001"
    resp = app_client.get(f"/traces/{correlation_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] == correlation_id
    assert data["trace_count"] == 2
    assert data["traces"] == sample_traces


def test_list_validation_errors_returns_errors(app_client, monkeypatch):
    """Test listing of validation errors returns total and errors."""
    errors = [{"field": "content", "message": "missing"}, {"field": "files", "message": "empty"}]
    monkeypatch.setattr(app_module, "get_validation_errors", lambda: errors)

    resp = app_client.get("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == 2
    assert data["errors"] == errors


def test_delete_validation_errors_clears_and_returns_message(app_client, monkeypatch):
    """Test deletion of validation errors triggers clear and returns confirmation."""
    clear_mock = Mock()
    monkeypatch.setattr(app_module, "clear_validation_errors", clear_mock)

    resp = app_client.delete("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["message"] == "Validation errors cleared"
    clear_mock.assert_called_once()