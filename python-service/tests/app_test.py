import sys
import types
from types import SimpleNamespace

# Create stub modules for external dependencies before importing src.app
# Stub for src.request_validator
request_validator_module = types.ModuleType("src.request_validator")

_validation_errors_store = []

def _validate_review_request(data):
    return []

def _validate_statistics_request(data):
    return []

def _sanitize_request_data(data):
    return data

def _get_validation_errors():
    return list(_validation_errors_store)

def _clear_validation_errors():
    _validation_errors_store.clear()

request_validator_module.validate_review_request = _validate_review_request
request_validator_module.validate_statistics_request = _validate_statistics_request
request_validator_module.sanitize_request_data = _sanitize_request_data
request_validator_module.get_validation_errors = _get_validation_errors
request_validator_module.clear_validation_errors = _clear_validation_errors

sys.modules["src.request_validator"] = request_validator_module

# Stub for src.code_reviewer
code_reviewer_module = types.ModuleType("src.code_reviewer")

class _Issue:
    def __init__(self, severity, line, message, suggestion):
        self.severity = severity
        self.line = line
        self.message = message
        self.suggestion = suggestion

class _ReviewResult:
    def __init__(self, score, issues, suggestions, complexity_score):
        self.score = score
        self.issues = issues
        self.suggestions = suggestions
        self.complexity_score = complexity_score

class CodeReviewer:
    def review_code(self, content, language):
        return _ReviewResult(10, [], [], 1.0)

    def review_function(self, function_code):
        return {"ok": True, "length": len(function_code or "")}

code_reviewer_module.CodeReviewer = CodeReviewer
code_reviewer_module.Issue = _Issue
code_reviewer_module.ReviewResult = _ReviewResult
sys.modules["src.code_reviewer"] = code_reviewer_module

# Stub for src.statistics
statistics_module = types.ModuleType("src.statistics")

class _StatisticsResult:
    def __init__(
        self,
        total_files=0,
        average_score=0.0,
        total_issues=0,
        issues_by_severity=None,
        average_complexity=0.0,
        files_with_high_complexity=None,
        total_suggestions=0,
    ):
        self.total_files = total_files
        self.average_score = average_score
        self.total_issues = total_issues
        self.issues_by_severity = issues_by_severity or {}
        self.average_complexity = average_complexity
        self.files_with_high_complexity = files_with_high_complexity or []
        self.total_suggestions = total_suggestions

class StatisticsAggregator:
    def aggregate_reviews(self, files):
        return _StatisticsResult(total_files=len(files or []))

statistics_module.StatisticsAggregator = StatisticsAggregator
statistics_module.StatisticsResult = _StatisticsResult
sys.modules["src.statistics"] = statistics_module

# Stub for src.correlation_middleware
correlation_middleware_module = types.ModuleType("src.correlation_middleware")

class CorrelationIDMiddleware:
    def __init__(self, app):
        self.app = app

def get_traces(correlation_id):
    return []

def get_all_traces():
    return []

correlation_middleware_module.CorrelationIDMiddleware = CorrelationIDMiddleware
correlation_middleware_module.get_traces = get_traces
correlation_middleware_module.get_all_traces = get_all_traces
sys.modules["src.correlation_middleware"] = correlation_middleware_module

import pytest
from unittest.mock import Mock
import importlib

from src.app import app  # must use this exact import per instructions


@pytest.fixture(scope="module")
def app_module():
    """Import and return the src.app module for monkeypatching."""
    return importlib.import_module("src.app")


@pytest.fixture()
def client():
    """Provide a Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def fake_g(monkeypatch):
    """Provide a fake Flask 'g' with a fixed correlation_id for all tests."""
    monkeypatch.setattr("src.app", "g", SimpleNamespace(correlation_id="cid-123"), raising=False)


def test_health_check_ok(client):
    """GET /health should return service health status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "healthy", "service": "python-reviewer"}


def test_review_code_missing_body_returns_400(client):
    """POST /review without JSON body should return 400 error."""
    resp = client.post("/review")
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "Missing request body"}


def test_review_code_validation_error_returns_422_with_details(client, monkeypatch, app_module):
    """POST /review with validation errors should return 422 and details."""
    error1 = Mock()
    error1.to_dict.return_value = {"field": "content", "message": "required"}
    error2 = Mock()
    error2.to_dict.return_value = {"field": "language", "message": "invalid"}

    monkeypatch.setattr(app_module, "validate_review_request", lambda data: [error1, error2])
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: data)
    reviewer_mock = Mock()
    monkeypatch.setattr(app_module, "reviewer", reviewer_mock)

    resp = client.post("/review", json={"content": "", "language": ""})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "Validation failed"
    assert body["details"] == [
        {"field": "content", "message": "required"},
        {"field": "language", "message": "invalid"},
    ]
    assert reviewer_mock.review_code.call_count == 0


def test_review_code_success_returns_result_and_correlation_id(client, monkeypatch, app_module):
    """POST /review should return analyzed result and include correlation_id."""
    monkeypatch.setattr(app_module, "validate_review_request", lambda data: [])
    monkeypatch.setattr(
        app_module,
        "sanitize_request_data",
        lambda data: {"content": "print('hi')", "language": "python"},
    )

    class Issue:
        def __init__(self, severity, line, message, suggestion):
            self.severity = severity
            self.line = line
            self.message = message
            self.suggestion = suggestion

    class Result:
        def __init__(self):
            self.score = 95
            self.issues = [
                Issue("high", 1, "Use logging", "Replace print with logging"),
                Issue("low", 2, "Trailing whitespace", "Remove trailing spaces"),
            ]
            self.suggestions = ["Add docstrings", "Refactor long function"]
            self.complexity_score = 3.2

    reviewer_mock = Mock()
    reviewer_mock.review_code.return_value = Result()
    monkeypatch.setattr(app_module, "reviewer", reviewer_mock)

    resp = client.post("/review", json={"content": "ignored", "language": "ignored"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["score"] == 95
    assert data["complexity_score"] == 3.2
    assert data["suggestions"] == ["Add docstrings", "Refactor long function"]
    assert data["issues"] == [
        {
            "severity": "high",
            "line": 1,
            "message": "Use logging",
            "suggestion": "Replace print with logging",
        },
        {
            "severity": "low",
            "line": 2,
            "message": "Trailing whitespace",
            "suggestion": "Remove trailing spaces",
        },
    ]
    assert data["correlation_id"] == "cid-123"
    reviewer_mock.review_code.assert_called_once_with("print('hi')", "python")


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
    ],
)
def test_review_function_missing_field_returns_400(client, payload):
    """POST /review/function should return 400 if function_code is missing."""
    if payload is None:
        resp = client.post("/review/function")
    else:
        resp = client.post("/review/function", json=payload)
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "Missing 'function_code' field"}


def test_review_function_success_returns_reviewer_result(client, monkeypatch, app_module):
    """POST /review/function should delegate to reviewer.review_function and return its result."""
    reviewer_mock = Mock()
    reviewer_mock.review_function.return_value = {"ok": True, "summary": "fine"}
    monkeypatch.setattr(app_module, "reviewer", reviewer_mock)

    resp = client.post("/review/function", json={"function_code": "def f(): pass"})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "summary": "fine"}
    reviewer_mock.review_function.assert_called_once_with("def f(): pass")


def test_get_statistics_missing_body_returns_400(client):
    """POST /statistics without JSON body should return 400."""
    resp = client.post("/statistics")
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "Missing request body"}


def test_get_statistics_validation_error_returns_422_with_details(client, monkeypatch, app_module):
    """POST /statistics with invalid payload should return 422 and details."""
    err = Mock()
    err.to_dict.return_value = {"field": "files", "message": "must be a list"}

    monkeypatch.setattr(app_module, "validate_statistics_request", lambda data: [err])
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: data)

    resp = client.post("/statistics", json={"files": "not-a-list"})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "Validation failed"
    assert body["details"] == [{"field": "files", "message": "must be a list"}]


def test_get_statistics_success_returns_aggregated_stats_and_correlation_id(client, monkeypatch, app_module):
    """POST /statistics should return aggregated statistics and include correlation_id."""
    monkeypatch.setattr(app_module, "validate_statistics_request", lambda data: [])
    monkeypatch.setattr(app_module, "sanitize_request_data", lambda data: {"files": [{"path": "a.py"}]})

    class Stats:
        def __init__(self):
            self.total_files = 3
            self.average_score = 88.5
            self.total_issues = 7
            self.issues_by_severity = {"high": 2, "medium": 3, "low": 2}
            self.average_complexity = 2.1
            self.files_with_high_complexity = ["a.py"]
            self.total_suggestions = 5

    stats_aggregator_mock = Mock()
    stats_aggregator_mock.aggregate_reviews.return_value = Stats()
    monkeypatch.setattr(app_module, "statistics_aggregator", stats_aggregator_mock)

    resp = client.post("/statistics", json={"files": []})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_files"] == 3
    assert data["average_score"] == 88.5
    assert data["total_issues"] == 7
    assert data["issues_by_severity"] == {"high": 2, "medium": 3, "low": 2}
    assert data["average_complexity"] == 2.1
    assert data["files_with_high_complexity"] == ["a.py"]
    assert data["total_suggestions"] == 5
    assert data["correlation_id"] == "cid-123"
    stats_aggregator_mock.aggregate_reviews.assert_called_once_with([{"path": "a.py"}])


def test_list_traces_returns_total_and_list(client, monkeypatch, app_module):
    """GET /traces should return total_traces and traces list."""
    traces = [{"id": "t1"}, {"id": "t2"}, {"id": "t3"}]
    monkeypatch.setattr(app_module, "get_all_traces", lambda: traces)

    resp = client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == 3
    assert data["traces"] == traces


def test_get_trace_not_found_returns_404(client, monkeypatch, app_module):
    """GET /traces/<correlation_id> should return 404 when no traces are found."""
    monkeypatch.setattr(app_module, "get_traces", lambda cid: [])

    resp = client.get("/traces/unknown-id")
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "No traces found for correlation ID"}


def test_get_trace_success_returns_trace_data(client, monkeypatch, app_module):
    """GET /traces/<correlation_id> should return traces and count when found."""
    traces = [{"step": 1}, {"step": 2}]
    monkeypatch.setattr(app_module, "get_traces", lambda cid: traces)

    resp = client.get("/traces/corr-1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] == "corr-1"
    assert data["trace_count"] == 2
    assert data["traces"] == traces


def test_list_validation_errors_returns_total_and_errors(client, monkeypatch, app_module):
    """GET /validation/errors should return error count and errors list."""
    errs = [{"field": "content", "message": "too short"}, {"field": "language", "message": "unsupported"}]
    monkeypatch.setattr(app_module, "get_validation_errors", lambda: errs)

    resp = client.get("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == 2
    assert data["errors"] == errs


def test_delete_validation_errors_invokes_clear_and_returns_message(client, monkeypatch, app_module):
    """DELETE /validation/errors should clear errors and return a confirmation message."""
    clear_mock = Mock()
    monkeypatch.setattr(app_module, "clear_validation_errors", clear_mock)

    resp = client.delete("/validation/errors")
    assert resp.status_code == 200
    assert resp.get_json() == {"message": "Validation errors cleared"}
    clear_mock.assert_called_once()