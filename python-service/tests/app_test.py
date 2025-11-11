import sys
import types
from types import SimpleNamespace

# Create lightweight dummy modules for external dependencies before importing src.app
# so that "from src.app import app" succeeds even if those modules are absent.

# Ensure submodules exist without shadowing the real src package
code_reviewer_mod = types.ModuleType("src.code_reviewer")
statistics_mod = types.ModuleType("src.statistics")
correlation_middleware_mod = types.ModuleType("src.correlation_middleware")
request_validator_mod = types.ModuleType("src.request_validator")

# Dummy CodeReviewer with minimal behavior (will be patched in tests as needed)
class DummyCodeReviewer:
    def review_code(self, content, language):
        issue = SimpleNamespace(severity="low", line=1, message="msg", suggestion="sug")
        return SimpleNamespace(score=100, issues=[issue], suggestions=["ok"], complexity_score=1.0)

    def review_function(self, function_code):
        return {"reviewed": True, "issues": []}

code_reviewer_mod.CodeReviewer = DummyCodeReviewer

# Dummy StatisticsAggregator with minimal behavior (will be patched in tests)
class DummyStatisticsAggregator:
    def aggregate_reviews(self, files):
        return SimpleNamespace(
            total_files=len(files),
            average_score=95.0,
            total_issues=0,
            issues_by_severity={"low": 0, "medium": 0, "high": 0},
            average_complexity=1.0,
            files_with_high_complexity=[],
            total_suggestions=0,
        )

statistics_mod.StatisticsAggregator = DummyStatisticsAggregator

# Dummy correlation middleware and trace functions
class DummyCorrelationIDMiddleware:
    def __init__(self, app):
        self.app = app

_correlation_traces = {}

def dummy_get_traces(correlation_id):
    return _correlation_traces.get(correlation_id, [])

def dummy_get_all_traces():
    traces = []
    for items in _correlation_traces.values():
        traces.extend(items)
    return traces

correlation_middleware_mod.CorrelationIDMiddleware = DummyCorrelationIDMiddleware
correlation_middleware_mod.get_traces = dummy_get_traces
correlation_middleware_mod.get_all_traces = dummy_get_all_traces

# Dummy request validator with simple in-memory store
_validation_errors_store = []

def dummy_validate_review_request(data):
    return []  # empty means valid

def dummy_validate_statistics_request(data):
    return []  # empty means valid

def dummy_sanitize_request_data(data):
    return data

def dummy_get_validation_errors():
    return _validation_errors_store

def dummy_clear_validation_errors():
    _validation_errors_store.clear()

request_validator_mod.validate_review_request = dummy_validate_review_request
request_validator_mod.validate_statistics_request = dummy_validate_statistics_request
request_validator_mod.sanitize_request_data = dummy_sanitize_request_data
request_validator_mod.get_validation_errors = dummy_get_validation_errors
request_validator_mod.clear_validation_errors = dummy_clear_validation_errors

# Register dummy submodules
sys.modules["src.code_reviewer"] = code_reviewer_mod
sys.modules["src.statistics"] = statistics_mod
sys.modules["src.correlation_middleware"] = correlation_middleware_mod
sys.modules["src.request_validator"] = request_validator_mod

import pytest
from unittest.mock import Mock, patch
from src.app import app


@pytest.fixture
def client():
    """Provide a Flask test client for the app."""
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_dummy_modules_state():
    """Reset in-memory stores for dummy modules between tests."""
    # Reset traces
    correlation_middleware_mod._correlation_traces = {}
    # Reset validation errors
    _validation_errors_store.clear()
    yield


def test_health_check_ok(client):
    """GET /health should return healthy status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"status": "healthy", "service": "python-reviewer"}


@pytest.mark.parametrize("payload,expected_status", [
    (None, 400),
    ({}, 400),
])
def test_review_code_missing_body(client, payload, expected_status):
    """POST /review should return 400 when body is missing or empty."""
    if payload is None:
        resp = client.post("/review")
    else:
        resp = client.post("/review", json=payload)
    assert resp.status_code == expected_status
    data = resp.get_json()
    assert data["error"] == "Missing request body"


def test_review_code_validation_error(client):
    """POST /review should return 422 on validation errors."""
    class DummyError:
        def __init__(self, field, message):
            self.field = field
            self.message = message

        def to_dict(self):
            return {"field": self.field, "message": self.message}

    errors = [DummyError("content", "Content is required")]

    with patch("src.app.validate_review_request", return_value=errors):
        resp = client.post("/review", json={"content": "", "language": "python"})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"] == [{"field": "content", "message": "Content is required"}]


def test_review_code_success(client):
    """POST /review should process valid input and return review results."""
    issues = [
        SimpleNamespace(severity="high", line=10, message="Bad practice", suggestion="Refactor"),
        SimpleNamespace(severity="low", line=20, message="Nit", suggestion="Rename"),
    ]
    result = SimpleNamespace(
        score=85,
        issues=issues,
        suggestions=["Use list comprehension"],
        complexity_score=2.5
    )

    mock_reviewer = Mock()
    mock_reviewer.review_code.return_value = result

    with patch("src.app.reviewer", mock_reviewer), \
         patch("src.app.sanitize_request_data", side_effect=lambda d: d), \
         patch("src.app.validate_review_request", return_value=[]):
        resp = client.post("/review", json={"content": "print('hi')", "language": "python"})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["score"] == 85
    assert data["issues"] == [
        {"severity": "high", "line": 10, "message": "Bad practice", "suggestion": "Refactor"},
        {"severity": "low", "line": 20, "message": "Nit", "suggestion": "Rename"},
    ]
    assert data["suggestions"] == ["Use list comprehension"]
    assert data["complexity_score"] == 2.5
    assert "correlation_id" in data and data["correlation_id"] is None
    mock_reviewer.review_code.assert_called_once_with("print('hi')", "python")


def test_review_function_missing_field(client):
    """POST /review/function should return 400 if 'function_code' is missing."""
    resp = client.post("/review/function", json={"not_function_code": "def f(): pass"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing 'function_code' field"


def test_review_function_success(client):
    """POST /review/function should review the function code and return the result."""
    mock_result = {"issues": [], "summary": "OK"}
    mock_reviewer = Mock()
    mock_reviewer.review_function.return_value = mock_result

    with patch("src.app.reviewer", mock_reviewer):
        resp = client.post("/review/function", json={"function_code": "def f(): pass"})
    assert resp.status_code == 200
    assert resp.get_json() == mock_result
    mock_reviewer.review_function.assert_called_once_with("def f(): pass")


@pytest.mark.parametrize("payload,expected_status", [
    (None, 400),
    ({}, 422),  # because validate_statistics_request will see missing 'files' as error in patched test
])
def test_get_statistics_error_paths(client, payload, expected_status):
    """POST /statistics should handle missing body and validation errors."""
    if payload is None:
        resp = client.post("/statistics")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Missing request body"
        return

    class DummyError:
        def __init__(self, field, message):
            self.field = field
            self.message = message

        def to_dict(self):
            return {"field": self.field, "message": self.message}

    errors = [DummyError("files", "At least one file is required")]
    with patch("src.app.validate_statistics_request", return_value=errors):
        resp = client.post("/statistics", json=payload)
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"] == [{"field": "files", "message": "At least one file is required"}]


def test_get_statistics_success(client):
    """POST /statistics should return aggregated review statistics."""
    stats_obj = SimpleNamespace(
        total_files=3,
        average_score=88.5,
        total_issues=5,
        issues_by_severity={"low": 2, "medium": 2, "high": 1},
        average_complexity=3.2,
        files_with_high_complexity=["a.py", "b.py"],
        total_suggestions=4,
    )
    mock_aggregator = Mock()
    mock_aggregator.aggregate_reviews.return_value = stats_obj

    with patch("src.app.statistics_aggregator", mock_aggregator), \
         patch("src.app.sanitize_request_data", side_effect=lambda d: d), \
         patch("src.app.validate_statistics_request", return_value=[]):
        resp = client.post("/statistics", json={"files": [{"content": "x", "language": "python"}]})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_files"] == 3
    assert data["average_score"] == 88.5
    assert data["total_issues"] == 5
    assert data["issues_by_severity"] == {"low": 2, "medium": 2, "high": 1}
    assert data["average_complexity"] == 3.2
    assert data["files_with_high_complexity"] == ["a.py", "b.py"]
    assert data["total_suggestions"] == 4
    assert "correlation_id" in data and data["correlation_id"] is None
    mock_aggregator.aggregate_reviews.assert_called_once_with([{"content": "x", "language": "python"}])


def test_list_traces_empty(client):
    """GET /traces should return empty list when no traces exist."""
    with patch("src.app.get_all_traces", return_value=[]):
        resp = client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == 0
    assert data["traces"] == []


def test_list_traces_with_items(client):
    """GET /traces should return all traces with correct count."""
    traces = [{"id": "1", "event": "start"}, {"id": "2", "event": "end"}]
    with patch("src.app.get_all_traces", return_value=traces):
        resp = client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == 2
    assert data["traces"] == traces


def test_get_trace_not_found(client):
    """GET /traces/<correlation_id> should return 404 if no traces found."""
    with patch("src.app.get_traces", return_value=[]):
        resp = client.get("/traces/abc123")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "No traces found for correlation ID"


def test_get_trace_found(client):
    """GET /traces/<correlation_id> should return traces when available."""
    traces = [{"step": 1}, {"step": 2}]
    with patch("src.app.get_traces", return_value=traces):
        resp = client.get("/traces/xyz789")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] == "xyz789"
    assert data["trace_count"] == 2
    assert data["traces"] == traces


def test_validation_errors_list_and_delete(client):
    """GET /validation/errors lists current errors; DELETE clears them."""
    # Seed validation errors via dummy module
    current = request_validator_mod.get_validation_errors()
    current.append({"field": "content", "message": "too short"})

    resp_list = client.get("/validation/errors")
    assert resp_list.status_code == 200
    data = resp_list.get_json()
    assert data["total_errors"] == 1
    assert data["errors"] == [{"field": "content", "message": "too short"}]

    resp_delete = client.delete("/validation/errors")
    assert resp_delete.status_code == 200
    assert resp_delete.get_json() == {"message": "Validation errors cleared"}

    resp_list2 = client.get("/validation/errors")
    assert resp_list2.status_code == 200
    data2 = resp_list2.get_json()
    assert data2["total_errors"] == 0
    assert data2["errors"] == []