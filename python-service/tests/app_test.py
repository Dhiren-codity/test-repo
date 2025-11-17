import sys
import types
from types import SimpleNamespace
import pytest
from unittest.mock import patch, MagicMock

# Inject dummy external modules required by src.app before importing it

# Dummy src.code_reviewer
code_reviewer_mod = types.ModuleType("src.code_reviewer")
class DummyCodeReviewer:
    def review_code(self, content, language):
        return SimpleNamespace(
            score=0,
            issues=[],
            suggestions=[],
            complexity_score=0.0
        )

    def review_function(self, function_code):
        return {"review": "ok"}
code_reviewer_mod.CodeReviewer = DummyCodeReviewer
sys.modules["src.code_reviewer"] = code_reviewer_mod

# Dummy src.statistics
statistics_mod = types.ModuleType("src.statistics")
class DummyStatisticsAggregator:
    def aggregate_reviews(self, files):
        return SimpleNamespace(
            total_files=len(files),
            average_score=0.0,
            total_issues=0,
            issues_by_severity={},
            average_complexity=0.0,
            files_with_high_complexity=[],
            total_suggestions=0,
        )
statistics_mod.StatisticsAggregator = DummyStatisticsAggregator
sys.modules["src.statistics"] = statistics_mod

# Dummy src.correlation_middleware
corr_mod = types.ModuleType("src.correlation_middleware")
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
sys.modules["src.correlation_middleware"] = corr_mod

# Dummy src.request_validator
validator_mod = types.ModuleType("src.request_validator")
def dummy_validate_review_request(data):
    return []
def dummy_validate_statistics_request(data):
    return []
def dummy_sanitize_request_data(data):
    return data
_validation_errors_store = []
def dummy_get_validation_errors():
    return list(_validation_errors_store)
def dummy_clear_validation_errors():
    _validation_errors_store.clear()
validator_mod.validate_review_request = dummy_validate_review_request
validator_mod.validate_statistics_request = dummy_validate_statistics_request
validator_mod.sanitize_request_data = dummy_sanitize_request_data
validator_mod.get_validation_errors = dummy_get_validation_errors
validator_mod.clear_validation_errors = dummy_clear_validation_errors
sys.modules["src.request_validator"] = validator_mod

# Now import the app under test
from src.app import app as flask_app


@pytest.fixture
def client():
    """Flask test client fixture."""
    flask_app.testing = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def fake_validation_error():
    """Provide a fake validation error object with to_dict."""
    class FakeError:
        def __init__(self, field="content", message="Invalid"):
            self.field = field
            self.message = message

        def to_dict(self):
            return {"field": self.field, "message": self.message}

    return FakeError()


def test_health_check_ok(client):
    """GET /health should return healthy status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


def test_review_code_missing_body(client):
    """POST /review without body should return 400."""
    resp = client.post("/review")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_review_code_validation_error(client, fake_validation_error):
    """POST /review with validation errors should return 422 and details."""
    with patch("src.app.validate_review_request", return_value=[fake_validation_error]):
        resp = client.post("/review", json={"content": ""})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"] == [fake_validation_error.to_dict()]


def test_review_code_success(client):
    """POST /review should return review results on success."""
    issues = [
        SimpleNamespace(severity="high", line=10, message="Issue found", suggestion="Fix it"),
        SimpleNamespace(severity="low", line=2, message="Minor issue", suggestion="Consider change"),
    ]
    review_result = SimpleNamespace(
        score=88,
        issues=issues,
        suggestions=["Refactor function", "Add tests"],
        complexity_score=3.5,
    )

    with patch("src.app.validate_review_request", return_value=[]), \
         patch("src.app.sanitize_request_data", return_value={"content": "print(1)", "language": "python"}), \
         patch("src.app.reviewer") as mock_reviewer:
        mock_reviewer.review_code.return_value = review_result
        resp = client.post("/review", json={"content": "print(1)"})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["score"] == 88
    assert data["complexity_score"] == 3.5
    assert data["suggestions"] == ["Refactor function", "Add tests"]
    assert isinstance(data["issues"], list)
    assert data["issues"][0]["severity"] == "high"
    assert data["issues"][0]["line"] == 10
    # correlation_id may be None if middleware not active in tests
    assert "correlation_id" in data


@pytest.mark.parametrize("payload", [None, {}])
def test_review_function_missing_field(client, payload):
    """POST /review/function without function_code should return 400."""
    if payload is None:
        resp = client.post("/review/function")
    else:
        resp = client.post("/review/function", json=payload)

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing 'function_code' field"


def test_review_function_success(client):
    """POST /review/function should return reviewer output."""
    expected = {"status": "ok", "findings": []}
    with patch("src.app.reviewer") as mock_reviewer:
        mock_reviewer.review_function.return_value = expected
        resp = client.post("/review/function", json={"function_code": "def f(): pass"})
    assert resp.status_code == 200
    assert resp.get_json() == expected


def test_get_statistics_missing_body(client):
    """POST /statistics without body should return 400."""
    resp = client.post("/statistics")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_get_statistics_validation_error(client, fake_validation_error):
    """POST /statistics with validation errors should return 422."""
    with patch("src.app.validate_statistics_request", return_value=[fake_validation_error]):
        resp = client.post("/statistics", json={"files": []})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"] == [fake_validation_error.to_dict()]


def test_get_statistics_success(client):
    """POST /statistics should return aggregated statistics."""
    stats_obj = SimpleNamespace(
        total_files=3,
        average_score=91.5,
        total_issues=5,
        issues_by_severity={"high": 2, "low": 3},
        average_complexity=2.3,
        files_with_high_complexity=["a.py"],
        total_suggestions=4,
    )
    with patch("src.app.validate_statistics_request", return_value=[]), \
         patch("src.app.sanitize_request_data", return_value={"files": [{"content": "x"}]}), \
         patch("src.app.statistics_aggregator") as mock_aggregator:
        mock_aggregator.aggregate_reviews.return_value = stats_obj
        resp = client.post("/statistics", json={"files": [{"content": "x"}]})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_files"] == 3
    assert data["average_score"] == 91.5
    assert data["total_issues"] == 5
    assert data["issues_by_severity"] == {"high": 2, "low": 3}
    assert data["average_complexity"] == 2.3
    assert data["files_with_high_complexity"] == ["a.py"]
    assert data["total_suggestions"] == 4
    assert "correlation_id" in data


def test_list_traces_ok(client):
    """GET /traces should return list of traces."""
    traces = [{"id": "c1"}, {"id": "c2"}]
    with patch("src.app.get_all_traces", return_value=traces):
        resp = client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == len(traces)
    assert data["traces"] == traces


def test_get_trace_not_found(client):
    """GET /traces/<id> should return 404 when no traces found."""
    with patch("src.app.get_traces", return_value=[]):
        resp = client.get("/traces/unknown-id")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "No traces found for correlation ID"


def test_get_trace_found(client):
    """GET /traces/<id> should return trace details when found."""
    sample_traces = [{"step": 1}, {"step": 2}]
    with patch("src.app.get_traces", return_value=sample_traces):
        resp = client.get("/traces/corr-123")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] == "corr-123"
    assert data["trace_count"] == 2
    assert data["traces"] == sample_traces


def test_list_validation_errors_ok(client):
    """GET /validation/errors should return list of validation errors."""
    errors = [{"field": "content", "message": "required"}, {"field": "language", "message": "unsupported"}]
    with patch("src.app.get_validation_errors", return_value=errors):
        resp = client.get("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == len(errors)
    assert data["errors"] == errors


def test_delete_validation_errors_ok(client):
    """DELETE /validation/errors should clear validation errors."""
    with patch("src.app.clear_validation_errors") as mock_clear:
        resp = client.delete("/validation/errors")
    assert resp.status_code == 200
    assert resp.get_json()["message"] == "Validation errors cleared"
    mock_clear.assert_called_once()