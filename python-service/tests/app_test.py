import sys
import types
from types import SimpleNamespace

# Create stub modules needed by src.app before importing it
src_code_reviewer = types.ModuleType("src.code_reviewer")
src_statistics = types.ModuleType("src.statistics")
src_correlation_middleware = types.ModuleType("src.correlation_middleware")
src_request_validator = types.ModuleType("src.request_validator")

# Stub: src.code_reviewer
class _StubIssue:
    def __init__(self, severity="low", line=1, message="msg", suggestion="do this"):
        self.severity = severity
        self.line = line
        self.message = message
        self.suggestion = suggestion

class _StubReviewResult:
    def __init__(self, score=90, issues=None, suggestions=None, complexity_score=1.2):
        self.score = score
        self.issues = issues if issues is not None else []
        self.suggestions = suggestions if suggestions is not None else []
        self.complexity_score = complexity_score

class CodeReviewer:
    def review_code(self, content, language):
        # Simple behavior: if 'bad' in content, add an issue
        issues = []
        if content and "bad" in content:
            issues.append(_StubIssue(severity="high", line=3, message="Bad pattern", suggestion="Refactor"))
        return _StubReviewResult(score=75 if issues else 95, issues=issues, suggestions=["Consider cleanup"], complexity_score=2.5)

    def review_function(self, function_code):
        return {"reviewed": True, "length": len(function_code or "")}

src_code_reviewer.CodeReviewer = CodeReviewer

# Stub: src.statistics
class StatisticsAggregator:
    def aggregate_reviews(self, files):
        total_files = len(files or [])
        return SimpleNamespace(
            total_files=total_files,
            average_score=88.5,
            total_issues=5,
            issues_by_severity={"low": 2, "medium": 2, "high": 1},
            average_complexity=3.1,
            files_with_high_complexity=["a.py"] if total_files else [],
            total_suggestions=7
        )

src_statistics.StatisticsAggregator = StatisticsAggregator

# Stub: src.correlation_middleware
def _before_request_set_correlation():
    try:
        from flask import g, request
        cid = request.headers.get("X-Correlation-ID")
        if cid:
            g.correlation_id = cid
    except Exception:
        pass

class CorrelationIDMiddleware:
    def __init__(self, app):
        try:
            app.before_request(_before_request_set_correlation)
        except Exception:
            pass

def get_traces(correlation_id):
    return []

def get_all_traces():
    return []

src_correlation_middleware.CorrelationIDMiddleware = CorrelationIDMiddleware
src_correlation_middleware.get_traces = get_traces
src_correlation_middleware.get_all_traces = get_all_traces

# Stub: src.request_validator
_VALIDATION_ERRORS_STORE = []

class _StubValidationError:
    def __init__(self, field, message, code="invalid"):
        self.field = field
        self.message = message
        self.code = code

    def to_dict(self):
        return {"field": self.field, "message": self.message, "code": self.code}

def validate_review_request(data):
    return []

def validate_statistics_request(data):
    return []

def sanitize_request_data(data):
    return data

def get_validation_errors():
    return list(_VALIDATION_ERRORS_STORE)

def clear_validation_errors():
    _VALIDATION_ERRORS_STORE.clear()

src_request_validator._StubValidationError = _StubValidationError
src_request_validator.validate_review_request = validate_review_request
src_request_validator.validate_statistics_request = validate_statistics_request
src_request_validator.sanitize_request_data = sanitize_request_data
src_request_validator.get_validation_errors = get_validation_errors
src_request_validator.clear_validation_errors = clear_validation_errors

# Register stubs
sys.modules["src.code_reviewer"] = src_code_reviewer
sys.modules["src.statistics"] = src_statistics
sys.modules["src.correlation_middleware"] = src_correlation_middleware
sys.modules["src.request_validator"] = src_request_validator

import pytest
from unittest.mock import Mock

from src.app import app as flask_app
import src.app as app_module


@pytest.fixture(scope="function")
def client():
    """Provide a Flask test client with testing config enabled."""
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def test_health_check_ok(client):
    """GET /health should return service health metadata."""
    r = client.get("/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "healthy"
    assert body["service"] == "python-reviewer"


def test_review_code_missing_body_returns_400(client):
    """POST /review without JSON should return 400."""
    r = client.post("/review")
    assert r.status_code == 400
    assert r.get_json()["error"] == "Missing request body"


def test_review_code_validation_error_returns_422(client, monkeypatch):
    """POST /review with validation errors should return 422 and error details."""
    class Err:
        def __init__(self, field, message):
            self.field = field
            self.message = message

        def to_dict(self):
            return {"field": self.field, "message": self.message}

    def fake_validate_review_request(data):
        return [Err("content", "Required"), Err("language", "Unsupported")]

    monkeypatch.setattr(app_module, "validate_review_request", fake_validate_review_request)
    r = client.post("/review", json={"content": "", "language": "python"})
    assert r.status_code == 422
    body = r.get_json()
    assert body["error"] == "Validation failed"
    assert len(body["details"]) == 2
    assert {"field": "content", "message": "Required"} in body["details"]


def test_review_code_success_returns_result_and_correlation_id(client, monkeypatch):
    """POST /review with valid data should return review result including correlation_id."""
    monkeypatch.setattr(app_module, "validate_review_request", lambda data: [])
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: {"content": "print('ok')", "language": "python"})

    # Mock reviewer to produce a deterministic result
    mock_issue = SimpleNamespace(severity="low", line=4, message="Minor issue", suggestion="Do X")
    mock_result = SimpleNamespace(
        score=93,
        issues=[mock_issue],
        suggestions=["Use better var names"],
        complexity_score=2.2
    )
    mock_reviewer = Mock()
    mock_reviewer.review_code.return_value = mock_result
    monkeypatch.setattr(app_module, "reviewer", mock_reviewer)

    r = client.post("/review", headers={"X-Correlation-ID": "cid-123"}, json={"content": "dummy"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["score"] == 93
    assert body["issues"][0]["message"] == "Minor issue"
    assert body["suggestions"] == ["Use better var names"]
    assert body["complexity_score"] == 2.2
    assert body["correlation_id"] == "cid-123"
    mock_reviewer.review_code.assert_called_once_with("print('ok')", "python")


@pytest.mark.parametrize("payload", [None, {}, {"other": "field"}])
def test_review_function_missing_function_code_returns_400(client, payload):
    """POST /review/function without 'function_code' should return 400."""
    if payload is None:
        r = client.post("/review/function")
    else:
        r = client.post("/review/function", json=payload)
    assert r.status_code == 400
    assert r.get_json()["error"] == "Missing 'function_code' field"


def test_review_function_success_returns_raw_result(client, monkeypatch):
    """POST /review/function should return whatever reviewer.review_function returns."""
    mock_reviewer = Mock()
    mock_reviewer.review_function.return_value = {"ok": True, "score": 77}
    monkeypatch.setattr(app_module, "reviewer", mock_reviewer)

    r = client.post("/review/function", json={"function_code": "def f(): pass"})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "score": 77}
    mock_reviewer.review_function.assert_called_once_with("def f(): pass")


def test_statistics_missing_body_returns_400(client):
    """POST /statistics without JSON should return 400."""
    r = client.post("/statistics")
    assert r.status_code == 400
    assert r.get_json()["error"] == "Missing request body"


def test_statistics_validation_error_returns_422(client, monkeypatch):
    """POST /statistics with validation errors should return 422 and error details."""
    class Err:
        def __init__(self, field, message):
            self.field = field
            self.message = message

        def to_dict(self):
            return {"field": self.field, "message": self.message}

    def fake_validate_statistics_request(data):
        return [Err("files", "Must be a non-empty list")]

    monkeypatch.setattr(app_module, "validate_statistics_request", fake_validate_statistics_request)
    r = client.post("/statistics", json={"files": []})
    assert r.status_code == 422
    body = r.get_json()
    assert body["error"] == "Validation failed"
    assert len(body["details"]) == 1
    assert body["details"][0]["field"] == "files"


def test_statistics_success_returns_aggregated_values_and_correlation_id(client, monkeypatch):
    """POST /statistics with valid data should return statistics and correlation_id."""
    monkeypatch.setattr(app_module, "validate_statistics_request", lambda data: [])
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: {"files": [{"content": "print('x')"}]})

    mock_stats = SimpleNamespace(
        total_files=1,
        average_score=91.3,
        total_issues=3,
        issues_by_severity={"low": 1, "medium": 1, "high": 1},
        average_complexity=2.9,
        files_with_high_complexity=["foo.py"],
        total_suggestions=4
    )
    mock_aggregator = Mock()
    mock_aggregator.aggregate_reviews.return_value = mock_stats
    monkeypatch.setattr(app_module, "statistics_aggregator", mock_aggregator)

    r = client.post("/statistics", headers={"X-Correlation-ID": "stat-789"}, json={"files": [{"content": "x"}]})
    assert r.status_code == 200
    body = r.get_json()

    assert body["total_files"] == 1
    assert body["average_score"] == 91.3
    assert body["total_issues"] == 3
    assert body["issues_by_severity"]["high"] == 1
    assert body["average_complexity"] == 2.9
    assert body["files_with_high_complexity"] == ["foo.py"]
    assert body["total_suggestions"] == 4
    assert body["correlation_id"] == "stat-789"
    mock_aggregator.aggregate_reviews.assert_called_once_with([{"content": "print('x')"}])


def test_list_traces_returns_all_traces(client, monkeypatch):
    """GET /traces should return total count and provided trace list."""
    traces = [{"id": "t1"}, {"id": "t2"}, {"id": "t3"}]
    monkeypatch.setattr(app_module, "get_all_traces", lambda: traces)
    r = client.get("/traces")
    assert r.status_code == 200
    body = r.get_json()
    assert body["total_traces"] == 3
    assert body["traces"] == traces


def test_get_trace_not_found_returns_404(client, monkeypatch):
    """GET /traces/<id> should return 404 when no traces found."""
    monkeypatch.setattr(app_module, "get_traces", lambda cid: [])
    r = client.get("/traces/unknown-id")
    assert r.status_code == 404
    assert r.get_json()["error"] == "No traces found for correlation ID"


def test_get_trace_success_returns_trace_details(client, monkeypatch):
    """GET /traces/<id> should return trace details."""
    sample = [{"step": "start"}, {"step": "end"}]
    monkeypatch.setattr(app_module, "get_traces", lambda cid: sample)
    r = client.get("/traces/corr-42")
    assert r.status_code == 200
    body = r.get_json()
    assert body["correlation_id"] == "corr-42"
    assert body["trace_count"] == 2
    assert body["traces"] == sample


def test_list_validation_errors_returns_error_store(client, monkeypatch):
    """GET /validation/errors should return aggregated validation errors."""
    errors = [{"field": "content", "message": "Required"}]
    monkeypatch.setattr(app_module, "get_validation_errors", lambda: errors)
    r = client.get("/validation/errors")
    assert r.status_code == 200
    body = r.get_json()
    assert body["total_errors"] == 1
    assert body["errors"] == errors


def test_delete_validation_errors_clears_store(client, monkeypatch):
    """DELETE /validation/errors should trigger clear and return confirmation."""
    called = {"flag": False}

    def fake_clear():
        called["flag"] = True

    monkeypatch.setattr(app_module, "clear_validation_errors", fake_clear)
    r = client.delete("/validation/errors")
    assert r.status_code == 200
    body = r.get_json()
    assert body["message"] == "Validation errors cleared"
    assert called["flag"] is True