import pytest
from unittest.mock import Mock
import importlib
from types import SimpleNamespace

from src.app import app as flask_app


@pytest.fixture
def app_client():
    """Create a Flask test client and set a correlation_id before each request."""
    app_module = importlib.import_module("src.app")
    app = flask_app
    app.testing = True

    @app.before_request
    def set_test_correlation_id():
        from flask import g
        g.correlation_id = "test-correlation-id"

    return app.test_client()


def test_health_check_ok(app_client):
    """Test /health endpoint returns healthy status."""
    resp = app_client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


@pytest.mark.parametrize("endpoint", ["/review", "/statistics"])
def test_post_endpoints_missing_body_returns_400(app_client, endpoint):
    """Test that POST endpoints return 400 when request body is missing."""
    resp = app_client.post(endpoint)
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data


def test_review_code_validation_error_returns_422(app_client, monkeypatch):
    """Test /review returns 422 when validation fails."""
    app_module = importlib.import_module("src.app")

    mock_error1 = Mock()
    mock_error1.to_dict.return_value = {"field": "content", "message": "required"}
    mock_error2 = Mock()
    mock_error2.to_dict.return_value = {"field": "language", "message": "unsupported"}

    monkeypatch.setattr(app_module, "validate_review_request", lambda data: [mock_error1, mock_error2])
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: data)

    resp = app_client.post("/review", json={"content": "", "language": "unknown"})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert isinstance(data["details"], list)
    assert data["details"][0]["field"] == "content"
    assert data["details"][1]["field"] == "language"


def test_review_code_success_returns_result_and_correlation_id(app_client, monkeypatch):
    """Test /review success path returns transformed result and correlation_id."""
    app_module = importlib.import_module("src.app")

    # Mock validation and sanitization
    monkeypatch.setattr(app_module, "validate_review_request", lambda data: [])
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: data)

    # Mock reviewer and its return object
    issue1 = SimpleNamespace(severity="high", line=10, message="Use of eval", suggestion="Avoid eval")
    issue2 = SimpleNamespace(severity="low", line=2, message="Trailing whitespace", suggestion="Remove trailing spaces")
    review_result = SimpleNamespace(
        score=85,
        issues=[issue1, issue2],
        suggestions=["Refactor to remove duplicates"],
        complexity_score=3.5,
    )
    reviewer_mock = Mock()
    reviewer_mock.review_code.return_value = review_result
    monkeypatch.setattr(app_module, "reviewer", reviewer_mock)

    payload = {"content": "print('hello')", "language": "python"}
    resp = app_client.post("/review", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()

    reviewer_mock.review_code.assert_called_once_with("print('hello')", "python")
    assert data["score"] == 85
    assert data["complexity_score"] == 3.5
    assert len(data["issues"]) == 2
    assert data["issues"][0]["severity"] == "high"
    assert data["suggestions"] == ["Refactor to remove duplicates"]
    assert data["correlation_id"] == "test-correlation-id"


@pytest.mark.parametrize("payload", [None, {}, {"foo": "bar"}])
def test_review_function_missing_field_returns_400(app_client, payload):
    """Test /review/function returns 400 when 'function_code' is missing or body is None."""
    resp = app_client.post("/review/function", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data


def test_review_function_success_returns_json(app_client, monkeypatch):
    """Test /review/function success path returns reviewer output."""
    app_module = importlib.import_module("src.app")

    reviewer_mock = Mock()
    reviewer_mock.review_function.return_value = {"issues": [], "score": 100}
    monkeypatch.setattr(app_module, "reviewer", reviewer_mock)

    payload = {"function_code": "def foo():\n    pass"}
    resp = app_client.post("/review/function", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()

    reviewer_mock.review_function.assert_called_once_with("def foo():\n    pass")
    assert data == {"issues": [], "score": 100}


def test_statistics_validation_error_returns_422(app_client, monkeypatch):
    """Test /statistics returns 422 when validation fails."""
    app_module = importlib.import_module("src.app")

    mock_error = Mock()
    mock_error.to_dict.return_value = {"field": "files", "message": "must be a list"}
    monkeypatch.setattr(app_module, "validate_statistics_request", lambda data: [mock_error])
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: data)

    resp = app_client.post("/statistics", json={"files": "not-a-list"})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"][0]["field"] == "files"


def test_statistics_success_returns_aggregated_values_and_correlation_id(app_client, monkeypatch):
    """Test /statistics success path returns aggregated statistics and correlation_id."""
    app_module = importlib.import_module("src.app")

    # Mock validation and sanitization
    monkeypatch.setattr(app_module, "validate_statistics_request", lambda data: [])
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: data)

    stats_obj = SimpleNamespace(
        total_files=3,
        average_score=90.5,
        total_issues=7,
        issues_by_severity={"low": 3, "medium": 2, "high": 2},
        average_complexity=2.3,
        files_with_high_complexity=["a.py", "b.py"],
        total_suggestions=5,
    )
    stats_mock = Mock()
    stats_mock.aggregate_reviews.return_value = stats_obj
    monkeypatch.setattr(app_module, "statistics_aggregator", stats_mock)

    payload = {"files": [{"content": "code1"}, {"content": "code2"}, {"content": "code3"}]}
    resp = app_client.post("/statistics", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()

    stats_mock.aggregate_reviews.assert_called_once_with(payload["files"])
    assert data["total_files"] == 3
    assert data["average_score"] == 90.5
    assert data["total_issues"] == 7
    assert data["issues_by_severity"] == {"low": 3, "medium": 2, "high": 2}
    assert data["average_complexity"] == 2.3
    assert data["files_with_high_complexity"] == ["a.py", "b.py"]
    assert data["total_suggestions"] == 5
    assert data["correlation_id"] == "test-correlation-id"


def test_list_traces_returns_all(app_client, monkeypatch):
    """Test /traces returns list of all traces with total count."""
    app_module = importlib.import_module("src.app")

    traces = [{"id": "t1"}, {"id": "t2"}]
    monkeypatch.setattr(app_module, "get_all_traces", lambda: traces)

    resp = app_client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == 2
    assert data["traces"] == traces


def test_get_trace_found_returns_data(app_client, monkeypatch):
    """Test /traces/<correlation_id> returns traces when found."""
    app_module = importlib.import_module("src.app")

    test_traces = [{"event": "start"}, {"event": "end"}]
    monkeypatch.setattr(app_module, "get_traces", lambda cid: test_traces if cid == "abc" else [])

    resp = app_client.get("/traces/abc")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] == "abc"
    assert data["trace_count"] == 2
    assert data["traces"] == test_traces


def test_get_trace_not_found_returns_404(app_client, monkeypatch):
    """Test /traces/<correlation_id> returns 404 when not found."""
    app_module = importlib.import_module("src.app")

    monkeypatch.setattr(app_module, "get_traces", lambda cid: [])

    resp = app_client.get("/traces/does-not-exist")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["error"] == "No traces found for correlation ID"


def test_list_validation_errors_returns_errors(app_client, monkeypatch):
    """Test /validation/errors GET returns list of validation errors."""
    app_module = importlib.import_module("src.app")

    errors = [{"field": "content", "message": "required"}, {"field": "language", "message": "invalid"}]
    monkeypatch.setattr(app_module, "get_validation_errors", lambda: errors)

    resp = app_client.get("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == 2
    assert data["errors"] == errors


def test_delete_validation_errors_clears_and_returns_message(app_client, monkeypatch):
    """Test /validation/errors DELETE clears errors and returns confirmation."""
    app_module = importlib.import_module("src.app")

    clear_mock = Mock()
    monkeypatch.setattr(app_module, "clear_validation_errors", clear_mock)

    resp = app_client.delete("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"message": "Validation errors cleared"}
    clear_mock.assert_called_once_with()