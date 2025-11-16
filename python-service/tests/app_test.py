import sys
import types
import importlib
from types import SimpleNamespace

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(scope="module")
def app_module(monkeypatch):
    """Create fake dependent modules and import the Flask app module."""
    # Create fake src.code_reviewer
    code_reviewer_mod = types.ModuleType("src.code_reviewer")

    class FakeIssue:
        def __init__(self, severity="low", line=1, message="msg", suggestion="suggest"):
            self.severity = severity
            self.line = line
            self.message = message
            self.suggestion = suggestion

    class FakeReviewResult:
        def __init__(self, score=95, issues=None, suggestions=None, complexity_score=1.0):
            self.score = score
            self.issues = issues or [FakeIssue()]
            self.suggestions = suggestions or ["Use list comprehension"]
            self.complexity_score = complexity_score

    class FakeCodeReviewer:
        def review_code(self, content, language):
            return FakeReviewResult()

        def review_function(self, function_code):
            return {"status": "ok", "function_reviewed": True}

    code_reviewer_mod.CodeReviewer = FakeCodeReviewer

    # Create fake src.statistics
    statistics_mod = types.ModuleType("src.statistics")

    class FakeStats:
        def __init__(
            self,
            total_files=1,
            average_score=90.0,
            total_issues=2,
            issues_by_severity=None,
            average_complexity=3.0,
            files_with_high_complexity=None,
            total_suggestions=1,
        ):
            self.total_files = total_files
            self.average_score = average_score
            self.total_issues = total_issues
            self.issues_by_severity = issues_by_severity or {"low": 1, "high": 1}
            self.average_complexity = average_complexity
            self.files_with_high_complexity = files_with_high_complexity or ["a.py"]
            self.total_suggestions = total_suggestions

    class FakeStatisticsAggregator:
        def aggregate_reviews(self, files):
            return FakeStats()

    statistics_mod.StatisticsAggregator = FakeStatisticsAggregator

    # Create fake src.correlation_middleware
    correlation_mod = types.ModuleType("src.correlation_middleware")

    class FakeCorrelationIDMiddleware:
        def __init__(self, app):
            self.app = app

    def fake_get_traces(correlation_id):
        return []

    def fake_get_all_traces():
        return []

    correlation_mod.CorrelationIDMiddleware = FakeCorrelationIDMiddleware
    correlation_mod.get_traces = fake_get_traces
    correlation_mod.get_all_traces = fake_get_all_traces

    # Create fake src.request_validator
    request_validator_mod = types.ModuleType("src.request_validator")

    class FakeValidationError:
        def __init__(self, field="field", message="invalid"):
            self.field = field
            self.message = message

        def to_dict(self):
            return {"field": self.field, "message": self.message}

    def validate_review_request(data):
        return []

    def validate_statistics_request(data):
        return []

    def sanitize_request_data(data):
        return data

    _validation_errors_store = []

    def get_validation_errors():
        return _validation_errors_store.copy()

    def clear_validation_errors():
        _validation_errors_store.clear()

    request_validator_mod.validate_review_request = validate_review_request
    request_validator_mod.validate_statistics_request = validate_statistics_request
    request_validator_mod.sanitize_request_data = sanitize_request_data
    request_validator_mod.get_validation_errors = get_validation_errors
    request_validator_mod.clear_validation_errors = clear_validation_errors
    request_validator_mod.FakeValidationError = FakeValidationError

    # Inject fake modules
    monkeypatch.setitem(sys.modules, "src.code_reviewer", code_reviewer_mod)
    monkeypatch.setitem(sys.modules, "src.statistics", statistics_mod)
    monkeypatch.setitem(sys.modules, "src.correlation_middleware", correlation_mod)
    monkeypatch.setitem(sys.modules, "src.request_validator", request_validator_mod)

    # Import the app after fakes are in place
    from src.app import app as flask_app  # noqa: F401
    app_mod = importlib.import_module("src.app")
    return app_mod


@pytest.fixture
def client(app_module):
    """Provide a Flask test client."""
    return app_module.app.test_client()


def test_health_check_ok(client):
    """Test GET /health returns healthy status."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


def test_review_code_missing_body(client):
    """Test POST /review without JSON body returns 400."""
    res = client.post("/review")
    assert res.status_code == 400
    assert res.get_json()["error"] == "Missing request body"


def test_review_code_validation_errors(client):
    """Test POST /review returns 422 when validation fails."""
    class Err:
        def to_dict(self):
            return {"field": "content", "message": "is required"}

    with patch("src.app.validate_review_request", return_value=[Err()]):
        res = client.post("/review", json={"foo": "bar"})
    assert res.status_code == 422
    body = res.get_json()
    assert body["error"] == "Validation failed"
    assert isinstance(body["details"], list)
    assert body["details"][0]["field"] == "content"


def test_review_code_success_returns_expected_fields_and_correlation_id(client):
    """Test POST /review happy path returns review result and correlation id."""
    fake_result = SimpleNamespace(
        score=88,
        issues=[
            SimpleNamespace(severity="high", line=10, message="Bug found", suggestion="Fix it")
        ],
        suggestions=["Consider refactoring"],
        complexity_score=2.5,
    )
    with patch("src.app.validate_review_request", return_value=[]), \
         patch("src.app.sanitize_request_data", side_effect=lambda d: d), \
         patch("src.app.reviewer.review_code", return_value=fake_result), \
         patch("src.app.g", SimpleNamespace(correlation_id="cid-123")):
        res = client.post("/review", json={"content": "print('hi')", "language": "python"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["score"] == 88
    assert data["issues"][0]["severity"] == "high"
    assert data["issues"][0]["line"] == 10
    assert data["issues"][0]["message"] == "Bug found"
    assert data["issues"][0]["suggestion"] == "Fix it"
    assert data["suggestions"] == ["Consider refactoring"]
    assert data["complexity_score"] == 2.5
    assert data["correlation_id"] == "cid-123"


def test_review_function_missing_field(client):
    """Test POST /review/function with missing 'function_code' returns 400."""
    res = client.post("/review/function", json={"nope": "x"})
    assert res.status_code == 400
    assert res.get_json()["error"] == "Missing 'function_code' field"


def test_review_function_success(client):
    """Test POST /review/function happy path returns expected JSON."""
    with patch("src.app.reviewer.review_function", return_value={"ok": True, "issues": []}):
        res = client.post("/review/function", json={"function_code": "def f(): pass"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["issues"] == []


def test_get_statistics_missing_body(client):
    """Test POST /statistics without body returns 400."""
    res = client.post("/statistics")
    assert res.status_code == 400
    assert res.get_json()["error"] == "Missing request body"


def test_get_statistics_validation_errors(client):
    """Test POST /statistics returns 422 on validation failure."""
    class Err:
        def to_dict(self):
            return {"field": "files", "message": "cannot be empty"}

    with patch("src.app.validate_statistics_request", return_value=[Err()]):
        res = client.post("/statistics", json={"files": []})
    assert res.status_code == 422
    body = res.get_json()
    assert body["error"] == "Validation failed"
    assert body["details"][0]["field"] == "files"


def test_get_statistics_success_returns_expected_fields_and_correlation_id(client):
    """Test POST /statistics returns aggregated stats and correlation id."""
    fake_stats = SimpleNamespace(
        total_files=3,
        average_score=85.5,
        total_issues=7,
        issues_by_severity={"low": 3, "high": 4},
        average_complexity=4.2,
        files_with_high_complexity=["a.py", "b.py"],
        total_suggestions=5,
    )
    with patch("src.app.validate_statistics_request", return_value=[]), \
         patch("src.app.sanitize_request_data", side_effect=lambda d: d), \
         patch("src.app.statistics_aggregator.aggregate_reviews", return_value=fake_stats), \
         patch("src.app.g", SimpleNamespace(correlation_id="stat-999")):
        res = client.post("/statistics", json={"files": [{"content": "x", "language": "python"}]})
    assert res.status_code == 200
    data = res.get_json()
    assert data["total_files"] == 3
    assert data["average_score"] == 85.5
    assert data["total_issues"] == 7
    assert data["issues_by_severity"] == {"low": 3, "high": 4}
    assert data["average_complexity"] == 4.2
    assert data["files_with_high_complexity"] == ["a.py", "b.py"]
    assert data["total_suggestions"] == 5
    assert data["correlation_id"] == "stat-999"


def test_list_traces_returns_all(client):
    """Test GET /traces returns all traces and total count."""
    traces = [{"id": 1}, {"id": 2}, {"id": 3}]
    with patch("src.app.get_all_traces", return_value=traces):
        res = client.get("/traces")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total_traces"] == 3
    assert data["traces"] == traces


def test_get_trace_not_found(client):
    """Test GET /traces/<id> returns 404 when no traces exist for id."""
    with patch("src.app.get_traces", return_value=[]):
        res = client.get("/traces/unknown-id")
    assert res.status_code == 404
    assert res.get_json()["error"] == "No traces found for correlation ID"


@pytest.mark.parametrize("correlation_id,items_count", [
    ("abc-123", 1),
    ("xyz-789", 2),
])
def test_get_trace_found_multiple_cases(client, correlation_id, items_count):
    """Test GET /traces/<id> returns traces and correct count."""
    items = [{"event": "e"} for _ in range(items_count)]
    with patch("src.app.get_traces", return_value=items):
        res = client.get(f"/traces/{correlation_id}")
    assert res.status_code == 200
    data = res.get_json()
    assert data["correlation_id"] == correlation_id
    assert data["trace_count"] == items_count
    assert data["traces"] == items


def test_list_validation_errors_returns_items(client):
    """Test GET /validation/errors returns errors and total count."""
    errors = [{"field": "content", "message": "missing"}, {"field": "language", "message": "invalid"}]
    with patch("src.app.get_validation_errors", return_value=errors):
        res = client.get("/validation/errors")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total_errors"] == 2
    assert data["errors"] == errors


def test_delete_validation_errors_clears(client):
    """Test DELETE /validation/errors clears the stored errors."""
    with patch("src.app.clear_validation_errors") as clear_mock:
        res = client.delete("/validation/errors")
    assert res.status_code == 200
    assert res.get_json()["message"] == "Validation errors cleared"
    clear_mock.assert_called_once()