import sys
import types
from types import SimpleNamespace

# Create stub modules for external dependencies so that "from src.app import app" works
src_pkg = types.ModuleType("src")
src_pkg.__path__ = []  # mark as package
sys.modules.setdefault("src", src_pkg)

# Stub for src.code_reviewer
code_reviewer_mod = types.ModuleType("src.code_reviewer")
class _StubCodeReviewer:
    def review_code(self, content, language):
        return SimpleNamespace(score=0, issues=[], suggestions=[], complexity_score=0)
    def review_function(self, function_code):
        return {}
code_reviewer_mod.CodeReviewer = _StubCodeReviewer
sys.modules["src.code_reviewer"] = code_reviewer_mod

# Stub for src.statistics
statistics_mod = types.ModuleType("src.statistics")
class _StubStatisticsAggregator:
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
statistics_mod.StatisticsAggregator = _StubStatisticsAggregator
sys.modules["src.statistics"] = statistics_mod

# Stub for src.correlation_middleware
correlation_mod = types.ModuleType("src.correlation_middleware")
class _StubCorrelationIDMiddleware:
    def __init__(self, app):
        pass
def _stub_get_traces(correlation_id):
    return []
def _stub_get_all_traces():
    return []
correlation_mod.CorrelationIDMiddleware = _StubCorrelationIDMiddleware
correlation_mod.get_traces = _stub_get_traces
correlation_mod.get_all_traces = _stub_get_all_traces
sys.modules["src.correlation_middleware"] = correlation_mod

# Stub for src.request_validator
validator_mod = types.ModuleType("src.request_validator")
def _stub_validate_review_request(data):
    return []
def _stub_validate_statistics_request(data):
    return []
def _stub_sanitize_request_data(data):
    return data
def _stub_get_validation_errors():
    return []
def _stub_clear_validation_errors():
    pass
validator_mod.validate_review_request = _stub_validate_review_request
validator_mod.validate_statistics_request = _stub_validate_statistics_request
validator_mod.sanitize_request_data = _stub_sanitize_request_data
validator_mod.get_validation_errors = _stub_get_validation_errors
validator_mod.clear_validation_errors = _stub_clear_validation_errors
sys.modules["src.request_validator"] = validator_mod

import pytest
from unittest.mock import Mock
from src.app import app  # Use EXACT import path requirement


@pytest.fixture
def client():
    """Flask test client fixture."""
    with app.test_client() as c:
        yield c


def test_health_check_ok(client):
    """Test /health returns healthy status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


def test_review_code_missing_body_returns_400(client):
    """Test /review returns 400 when body is missing."""
    resp = client.post("/review")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing request body"


def test_review_code_validation_error_returns_422(client, monkeypatch):
    """Test /review returns 422 with validation errors."""
    class FakeValidationError:
        def to_dict(self):
            return {"field": "content", "message": "Content is required", "code": "missing"}

    monkeypatch.setattr("src.app.validate_review_request", lambda data: [FakeValidationError()])

    resp = client.post("/review", json={})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"] == [{"field": "content", "message": "Content is required", "code": "missing"}]


def test_review_code_happy_path_returns_result(client, monkeypatch):
    """Test /review returns 200 and review result on valid input."""
    # No validation errors
    monkeypatch.setattr("src.app.validate_review_request", lambda data: [])

    # Sanitization returns provided data
    monkeypatch.setattr("src.app.sanitize_request_data", lambda data: data)

    # Mock reviewer
    issue1 = SimpleNamespace(severity="high", line=10, message="Bug found", suggestion="Refactor")
    issue2 = SimpleNamespace(severity="low", line=5, message="Style issue", suggestion="Use PEP8")
    fake_result = SimpleNamespace(
        score=85,
        issues=[issue1, issue2],
        suggestions=["Add tests", "Improve docs"],
        complexity_score=12.3
    )
    reviewer_mock = Mock()
    reviewer_mock.review_code.return_value = fake_result
    monkeypatch.setattr("src.app.reviewer", reviewer_mock)

    payload = {"content": "print(1)", "language": "python"}
    resp = client.post("/review", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["score"] == 85
    assert data["issues"] == [
        {"severity": "high", "line": 10, "message": "Bug found", "suggestion": "Refactor"},
        {"severity": "low", "line": 5, "message": "Style issue", "suggestion": "Use PEP8"},
    ]
    assert data["suggestions"] == ["Add tests", "Improve docs"]
    assert data["complexity_score"] == 12.3
    # correlation_id may be None if middleware doesn't set it
    assert "correlation_id" in data
    reviewer_mock.review_code.assert_called_once_with("print(1)", "python")


@pytest.mark.parametrize("payload,use_json", [
    (None, False),
    ({}, True),
])
def test_review_function_missing_field_returns_400(client, payload, use_json):
    """Test /review/function returns 400 when function_code is missing."""
    if use_json:
        resp = client.post("/review/function", json=payload)
    else:
        resp = client.post("/review/function")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing 'function_code' field"


def test_review_function_happy_path(client, monkeypatch):
    """Test /review/function returns reviewer output."""
    reviewer_mock = Mock()
    reviewer_mock.review_function.return_value = {"status": "ok", "score": 90, "issues": []}
    monkeypatch.setattr("src.app.reviewer", reviewer_mock)

    resp = client.post("/review/function", json={"function_code": "def f(): pass"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"status": "ok", "score": 90, "issues": []}
    reviewer_mock.review_function.assert_called_once_with("def f(): pass")


def test_statistics_missing_body_returns_400(client):
    """Test /statistics returns 400 when body is missing."""
    resp = client.post("/statistics")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing request body"


def test_statistics_validation_error_returns_422(client, monkeypatch):
    """Test /statistics returns 422 when validation fails."""
    class FakeValidationError:
        def to_dict(self):
            return {"field": "files", "message": "Files required", "code": "missing"}

    monkeypatch.setattr("src.app.validate_statistics_request", lambda data: [FakeValidationError()])

    resp = client.post("/statistics", json={})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"] == [{"field": "files", "message": "Files required", "code": "missing"}]


def test_statistics_happy_path_returns_aggregates(client, monkeypatch):
    """Test /statistics returns aggregated statistics on valid input."""
    monkeypatch.setattr("src.app.validate_statistics_request", lambda data: [])
    monkeypatch.setattr("src.app.sanitize_request_data", lambda data: data)

    stats_obj = SimpleNamespace(
        total_files=3,
        average_score=88.5,
        total_issues=7,
        issues_by_severity={"high": 2, "medium": 3, "low": 2},
        average_complexity=10.7,
        files_with_high_complexity=["a.py", "b.py"],
        total_suggestions=5,
    )
    stats_mock = Mock()
    stats_mock.aggregate_reviews.return_value = stats_obj
    monkeypatch.setattr("src.app.statistics_aggregator", stats_mock)

    payload = {"files": [{"path": "a.py"}, {"path": "b.py"}]}
    resp = client.post("/statistics", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_files"] == 3
    assert data["average_score"] == 88.5
    assert data["total_issues"] == 7
    assert data["issues_by_severity"] == {"high": 2, "medium": 3, "low": 2}
    assert data["average_complexity"] == 10.7
    assert data["files_with_high_complexity"] == ["a.py", "b.py"]
    assert data["total_suggestions"] == 5
    assert "correlation_id" in data
    stats_mock.aggregate_reviews.assert_called_once_with(payload["files"])


def test_traces_list_returns_values(client, monkeypatch):
    """Test GET /traces lists all traces with count."""
    traces = [{"cid": "1", "ev": "start"}, {"cid": "2", "ev": "end"}]
    monkeypatch.setattr("src.app.get_all_traces", lambda: traces)

    resp = client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == 2
    assert data["traces"] == traces


def test_get_trace_not_found_returns_404(client, monkeypatch):
    """Test GET /traces/<id> returns 404 when no traces."""
    monkeypatch.setattr("src.app.get_traces", lambda cid: [])

    resp = client.get("/traces/unknown")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["error"] == "No traces found for correlation ID"


def test_get_trace_found_returns_data(client, monkeypatch):
    """Test GET /traces/<id> returns trace details when found."""
    traces = [{"step": "start"}, {"step": "analyze"}]
    monkeypatch.setattr("src.app.get_traces", lambda cid: traces)

    resp = client.get("/traces/abc123")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] == "abc123"
    assert data["trace_count"] == 2
    assert data["traces"] == traces


def test_validation_errors_list_returns_values(client, monkeypatch):
    """Test GET /validation/errors returns stored validation errors and count."""
    errors = [{"field": "content", "message": "Missing"}, {"field": "files", "message": "Invalid"}]
    monkeypatch.setattr("src.app.get_validation_errors", lambda: errors)

    resp = client.get("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == 2
    assert data["errors"] == errors


def test_delete_validation_errors_calls_clear(client, monkeypatch):
    """Test DELETE /validation/errors clears validation errors."""
    clear_mock = Mock()
    monkeypatch.setattr("src.app.clear_validation_errors", clear_mock)

    resp = client.delete("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["message"] == "Validation errors cleared"
    clear_mock.assert_called_once()