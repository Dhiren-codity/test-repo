import sys
import types
from types import SimpleNamespace

# ---- Create stub modules before importing the Flask app ----

# Stub for src.code_reviewer
code_reviewer_mod = types.ModuleType("src.code_reviewer")


class CodeReviewer:
    def review_code(self, content, language):
        return SimpleNamespace(score=0, issues=[], suggestions=[], complexity_score=0)

    def review_function(self, function_code):
        return {"ok": True}


code_reviewer_mod.CodeReviewer = CodeReviewer
sys.modules["src.code_reviewer"] = code_reviewer_mod

# Stub for src.statistics
statistics_mod = types.ModuleType("src.statistics")


class StatisticsAggregator:
    def aggregate_reviews(self, files):
        return SimpleNamespace(
            total_files=0,
            average_score=0.0,
            total_issues=0,
            issues_by_severity={},
            average_complexity=0.0,
            files_with_high_complexity=[],
            total_suggestions=0,
        )


statistics_mod.StatisticsAggregator = StatisticsAggregator
sys.modules["src.statistics"] = statistics_mod

# Stub for src.correlation_middleware
corr_mod = types.ModuleType("src.correlation_middleware")


class CorrelationIDMiddleware:
    def __init__(self, app):
        self.app = app


def get_traces(correlation_id):
    return []


def get_all_traces():
    return []


corr_mod.CorrelationIDMiddleware = CorrelationIDMiddleware
corr_mod.get_traces = get_traces
corr_mod.get_all_traces = get_all_traces
sys.modules["src.correlation_middleware"] = corr_mod

# Stub for src.request_validator
validator_mod = types.ModuleType("src.request_validator")


def validate_review_request(data):
    return []


def validate_statistics_request(data):
    return []


def sanitize_request_data(data):
    return data


_validation_errors_store = []


def get_validation_errors():
    return list(_validation_errors_store)


def clear_validation_errors():
    _validation_errors_store.clear()


validator_mod.validate_review_request = validate_review_request
validator_mod.validate_statistics_request = validate_statistics_request
validator_mod.sanitize_request_data = sanitize_request_data
validator_mod.get_validation_errors = get_validation_errors
validator_mod.clear_validation_errors = clear_validation_errors
sys.modules["src.request_validator"] = validator_mod

# ---- Now import the app as required ----
import pytest
from unittest.mock import Mock
from src.app import app


@pytest.fixture
def app_module():
    """Provide access to the imported src.app module for monkeypatching."""
    return sys.modules["src.app"]


@pytest.fixture
def client():
    """Yield a Flask test client."""
    with app.test_client() as c:
        yield c


def test_health_check_ok(client):
    """GET /health returns healthy status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


def test_review_code_missing_body_returns_400(client):
    """POST /review without JSON body returns 400."""
    resp = client.post("/review")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing request body"


def test_review_code_validation_error_returns_422(client, monkeypatch, app_module):
    """POST /review with validation errors returns 422 and details."""

    class FakeError:
        def __init__(self, field, message):
            self.field = field
            self.message = message

        def to_dict(self):
            return {"field": self.field, "message": self.message}

    monkeypatch.setattr(
        app_module, "validate_review_request", lambda data: [FakeError("content", "required"), FakeError("language", "invalid")]
    )

    resp = client.post("/review", json={"content": "", "language": ""})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert isinstance(data["details"], list)
    assert {"field": "content", "message": "required"} in data["details"]
    assert {"field": "language", "message": "invalid"} in data["details"]


def test_review_code_success_returns_result_and_correlation_id(client, monkeypatch, app_module):
    """POST /review returns review result with issues and correlation_id."""
    # No validation errors
    monkeypatch.setattr(app_module, "validate_review_request", lambda data: [])
    # Sanitize returns expected fields
    monkeypatch.setattr(
        app_module, "sanitize_request_data", lambda data: {"content": "print('hi')", "language": "python"}
    )

    class Issue:
        def __init__(self, severity, line, message, suggestion):
            self.severity = severity
            self.line = line
            self.message = message
            self.suggestion = suggestion

    result = SimpleNamespace(
        score=92.5,
        issues=[Issue("high", 10, "Do not use hardcoded secrets", "Use environment variables")],
        suggestions=["Refactor into smaller functions"],
        complexity_score=3.7,
    )

    mock_reviewer = Mock()
    mock_reviewer.review_code.return_value = result
    monkeypatch.setattr(app_module, "reviewer", mock_reviewer)

    # Set correlation id
    monkeypatch.setattr(app_module, "g", SimpleNamespace(correlation_id="cid-123"))

    resp = client.post("/review", json={"anything": "goes"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["score"] == 92.5
    assert data["complexity_score"] == 3.7
    assert data["correlation_id"] == "cid-123"
    assert isinstance(data["issues"], list)
    assert data["issues"][0]["severity"] == "high"
    assert data["issues"][0]["line"] == 10
    assert data["issues"][0]["message"] == "Do not use hardcoded secrets"
    assert data["issues"][0]["suggestion"] == "Use environment variables"
    assert data["suggestions"] == ["Refactor into smaller functions"]
    mock_reviewer.review_code.assert_called_once_with("print('hi')", "python")


@pytest.mark.parametrize("payload", [None, {}])
def test_review_function_missing_field_returns_400(client, payload):
    """POST /review/function without function_code returns 400."""
    if payload is None:
        resp = client.post("/review/function", json=None)
    else:
        resp = client.post("/review/function", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing 'function_code' field"


def test_review_function_success_returns_json(client, monkeypatch, app_module):
    """POST /review/function returns reviewer output as JSON."""
    out = {"status": "ok", "issues": []}
    mock_reviewer = Mock()
    mock_reviewer.review_function.return_value = out
    monkeypatch.setattr(app_module, "reviewer", mock_reviewer)

    resp = client.post("/review/function", json={"function_code": "def f(): pass"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == out
    mock_reviewer.review_function.assert_called_once_with("def f(): pass")


def test_get_statistics_missing_body_returns_400(client):
    """POST /statistics without body returns 400."""
    resp = client.post("/statistics")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing request body"


def test_get_statistics_validation_error_returns_422(client, monkeypatch, app_module):
    """POST /statistics with validation errors returns 422."""

    class FakeError:
        def __init__(self, field, message):
            self.field = field
            self.message = message

        def to_dict(self):
            return {"field": self.field, "message": self.message}

    monkeypatch.setattr(
        app_module, "validate_statistics_request", lambda data: [FakeError("files", "must be non-empty")]
    )

    resp = client.post("/statistics", json={"files": []})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert {"field": "files", "message": "must be non-empty"} in data["details"]


def test_get_statistics_success_includes_correlation(client, monkeypatch, app_module):
    """POST /statistics returns aggregated stats and includes correlation_id."""
    monkeypatch.setattr(app_module, "validate_statistics_request", lambda data: [])
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: {"files": ["a.py", "b.py"]})

    stats = SimpleNamespace(
        total_files=2,
        average_score=88.0,
        total_issues=4,
        issues_by_severity={"low": 1, "medium": 2, "high": 1},
        average_complexity=2.1,
        files_with_high_complexity=["b.py"],
        total_suggestions=3,
    )

    mock_stats = Mock()
    mock_stats.aggregate_reviews.return_value = stats
    monkeypatch.setattr(app_module, "statistics_aggregator", mock_stats)

    monkeypatch.setattr(app_module, "g", SimpleNamespace(correlation_id="corr-789"))

    resp = client.post("/statistics", json={"files": ["ignored"]})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_files"] == 2
    assert data["average_score"] == 88.0
    assert data["total_issues"] == 4
    assert data["issues_by_severity"] == {"low": 1, "medium": 2, "high": 1}
    assert data["average_complexity"] == 2.1
    assert data["files_with_high_complexity"] == ["b.py"]
    assert data["total_suggestions"] == 3
    assert data["correlation_id"] == "corr-789"
    mock_stats.aggregate_reviews.assert_called_once_with(["a.py", "b.py"])


def test_list_traces_returns_all(client, monkeypatch, app_module):
    """GET /traces returns total_traces and traces list."""
    monkeypatch.setattr(app_module, "get_all_traces", lambda: [{"id": "t1"}, {"id": "t2"}])

    resp = client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == 2
    assert data["traces"] == [{"id": "t1"}, {"id": "t2"}]


def test_get_trace_not_found_returns_404(client, monkeypatch, app_module):
    """GET /traces/<id> returns 404 when no traces found."""
    monkeypatch.setattr(app_module, "get_traces", lambda cid: [])

    resp = client.get("/traces/unknown-id")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["error"] == "No traces found for correlation ID"


def test_get_trace_found_returns_data(client, monkeypatch, app_module):
    """GET /traces/<id> returns traces and trace_count when found."""
    monkeypatch.setattr(
        app_module, "get_traces", lambda cid: [{"step": 1}, {"step": 2}]
    )

    corr_id = "abc-123"
    resp = client.get(f"/traces/{corr_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] == corr_id
    assert data["trace_count"] == 2
    assert data["traces"] == [{"step": 1}, {"step": 2}]


def test_list_validation_errors_returns_errors(client, monkeypatch, app_module):
    """GET /validation/errors returns total_errors and errors list."""
    errors = [{"field": "files", "message": "invalid"}, {"field": "content", "message": "missing"}]
    monkeypatch.setattr(app_module, "get_validation_errors", lambda: errors)

    resp = client.get("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == 2
    assert data["errors"] == errors


def test_delete_validation_errors_clears(client, monkeypatch, app_module):
    """DELETE /validation/errors triggers clear and returns confirmation message."""
    mock_clear = Mock()
    monkeypatch.setattr(app_module, "clear_validation_errors", mock_clear)

    resp = client.delete("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["message"] == "Validation errors cleared"
    mock_clear.assert_called_once()