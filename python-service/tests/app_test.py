import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

# ---------------------------------------------------------------------------
# Create stub modules for dependencies that may not exist in the environment
# ---------------------------------------------------------------------------

# Stub for src.code_reviewer
if "src.code_reviewer" not in sys.modules:
    m = types.ModuleType("src.code_reviewer")

    class _StubCodeReviewer:
        def review_code(self, content, language="python"):
            return SimpleNamespace(
                score=100,
                issues=[],
                suggestions=[],
                complexity_score=1.0,
            )

        def review_function(self, function_code):
            return {"status": "reviewed", "length": len(function_code)}

    m.CodeReviewer = _StubCodeReviewer
    sys.modules["src.code_reviewer"] = m

# Stub for src.statistics
if "src.statistics" not in sys.modules:
    m = types.ModuleType("src.statistics")

    class _StubStatisticsAggregator:
        def aggregate_reviews(self, files):
            return SimpleNamespace(
                total_files=len(files),
                average_score=95.0,
                total_issues=0,
                issues_by_severity={},
                average_complexity=1.5,
                files_with_high_complexity=[],
                total_suggestions=0,
            )

    m.StatisticsAggregator = _StubStatisticsAggregator
    sys.modules["src.statistics"] = m

# Stub for src.correlation_middleware
if "src.correlation_middleware" not in sys.modules:
    m = types.ModuleType("src.correlation_middleware")

    class _StubCorrelationIDMiddleware:
        def __init__(self, app):
            self.app = app

    def _stub_get_traces(correlation_id):
        return []

    def _stub_get_all_traces():
        return []

    m.CorrelationIDMiddleware = _StubCorrelationIDMiddleware
    m.get_traces = _stub_get_traces
    m.get_all_traces = _stub_get_all_traces
    sys.modules["src.correlation_middleware"] = m

# Stub for src.request_validator
if "src.request_validator" not in sys.modules:
    m = types.ModuleType("src.request_validator")

    def _validate_review_request(data):
        return []

    def _validate_statistics_request(data):
        return []

    def _sanitize_request_data(data):
        return data

    _validation_errors_store = []

    def _get_validation_errors():
        return list(_validation_errors_store)

    def _clear_validation_errors():
        _validation_errors_store.clear()

    m.validate_review_request = _validate_review_request
    m.validate_statistics_request = _validate_statistics_request
    m.sanitize_request_data = _sanitize_request_data
    m.get_validation_errors = _get_validation_errors
    m.clear_validation_errors = _clear_validation_errors
    sys.modules["src.request_validator"] = m

# Now import the app and globals under test
from src.app import app, reviewer  # noqa: E402


@pytest.fixture
def client():
    """Provide a Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class DummyValidationError:
    """Simple validation error stub that matches expected interface."""
    def __init__(self, field, message, code="invalid"):
        self.field = field
        self.message = message
        self.code = code

    def to_dict(self):
        return {"field": self.field, "message": self.message, "code": self.code}


def test_health_check_ok(client):
    """GET /health returns service status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


def test_review_code_missing_body_returns_400(client):
    """POST /review with no body returns 400."""
    resp = client.post("/review")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_review_code_validation_error_returns_422(client):
    """POST /review returns 422 when validation fails and includes details."""
    errors = [DummyValidationError("content", "Required"), DummyValidationError("language", "Unsupported")]

    with patch("src.app.validate_review_request", return_value=errors):
        payload = {"content": "", "language": "python"}
        resp = client.post("/review", json=payload)

    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "Validation failed"
    assert isinstance(body["details"], list)
    assert {"field": "content", "message": "Required", "code": "invalid"} in body["details"]


def test_review_code_success_returns_result_and_correlation(client):
    """POST /review returns reviewed result with issues and correlation id."""
    with patch("src.app.validate_review_request", return_value=[]), \
         patch("src.app.sanitize_request_data", side_effect=lambda d: d), \
         patch("src.app.g", SimpleNamespace(correlation_id="corr-123")), \
         patch.object(reviewer, "review_code") as mock_review_code:

        mock_issue = SimpleNamespace(severity="HIGH", line=10, message="Bug", suggestion="Fix it")
        mock_result = SimpleNamespace(
            score=88,
            issues=[mock_issue],
            suggestions=["Consider refactoring"],
            complexity_score=3.2,
        )
        mock_review_code.return_value = mock_result

        payload = {"content": "print('hello')", "language": "python"}
        resp = client.post("/review", json=payload)

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["score"] == 88
    assert data["issues"][0]["severity"] == "HIGH"
    assert data["issues"][0]["line"] == 10
    assert data["complexity_score"] == 3.2
    assert data["correlation_id"] == "corr-123"


@pytest.mark.parametrize("language", ["python", "javascript", "go"])
def test_review_code_called_with_correct_language(client, language):
    """POST /review passes the language to the reviewer correctly."""
    with patch("src.app.validate_review_request", return_value=[]), \
         patch("src.app.sanitize_request_data", side_effect=lambda d: d), \
         patch.object(reviewer, "review_code") as mock_review_code:

        mock_review_code.return_value = SimpleNamespace(
            score=90, issues=[], suggestions=[], complexity_score=1.0
        )
        payload = {"content": "code", "language": language}
        resp = client.post("/review", json=payload)

    assert resp.status_code == 200
    mock_review_code.assert_called_once_with("code", language)


def test_review_function_missing_field_returns_400(client):
    """POST /review/function without function_code field returns 400."""
    resp = client.post("/review/function", json={"not_function_code": "x"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing 'function_code' field"


def test_review_function_success_returns_result(client):
    """POST /review/function returns reviewer result payload."""
    with patch.object(reviewer, "review_function", return_value={"ok": True, "quality": "A"}) as mock_method:
        payload = {"function_code": "def f(): pass"}
        resp = client.post("/review/function", json=payload)

    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "quality": "A"}
    mock_method.assert_called_once_with("def f(): pass")


def test_get_statistics_missing_body_returns_400(client):
    """POST /statistics with no body returns 400."""
    resp = client.post("/statistics")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_get_statistics_validation_error_returns_422(client):
    """POST /statistics returns 422 when validation fails and includes details."""
    errors = [DummyValidationError("files", "Must be a list")]

    with patch("src.app.validate_statistics_request", return_value=errors):
        payload = {"files": "not a list"}
        resp = client.post("/statistics", json=payload)

    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"][0]["field"] == "files"


def test_get_statistics_success_returns_aggregates_and_correlation(client):
    """POST /statistics returns stats aggregate and correlation id."""
    mock_stats = SimpleNamespace(
        total_files=3,
        average_score=87.5,
        total_issues=5,
        issues_by_severity={"LOW": 2, "HIGH": 3},
        average_complexity=2.1,
        files_with_high_complexity=["a.py", "b.py"],
        total_suggestions=4,
    )

    with patch("src.app.validate_statistics_request", return_value=[]), \
         patch("src.app.sanitize_request_data", side_effect=lambda d: d), \
         patch("src.app.g", SimpleNamespace(correlation_id="stat-corr-1")), \
         patch("src.app.statistics_aggregator.aggregate_reviews", return_value=mock_stats):

        payload = {"files": [{"content": "x"}, {"content": "y"}]}
        resp = client.post("/statistics", json=payload)

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_files"] == 3
    assert data["average_score"] == 87.5
    assert data["issues_by_severity"]["HIGH"] == 3
    assert data["correlation_id"] == "stat-corr-1"


def test_list_traces_returns_total_and_items(client):
    """GET /traces returns total and traces list."""
    traces = [
        {"id": 1, "msg": "first"},
        {"id": 2, "msg": "second"},
    ]
    with patch("src.app.get_all_traces", return_value=traces):
        resp = client.get("/traces")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == 2
    assert data["traces"] == traces


def test_get_trace_not_found_returns_404(client):
    """GET /traces/<id> returns 404 when no traces exist for correlation id."""
    with patch("src.app.get_traces", return_value=[]):
        resp = client.get("/traces/unknown-id")

    assert resp.status_code == 404
    data = resp.get_json()
    assert data["error"] == "No traces found for correlation ID"


def test_get_trace_success_returns_trace_data(client):
    """GET /traces/<id> returns traces for correlation id."""
    traces = [{"event": "start"}, {"event": "end"}]
    with patch("src.app.get_traces", return_value=traces):
        resp = client.get("/traces/corr-999")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] == "corr-999"
    assert data["trace_count"] == 2
    assert data["traces"] == traces


def test_list_validation_errors_returns_errors(client):
    """GET /validation/errors returns list of errors with total count."""
    errs = [
        {"field": "content", "message": "Required", "code": "missing"},
        {"field": "language", "message": "Unsupported", "code": "invalid"},
    ]
    with patch("src.app.get_validation_errors", return_value=errs):
        resp = client.get("/validation/errors")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == 2
    assert data["errors"] == errs


def test_delete_validation_errors_clears_store(client):
    """DELETE /validation/errors triggers clear_validation_errors and returns message."""
    with patch("src.app.clear_validation_errors") as mock_clear:
        resp = client.delete("/validation/errors")

    assert resp.status_code == 200
    assert resp.get_json()["message"] == "Validation errors cleared"
    mock_clear.assert_called_once()