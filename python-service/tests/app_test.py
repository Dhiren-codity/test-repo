import sys
import types
from types import SimpleNamespace

import pytest
from unittest.mock import Mock

# ---- Create dummy dependency modules before importing the app ----
# This ensures src.app can be imported even if referenced modules aren't present.
if 'src.code_reviewer' not in sys.modules:
    code_reviewer_mod = types.ModuleType('src.code_reviewer')

    class DummyCodeReviewer:
        def review_code(self, content, language):
            return SimpleNamespace(
                score=0,
                issues=[],
                suggestions=[],
                complexity_score=0.0
            )

        def review_function(self, function_code):
            return {"ok": True, "function_code": function_code}

    code_reviewer_mod.CodeReviewer = DummyCodeReviewer
    sys.modules['src.code_reviewer'] = code_reviewer_mod

if 'src.statistics' not in sys.modules:
    statistics_mod = types.ModuleType('src.statistics')

    class DummyStatisticsAggregator:
        def aggregate_reviews(self, files):
            return SimpleNamespace(
                total_files=len(files),
                average_score=0.0,
                total_issues=0,
                issues_by_severity={},
                average_complexity=0.0,
                files_with_high_complexity=[],
                total_suggestions=0
            )

    statistics_mod.StatisticsAggregator = DummyStatisticsAggregator
    sys.modules['src.statistics'] = statistics_mod

if 'src.correlation_middleware' not in sys.modules:
    corr_mod = types.ModuleType('src.correlation_middleware')

    class DummyCorrelationIDMiddleware:
        def __init__(self, app):
            pass

    def dummy_get_traces(correlation_id):
        return []

    def dummy_get_all_traces():
        return []

    corr_mod.CorrelationIDMiddleware = DummyCorrelationIDMiddleware
    corr_mod.get_traces = dummy_get_traces
    corr_mod.get_all_traces = dummy_get_all_traces
    sys.modules['src.correlation_middleware'] = corr_mod

if 'src.request_validator' not in sys.modules:
    validator_mod = types.ModuleType('src.request_validator')

    def validate_review_request(data):
        return []

    def validate_statistics_request(data):
        return []

    def sanitize_request_data(data):
        return data

    _validation_errors = []

    def get_validation_errors():
        return list(_validation_errors)

    def clear_validation_errors():
        _validation_errors.clear()

    validator_mod.validate_review_request = validate_review_request
    validator_mod.validate_statistics_request = validate_statistics_request
    validator_mod.sanitize_request_data = sanitize_request_data
    validator_mod.get_validation_errors = get_validation_errors
    validator_mod.clear_validation_errors = clear_validation_errors
    sys.modules['src.request_validator'] = validator_mod

# ---- Import the app after dummy modules are set ----
from src.app import app  # noqa: E402
import src.app as app_module  # noqa: E402


@pytest.fixture
def client():
    """Flask test client fixture."""
    app.testing = True
    with app.test_client() as c:
        yield c


def test_health_check_returns_status(client):
    """GET /health should return healthy status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"status": "healthy", "service": "python-reviewer"}


def test_review_code_missing_body_returns_400(client):
    """POST /review without JSON body should return 400."""
    resp = client.post("/review", json=None)
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing request body"


def test_review_code_validation_failed_returns_422(client, monkeypatch):
    """POST /review with validation errors should return 422 with details."""
    class FakeError:
        def __init__(self, field, message):
            self.field = field
            self.message = message

        def to_dict(self):
            return {"field": self.field, "message": self.message}

    monkeypatch.setattr(app_module, "validate_review_request", lambda data: [FakeError("content", "required")])

    resp = client.post("/review", json={"content": ""})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert isinstance(data["details"], list)
    assert data["details"][0] == {"field": "content", "message": "required"}


def test_review_code_success_returns_result(client, monkeypatch):
    """POST /review with valid input returns reviewer result."""
    monkeypatch.setattr(app_module, "validate_review_request", lambda data: [])
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: {"content": "print('hi')", "language": "python"})

    class Issue:
        def __init__(self, severity, line, message, suggestion):
            self.severity = severity
            self.line = line
            self.message = message
            self.suggestion = suggestion

    result_obj = SimpleNamespace(
        score=85,
        issues=[Issue("warning", 1, "Use logging", "Replace print with logging")],
        suggestions=["Add docstring"],
        complexity_score=3.2,
    )

    mock_reviewer = Mock()
    mock_reviewer.review_code.return_value = result_obj
    monkeypatch.setattr(app_module, "reviewer", mock_reviewer)

    resp = client.post("/review", json={"content": "print('hi')", "language": "python"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["score"] == 85
    assert data["issues"][0]["severity"] == "warning"
    assert data["issues"][0]["line"] == 1
    assert data["issues"][0]["message"] == "Use logging"
    assert data["issues"][0]["suggestion"] == "Replace print with logging"
    assert data["suggestions"] == ["Add docstring"]
    assert data["complexity_score"] == 3.2
    assert "correlation_id" in data  # may be None by default


def test_review_code_includes_correlation_id_when_set(client, monkeypatch):
    """POST /review should include correlation_id when available in g."""
    monkeypatch.setattr(app_module, "validate_review_request", lambda data: [])
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: {"content": "code", "language": "python"})

    result_obj = SimpleNamespace(
        score=100,
        issues=[],
        suggestions=[],
        complexity_score=1.0,
    )
    mock_reviewer = Mock()
    mock_reviewer.review_code.return_value = result_obj
    monkeypatch.setattr(app_module, "reviewer", mock_reviewer)

    # Monkeypatch g to inject a correlation_id for this test
    monkeypatch.setattr(app_module, "g", SimpleNamespace(correlation_id="cid-123"))

    resp = client.post("/review", json={"content": "code"})
    assert resp.status_code == 200
    assert resp.get_json()["correlation_id"] == "cid-123"


@pytest.mark.parametrize("payload", [None, {}, {"not_function_code": "x"}])
def test_review_function_missing_field_returns_400(client, payload):
    """POST /review/function without required field should return 400."""
    resp = client.post("/review/function", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing 'function_code' field"


def test_review_function_success_returns_result(client, monkeypatch):
    """POST /review/function with valid input returns reviewer dict."""
    mock_reviewer = Mock()
    mock_reviewer.review_function.return_value = {"result": "ok", "count": 1}
    monkeypatch.setattr(app_module, "reviewer", mock_reviewer)

    resp = client.post("/review/function", json={"function_code": "def f(): pass"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"result": "ok", "count": 1}
    mock_reviewer.review_function.assert_called_once_with("def f(): pass")


def test_get_statistics_missing_body_returns_400(client):
    """POST /statistics without body should return 400."""
    resp = client.post("/statistics", json=None)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_get_statistics_validation_failed_returns_422(client, monkeypatch):
    """POST /statistics with validation errors should return 422."""
    class FakeError:
        def __init__(self, field, message):
            self.field = field
            self.message = message

        def to_dict(self):
            return {"field": self.field, "message": self.message}

    monkeypatch.setattr(app_module, "validate_statistics_request", lambda data: [FakeError("files", "must be list")])

    resp = client.post("/statistics", json={"files": "not-a-list"})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"][0] == {"field": "files", "message": "must be list"}


def test_get_statistics_success_returns_aggregated_stats(client, monkeypatch):
    """POST /statistics with valid input returns aggregated stats."""
    monkeypatch.setattr(app_module, "validate_statistics_request", lambda data: [])
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: {"files": [{"content": "a"}, {"content": "b"}]})

    stats_obj = SimpleNamespace(
        total_files=2,
        average_score=90.5,
        total_issues=3,
        issues_by_severity={"warning": 2, "error": 1},
        average_complexity=2.4,
        files_with_high_complexity=["file1.py"],
        total_suggestions=5,
    )
    mock_aggregator = Mock()
    mock_aggregator.aggregate_reviews.return_value = stats_obj
    monkeypatch.setattr(app_module, "statistics_aggregator", mock_aggregator)

    resp = client.post("/statistics", json={"files": [{"content": "a"}]})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_files"] == 2
    assert data["average_score"] == 90.5
    assert data["total_issues"] == 3
    assert data["issues_by_severity"] == {"warning": 2, "error": 1}
    assert data["average_complexity"] == 2.4
    assert data["files_with_high_complexity"] == ["file1.py"]
    assert data["total_suggestions"] == 5
    assert "correlation_id" in data


def test_list_traces_success_returns_all_traces(client, monkeypatch):
    """GET /traces returns list and total count."""
    traces = [{"id": "t1"}, {"id": "t2"}]
    monkeypatch.setattr(app_module, "get_all_traces", lambda: traces)

    resp = client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == 2
    assert data["traces"] == traces


def test_get_trace_not_found_returns_404(client, monkeypatch):
    """GET /traces/<id> with no traces should return 404."""
    monkeypatch.setattr(app_module, "get_traces", lambda cid: [])

    resp = client.get("/traces/unknown-id")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "No traces found for correlation ID"


def test_get_trace_success_returns_trace_data(client, monkeypatch):
    """GET /traces/<id> returns trace data when available."""
    monkeypatch.setattr(app_module, "get_traces", lambda cid: [{"span": "s1"}, {"span": "s2"}])

    resp = client.get("/traces/c-123")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] == "c-123"
    assert data["trace_count"] == 2
    assert data["traces"][0]["span"] == "s1"


def test_list_validation_errors_success(client, monkeypatch):
    """GET /validation/errors returns existing validation errors."""
    errors = [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}]
    monkeypatch.setattr(app_module, "get_validation_errors", lambda: errors)

    resp = client.get("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == 3
    assert data["errors"] == errors


def test_delete_validation_errors_clears_errors(client, monkeypatch):
    """DELETE /validation/errors clears validation errors."""
    mock_clear = Mock()
    monkeypatch.setattr(app_module, "clear_validation_errors", mock_clear)

    resp = client.delete("/validation/errors")
    assert resp.status_code == 200
    assert resp.get_json()["message"] == "Validation errors cleared"
    mock_clear.assert_called_once()