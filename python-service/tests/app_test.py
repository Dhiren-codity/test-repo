import sys
import types
from types import SimpleNamespace
import pytest
from unittest.mock import Mock

# Prepare stub modules before importing the Flask app
code_reviewer_mod = types.ModuleType("src.code_reviewer")


class StubCodeReviewer:
    def review_code(self, content, language):
        return SimpleNamespace(score=0, issues=[], suggestions=[], complexity_score=0)

    def review_function(self, function_code):
        return {"status": "ok"}


code_reviewer_mod.CodeReviewer = StubCodeReviewer

statistics_mod = types.ModuleType("src.statistics")


class StubStatisticsAggregator:
    def aggregate_reviews(self, files):
        return SimpleNamespace(
            total_files=0,
            average_score=0,
            total_issues=0,
            issues_by_severity={},
            average_complexity=0,
            files_with_high_complexity=[],
            total_suggestions=0,
        )


statistics_mod.StatisticsAggregator = StubStatisticsAggregator

correlation_mod = types.ModuleType("src.correlation_middleware")


class StubCorrelationIDMiddleware:
    def __init__(self, app):
        self.app = app


def stub_get_traces(correlation_id):
    return []


def stub_get_all_traces():
    return []


correlation_mod.CorrelationIDMiddleware = StubCorrelationIDMiddleware
correlation_mod.get_traces = stub_get_traces
correlation_mod.get_all_traces = stub_get_all_traces

request_validator_mod = types.ModuleType("src.request_validator")


def stub_validate_review_request(data):
    return []


def stub_validate_statistics_request(data):
    return []


def stub_sanitize_request_data(data):
    return data


_validation_errors_store = []


def stub_get_validation_errors():
    return list(_validation_errors_store)


def stub_clear_validation_errors():
    _validation_errors_store.clear()


request_validator_mod.validate_review_request = stub_validate_review_request
request_validator_mod.validate_statistics_request = stub_validate_statistics_request
request_validator_mod.sanitize_request_data = stub_sanitize_request_data
request_validator_mod.get_validation_errors = stub_get_validation_errors
request_validator_mod.clear_validation_errors = stub_clear_validation_errors

# Insert stubs into sys.modules
sys.modules.setdefault("src.code_reviewer", code_reviewer_mod)
sys.modules.setdefault("src.statistics", statistics_mod)
sys.modules.setdefault("src.correlation_middleware", correlation_mod)
sys.modules.setdefault("src.request_validator", request_validator_mod)

from src.app import app  # EXACT import
import src.app as app_module


@pytest.fixture
def client():
    app.testing = True
    return app.test_client()


def test_health_check_returns_status(client):
    """Test /health returns healthy status and service name."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


@pytest.mark.parametrize(
    "payload, use_json",
    [
        (None, False),  # No body
        ({}, True),     # Empty object
    ],
)
def test_review_code_missing_body_returns_400(client, payload, use_json):
    """Test /review returns 400 when request body is missing or empty."""
    if use_json:
        resp = client.post("/review", json=payload)
    else:
        resp = client.post("/review")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing request body"


def test_review_code_validation_failure_returns_422(client, monkeypatch):
    """Test /review returns 422 when validation fails with details."""
    class Err:
        def __init__(self, field, message, code):
            self.field = field
            self.message = message
            self.code = code

        def to_dict(self):
            return {"field": self.field, "message": self.message, "code": self.code}

    monkeypatch.setattr(app_module, "validate_review_request", lambda data: [Err("content", "required", "missing")])

    resp = client.post("/review", json={"language": "python"})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert isinstance(data["details"], list)
    assert data["details"][0]["field"] == "content"
    assert data["details"][0]["code"] == "missing"


def test_review_code_success_returns_result(client, monkeypatch):
    """Test /review returns formatted review result on success."""
    issues = [
        SimpleNamespace(severity="warning", line=10, message="Use of print", suggestion="Use logging instead"),
        SimpleNamespace(severity="error", line=20, message="Unused import", suggestion="Remove unused import"),
    ]
    review_result = SimpleNamespace(
        score=87,
        issues=issues,
        suggestions=["Consider refactoring"],
        complexity_score=3.14,
    )

    monkeypatch.setattr(app_module, "validate_review_request", lambda data: [])
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: data)
    reviewer_mock = Mock()
    reviewer_mock.review_code.return_value = review_result
    monkeypatch.setattr(app_module, "reviewer", reviewer_mock)

    resp = client.post("/review", json={"content": "print('hello')", "language": "python"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["score"] == 87
    assert data["complexity_score"] == 3.14
    assert data["suggestions"] == ["Consider refactoring"]
    assert data["correlation_id"] is None
    assert isinstance(data["issues"], list)
    assert data["issues"][0]["severity"] == "warning"
    assert data["issues"][0]["line"] == 10
    assert data["issues"][0]["message"] == "Use of print"
    assert data["issues"][0]["suggestion"] == "Use logging instead"
    reviewer_mock.review_code.assert_called_once_with("print('hello')", "python")


@pytest.mark.parametrize(
    "payload, use_json",
    [
        (None, False),
        ({}, True),
        ({"foo": "bar"}, True),
    ],
)
def test_review_function_missing_field_returns_400(client, payload, use_json):
    """Test /review/function returns 400 when function_code is missing."""
    if use_json:
        resp = client.post("/review/function", json=payload)
    else:
        resp = client.post("/review/function")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing 'function_code' field"


def test_review_function_success_returns_result(client, monkeypatch):
    """Test /review/function returns the underlying reviewer result."""
    reviewer_mock = Mock()
    reviewer_mock.review_function.return_value = {"ok": True, "score": 95}
    monkeypatch.setattr(app_module, "reviewer", reviewer_mock)

    resp = client.post("/review/function", json={"function_code": "def foo():\n    return 1"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"ok": True, "score": 95}
    reviewer_mock.review_function.assert_called_once()


@pytest.mark.parametrize(
    "payload, use_json",
    [
        (None, False),
        ({}, True),
    ],
)
def test_statistics_missing_body_returns_400(client, payload, use_json):
    """Test /statistics returns 400 when request body is missing or empty."""
    if use_json:
        resp = client.post("/statistics", json=payload)
    else:
        resp = client.post("/statistics")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing request body"


def test_statistics_validation_failure_returns_422(client, monkeypatch):
    """Test /statistics returns 422 when validation fails with details."""
    class Err:
        def __init__(self, field, message, code):
            self.field = field
            self.message = message
            self.code = code

        def to_dict(self):
            return {"field": self.field, "message": self.message, "code": self.code}

    monkeypatch.setattr(app_module, "validate_statistics_request", lambda data: [Err("files", "required", "missing")])

    resp = client.post("/statistics", json={"files": []})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"][0]["field"] == "files"
    assert data["details"][0]["code"] == "missing"


def test_statistics_success_returns_aggregates(client, monkeypatch):
    """Test /statistics returns aggregated statistics on success."""
    monkeypatch.setattr(app_module, "validate_statistics_request", lambda data: [])
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: data)

    stats_result = SimpleNamespace(
        total_files=3,
        average_score=88.5,
        total_issues=7,
        issues_by_severity={"info": 2, "warning": 3, "error": 2},
        average_complexity=2.7,
        files_with_high_complexity=["a.py"],
        total_suggestions=5,
    )
    stats_mock = Mock()
    stats_mock.aggregate_reviews.return_value = stats_result
    monkeypatch.setattr(app_module, "statistics_aggregator", stats_mock)

    resp = client.post("/statistics", json={"files": [{"content": "x"}, {"content": "y"}]})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_files"] == 3
    assert data["average_score"] == 88.5
    assert data["total_issues"] == 7
    assert data["issues_by_severity"] == {"info": 2, "warning": 3, "error": 2}
    assert data["average_complexity"] == 2.7
    assert data["files_with_high_complexity"] == ["a.py"]
    assert data["total_suggestions"] == 5
    assert data["correlation_id"] is None
    stats_mock.aggregate_reviews.assert_called_once()


def test_list_traces_returns_all_traces(client, monkeypatch):
    """Test /traces returns total count and traces list."""
    traces = [{"event": "start"}, {"event": "end"}]
    monkeypatch.setattr(app_module, "get_all_traces", lambda: traces)

    resp = client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == 2
    assert data["traces"] == traces


def test_get_trace_not_found_returns_404(client, monkeypatch):
    """Test /traces/<id> returns 404 when traces are not found."""
    monkeypatch.setattr(app_module, "get_traces", lambda cid: [])

    resp = client.get("/traces/xyz-123")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["error"] == "No traces found for correlation ID"


def test_get_trace_success_returns_trace(client, monkeypatch):
    """Test /traces/<id> returns traces with correlation ID and count."""
    traces = [{"event": "review_started"}, {"event": "review_finished"}]
    monkeypatch.setattr(app_module, "get_traces", lambda cid: traces)

    correlation_id = "abc-123"
    resp = client.get(f"/traces/{correlation_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] == correlation_id
    assert data["trace_count"] == 2
    assert data["traces"] == traces


def test_list_validation_errors_returns_errors(client, monkeypatch):
    """Test /validation/errors returns total errors and list."""
    errors = [{"field": "content", "message": "missing"}]
    monkeypatch.setattr(app_module, "get_validation_errors", lambda: errors)

    resp = client.get("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == 1
    assert data["errors"] == errors


def test_delete_validation_errors_clears_store(client, monkeypatch):
    """Test DELETE /validation/errors clears stored errors."""
    clear_mock = Mock()
    monkeypatch.setattr(app_module, "clear_validation_errors", clear_mock)

    resp = client.delete("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["message"] == "Validation errors cleared"
    assert clear_mock.called is True