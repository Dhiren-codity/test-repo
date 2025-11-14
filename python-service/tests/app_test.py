import sys
from types import ModuleType
import pytest
from unittest.mock import Mock

def _ensure_dummy_modules():
    """Ensure external dependencies are available as dummy modules before importing src.app."""
    # src.code_reviewer
    if 'src.code_reviewer' not in sys.modules:
        mod = ModuleType('src.code_reviewer')
        class CodeReviewer:  # minimal placeholder
            def review_code(self, content, language):
                return None
            def review_function(self, function_code):
                return {}
        mod.CodeReviewer = CodeReviewer
        sys.modules['src.code_reviewer'] = mod

    # src.statistics
    if 'src.statistics' not in sys.modules:
        mod = ModuleType('src.statistics')
        class StatisticsAggregator:  # minimal placeholder
            def aggregate_reviews(self, files):
                return None
        mod.StatisticsAggregator = StatisticsAggregator
        sys.modules['src.statistics'] = mod

    # src.correlation_middleware
    if 'src.correlation_middleware' not in sys.modules:
        mod = ModuleType('src.correlation_middleware')
        class CorrelationIDMiddleware:
            def __init__(self, app):
                pass
        def get_traces(correlation_id):
            return []
        def get_all_traces():
            return []
        mod.CorrelationIDMiddleware = CorrelationIDMiddleware
        mod.get_traces = get_traces
        mod.get_all_traces = get_all_traces
        sys.modules['src.correlation_middleware'] = mod

    # src.request_validator
    if 'src.request_validator' not in sys.modules:
        mod = ModuleType('src.request_validator')
        def validate_review_request(data):
            return []
        def validate_statistics_request(data):
            return []
        def sanitize_request_data(data):
            return data
        def get_validation_errors():
            return []
        def clear_validation_errors():
            pass
        mod.validate_review_request = validate_review_request
        mod.validate_statistics_request = validate_statistics_request
        mod.sanitize_request_data = sanitize_request_data
        mod.get_validation_errors = get_validation_errors
        mod.clear_validation_errors = clear_validation_errors
        sys.modules['src.request_validator'] = mod


@pytest.fixture
def app_and_module(monkeypatch):
    """Prepare Flask app and module with dummy dependencies and default mocks."""
    _ensure_dummy_modules()
    from src.app import app as flask_app  # required exact import
    import src.app as app_module

    # Put app in testing mode
    flask_app.testing = True

    # Default mocks for services and validators; can be overridden in tests
    monkeypatch.setattr(app_module, 'reviewer', Mock(name='reviewer'))
    monkeypatch.setattr(app_module, 'statistics_aggregator', Mock(name='statistics_aggregator'))
    monkeypatch.setattr(app_module, 'validate_review_request', lambda data: [])
    monkeypatch.setattr(app_module, 'validate_statistics_request', lambda data: [])
    monkeypatch.setattr(app_module, 'sanitize_request_data', lambda data: data)
    monkeypatch.setattr(app_module, 'get_all_traces', lambda: [])
    monkeypatch.setattr(app_module, 'get_traces', lambda cid: [])
    monkeypatch.setattr(app_module, 'get_validation_errors', lambda: [])
    monkeypatch.setattr(app_module, 'clear_validation_errors', lambda: None)

    return flask_app, app_module


@pytest.fixture
def client(app_and_module):
    """Return Flask test client."""
    flask_app, _ = app_and_module
    return flask_app.test_client()


def test_health_check_happy_path(client):
    """GET /health should return healthy status and service name."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


def test_review_code_missing_body_returns_400(client):
    """POST /review with missing JSON body should return 400."""
    # Send explicit JSON null to ensure request.get_json() returns None
    resp = client.post("/review", json=None)
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing request body"


def test_review_code_validation_error_returns_422(app_and_module, client, monkeypatch):
    """POST /review with validation errors should return 422 and details."""
    _, app_module = app_and_module

    class DummyError:
        def __init__(self, field, message):
            self.field = field
            self.message = message
        def to_dict(self):
            return {"field": self.field, "message": self.message}

    errors = [DummyError("content", "Content is required")]
    monkeypatch.setattr(app_module, 'validate_review_request', lambda data: errors)

    resp = client.post("/review", json={"content": ""})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "Validation failed"
    assert body["details"] == [e.to_dict() for e in errors]


@pytest.mark.parametrize(
    "payload,review_result",
    [
        (
            {"content": "print('hi')", "language": "python"},
            {
                "score": 95,
                "issues": [
                    {"severity": "low", "line": 1, "message": "OK", "suggestion": "None"}
                ],
                "suggestions": ["Looks good"],
                "complexity_score": 1.0,
            },
        ),
        (
            {"content": "console.log('x')", "language": "javascript"},
            {
                "score": 80,
                "issues": [
                    {"severity": "medium", "line": 1, "message": "Use const", "suggestion": "Use const instead of var"}
                ],
                "suggestions": ["Refactor variable usage"],
                "complexity_score": 2.5,
            },
        ),
    ],
)
def test_review_code_success_returns_expected_json(app_and_module, client, monkeypatch, payload, review_result):
    """POST /review with valid payload should return computed review result."""
    _, app_module = app_and_module

    class Issue:
        def __init__(self, severity, line, message, suggestion):
            self.severity = severity
            self.line = line
            self.message = message
            self.suggestion = suggestion

    class ReviewResult:
        def __init__(self, score, issues, suggestions, complexity_score):
            self.score = score
            self.issues = [Issue(**i) for i in issues]
            self.suggestions = suggestions
            self.complexity_score = complexity_score

    result_obj = ReviewResult(**review_result)
    app_module.reviewer.review_code.return_value = result_obj

    resp = client.post("/review", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["score"] == review_result["score"]
    assert data["issues"] == review_result["issues"]
    assert data["suggestions"] == review_result["suggestions"]
    assert data["complexity_score"] == review_result["complexity_score"]
    assert "correlation_id" in data  # may be None when middleware not active


def test_review_function_missing_field_returns_400(client):
    """POST /review/function without function_code should return 400."""
    resp = client.post("/review/function", json={})
    assert resp.status_code == 400
    body = resp.get_json()
    assert "Missing 'function_code' field" in body["error"]


def test_review_function_success_returns_result(app_and_module, client):
    """POST /review/function with function_code should return reviewer result."""
    _, app_module = app_and_module
    expected = {"score": 100, "notes": "Pure function"}
    app_module.reviewer.review_function.return_value = expected

    resp = client.post("/review/function", json={"function_code": "def f(): return 1"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == expected


def test_statistics_missing_body_returns_400(client):
    """POST /statistics with missing body should return 400."""
    resp = client.post("/statistics", json=None)
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "Missing request body"


def test_statistics_validation_error_returns_422(app_and_module, client, monkeypatch):
    """POST /statistics with validation errors should return 422 and details."""
    _, app_module = app_and_module

    class DummyError:
        def __init__(self, field, message):
            self.field = field
            self.message = message
        def to_dict(self):
            return {"field": self.field, "message": self.message}

    errors = [DummyError("files", "Files list is required")]
    monkeypatch.setattr(app_module, 'validate_statistics_request', lambda data: errors)

    resp = client.post("/statistics", json={"files": None})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"] == [e.to_dict() for e in errors]


def test_statistics_success_returns_aggregated_data(app_and_module, client):
    """POST /statistics with valid files should return aggregated stats."""
    _, app_module = app_and_module

    class Stats:
        def __init__(self):
            self.total_files = 3
            self.average_score = 88.5
            self.total_issues = 7
            self.issues_by_severity = {"low": 5, "high": 2}
            self.average_complexity = 3.2
            self.files_with_high_complexity = ["a.py", "b.py"]
            self.total_suggestions = 4

    app_module.statistics_aggregator.aggregate_reviews.return_value = Stats()

    payload = {"files": [{"name": "a.py"}, {"name": "b.py"}, {"name": "c.py"}]}
    resp = client.post("/statistics", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["total_files"] == 3
    assert data["average_score"] == 88.5
    assert data["total_issues"] == 7
    assert data["issues_by_severity"] == {"low": 5, "high": 2}
    assert data["average_complexity"] == 3.2
    assert data["files_with_high_complexity"] == ["a.py", "b.py"]
    assert data["total_suggestions"] == 4
    assert "correlation_id" in data  # may be None


def test_list_traces_returns_all_traces(app_and_module, client, monkeypatch):
    """GET /traces should return all traces with total count."""
    _, app_module = app_and_module
    traces = [{"id": "t1"}, {"id": "t2"}]
    monkeypatch.setattr(app_module, 'get_all_traces', lambda: traces)

    resp = client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == 2
    assert data["traces"] == traces


def test_get_trace_not_found_returns_404(app_and_module, client, monkeypatch):
    """GET /traces/<id> with unknown id should return 404."""
    _, app_module = app_and_module
    monkeypatch.setattr(app_module, 'get_traces', lambda cid: [])

    resp = client.get("/traces/unknown-id")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["error"] == "No traces found for correlation ID"


def test_get_trace_found_returns_trace_details(app_and_module, client, monkeypatch):
    """GET /traces/<id> should return trace list and count."""
    _, app_module = app_and_module
    found_traces = [{"step": "start"}, {"step": "end"}]
    monkeypatch.setattr(app_module, 'get_traces', lambda cid: found_traces)

    cid = "corr-123"
    resp = client.get(f"/traces/{cid}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] == cid
    assert data["trace_count"] == len(found_traces)
    assert data["traces"] == found_traces


def test_list_validation_errors_returns_errors(app_and_module, client, monkeypatch):
    """GET /validation/errors should return all collected validation errors."""
    _, app_module = app_and_module
    errors = [{"field": "content", "message": "Too short"}]
    monkeypatch.setattr(app_module, 'get_validation_errors', lambda: errors)

    resp = client.get("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == 1
    assert data["errors"] == errors


def test_delete_validation_errors_clears_and_returns_message(app_and_module, client, monkeypatch):
    """DELETE /validation/errors should clear errors and return confirmation message."""
    _, app_module = app_and_module
    cleared = {"called": False}
    def _clear():
        cleared["called"] = True
    monkeypatch.setattr(app_module, 'clear_validation_errors', _clear)

    resp = client.delete("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["message"] == "Validation errors cleared"
    assert cleared["called"] is True