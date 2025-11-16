import sys
import types
from typing import List, Dict, Any

import pytest

# Set up fake modules for external dependencies before importing src.app
# Create fake src.code_reviewer
code_reviewer_mod = types.ModuleType("src.code_reviewer")


class FakeIssue:
    def __init__(self, severity: str, line: int, message: str, suggestion: str):
        self.severity = severity
        self.line = line
        self.message = message
        self.suggestion = suggestion


class FakeReviewResult:
    def __init__(self, score: float, issues: List[FakeIssue], suggestions: List[str], complexity_score: float):
        self.score = score
        self.issues = issues
        self.suggestions = suggestions
        self.complexity_score = complexity_score


class CodeReviewer:
    def review_code(self, content: str, language: str):
        return FakeReviewResult(
            score=0,
            issues=[],
            suggestions=[],
            complexity_score=0,
        )

    def review_function(self, function_code: str) -> Dict[str, Any]:
        return {"ok": True}


code_reviewer_mod.CodeReviewer = CodeReviewer
sys.modules["src.code_reviewer"] = code_reviewer_mod

# Create fake src.statistics
statistics_mod = types.ModuleType("src.statistics")


class FakeStats:
    def __init__(
        self,
        total_files: int = 0,
        average_score: float = 0.0,
        total_issues: int = 0,
        issues_by_severity: Dict[str, int] = None,
        average_complexity: float = 0.0,
        files_with_high_complexity: List[str] = None,
        total_suggestions: int = 0,
    ):
        self.total_files = total_files
        self.average_score = average_score
        self.total_issues = total_issues
        self.issues_by_severity = issues_by_severity or {}
        self.average_complexity = average_complexity
        self.files_with_high_complexity = files_with_high_complexity or []
        self.total_suggestions = total_suggestions


class StatisticsAggregator:
    def aggregate_reviews(self, files: List[Dict[str, Any]]) -> FakeStats:
        return FakeStats()


statistics_mod.StatisticsAggregator = StatisticsAggregator
sys.modules["src.statistics"] = statistics_mod

# Create fake src.correlation_middleware
correlation_mw_mod = types.ModuleType("src.correlation_middleware")
from flask import g, request  # noqa: E402


class CorrelationIDMiddleware:
    def __init__(self, app):
        self.app = app

        @app.before_request
        def _set_corr_id():
            g.correlation_id = request.headers.get("X-Correlation-ID", None)


_TRACES: Dict[str, List[Dict[str, Any]]] = {}


def get_traces(correlation_id: str) -> List[Dict[str, Any]]:
    return _TRACES.get(correlation_id, [])


def get_all_traces() -> List[Dict[str, Any]]:
    all_items: List[Dict[str, Any]] = []
    for v in _TRACES.values():
        all_items.extend(v)
    return all_items


correlation_mw_mod.CorrelationIDMiddleware = CorrelationIDMiddleware
correlation_mw_mod.get_traces = get_traces
correlation_mw_mod.get_all_traces = get_all_traces
sys.modules["src.correlation_middleware"] = correlation_mw_mod

# Create fake src.request_validator
request_validator_mod = types.ModuleType("src.request_validator")


class ValidationError:
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message

    def to_dict(self) -> Dict[str, str]:
        return {"field": self.field, "message": self.message}


_VALIDATION_ERRORS_STORE: List[Dict[str, Any]] = []


def validate_review_request(data: Dict[str, Any]):
    if "content" not in data:
        return [ValidationError("content", "Missing content")]
    return []


def validate_statistics_request(data: Dict[str, Any]):
    if "files" not in data:
        return [ValidationError("files", "Missing files")]
    return []


def sanitize_request_data(data: Dict[str, Any]) -> Dict[str, Any]:
    return data


def get_validation_errors() -> List[Dict[str, Any]]:
    return list(_VALIDATION_ERRORS_STORE)


def clear_validation_errors():
    _VALIDATION_ERRORS_STORE.clear()


request_validator_mod.validate_review_request = validate_review_request
request_validator_mod.validate_statistics_request = validate_statistics_request
request_validator_mod.sanitize_request_data = sanitize_request_data
request_validator_mod.get_validation_errors = get_validation_errors
request_validator_mod.clear_validation_errors = clear_validation_errors
sys.modules["src.request_validator"] = request_validator_mod

# Now safe to import the app
from src.app import app, reviewer, statistics_aggregator  # noqa: E402
import src.app as app_module  # noqa: E402

from unittest.mock import Mock, patch
from types import SimpleNamespace


@pytest.fixture
def client():
    with app.test_client() as c:
        yield c


@pytest.fixture
def dummy_issue():
    return SimpleNamespace(severity="warning", line=10, message="Use of deprecated API", suggestion="Use new_api()")


@pytest.fixture
def dummy_review_result(dummy_issue):
    return SimpleNamespace(
        score=85.5,
        issues=[dummy_issue],
        suggestions=["Refactor function foo"],
        complexity_score=12.3,
    )


@pytest.fixture
def dummy_stats():
    return SimpleNamespace(
        total_files=3,
        average_score=78.2,
        total_issues=5,
        issues_by_severity={"low": 2, "medium": 2, "high": 1},
        average_complexity=9.1,
        files_with_high_complexity=["a.py", "b.py"],
        total_suggestions=4,
    )


def test_health_check_returns_healthy(client):
    """Test /health endpoint returns healthy status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
    ],
)
def test_review_code_missing_body_returns_400(client, payload):
    """Test /review returns 400 when request body is missing or empty."""
    if payload is None:
        resp = client.post("/review")
    else:
        resp = client.post("/review", json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_review_code_validation_error_returns_422(client):
    """Test /review returns 422 with validation error details."""
    error_obj = SimpleNamespace(to_dict=lambda: {"field": "content", "message": "must not be empty"})
    with patch("src.app.validate_review_request", return_value=[error_obj]):
        resp = client.post("/review", json={"content": ""})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "Validation failed"
    assert body["details"] == [{"field": "content", "message": "must not be empty"}]


def test_review_code_success_returns_result_and_correlation_id(client, dummy_review_result):
    """Test /review returns 200 with review result and propagates correlation_id."""
    with patch("src.app.validate_review_request", return_value=[]), patch(
        "src.app.sanitize_request_data", side_effect=lambda d: d
    ), patch.object(reviewer, "review_code", return_value=dummy_review_result):
        resp = client.post(
            "/review",
            json={"content": "print('hello')", "language": "python"},
            headers={"X-Correlation-ID": "abc-123"},
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["score"] == dummy_review_result.score
    assert body["issues"][0]["severity"] == dummy_review_result.issues[0].severity
    assert body["issues"][0]["line"] == dummy_review_result.issues[0].line
    assert body["issues"][0]["message"] == dummy_review_result.issues[0].message
    assert body["issues"][0]["suggestion"] == dummy_review_result.issues[0].suggestion
    assert body["suggestions"] == dummy_review_result.suggestions
    assert body["complexity_score"] == dummy_review_result.complexity_score
    assert body["correlation_id"] == "abc-123"


def test_review_function_missing_field_returns_400(client):
    """Test /review/function returns 400 when 'function_code' is missing."""
    resp = client.post("/review/function", json={"not_function_code": "x"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing 'function_code' field"


def test_review_function_success_returns_payload(client):
    """Test /review/function returns 200 with reviewer-provided payload."""
    expected = {"ok": True, "issues": [], "meta": {"fn": "foo"}}
    with patch.object(reviewer, "review_function", return_value=expected):
        resp = client.post("/review/function", json={"function_code": "def foo(): pass"})
    assert resp.status_code == 200
    assert resp.get_json() == expected


def test_statistics_missing_body_returns_400(client):
    """Test /statistics returns 400 when body is missing."""
    resp = client.post("/statistics")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_statistics_validation_error_returns_422(client):
    """Test /statistics returns 422 with validation errors."""
    error_obj = SimpleNamespace(to_dict=lambda: {"field": "files", "message": "required"})
    with patch("src.app.validate_statistics_request", return_value=[error_obj]):
        resp = client.post("/statistics", json={"files": None})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "Validation failed"
    assert body["details"] == [{"field": "files", "message": "required"}]


def test_statistics_success_returns_aggregated_stats_and_correlation_id(client, dummy_stats):
    """Test /statistics returns 200 with aggregated statistics and correlation_id."""
    with patch("src.app.validate_statistics_request", return_value=[]), patch(
        "src.app.sanitize_request_data", side_effect=lambda d: d
    ), patch.object(statistics_aggregator, "aggregate_reviews", return_value=dummy_stats):
        resp = client.post(
            "/statistics",
            json={"files": [{"content": "print(1)", "language": "python"}]},
            headers={"X-Correlation-ID": "cid-789"},
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_files"] == dummy_stats.total_files
    assert data["average_score"] == dummy_stats.average_score
    assert data["total_issues"] == dummy_stats.total_issues
    assert data["issues_by_severity"] == dummy_stats.issues_by_severity
    assert data["average_complexity"] == dummy_stats.average_complexity
    assert data["files_with_high_complexity"] == dummy_stats.files_with_high_complexity
    assert data["total_suggestions"] == dummy_stats.total_suggestions
    assert data["correlation_id"] == "cid-789"


def test_list_traces_returns_total_and_items(client):
    """Test /traces returns total_traces and list of traces."""
    traces = [{"id": 1, "msg": "a"}, {"id": 2, "msg": "b"}]
    with patch("src.app.get_all_traces", return_value=traces):
        resp = client.get("/traces")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_traces"] == 2
    assert body["traces"] == traces


def test_get_trace_not_found_returns_404(client):
    """Test /traces/<correlation_id> returns 404 when no traces found."""
    with patch("src.app.get_traces", return_value=[]):
        resp = client.get("/traces/unknown-id")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "No traces found for correlation ID"


def test_get_trace_success_returns_trace_list(client):
    """Test /traces/<correlation_id> returns trace data when found."""
    items = [{"id": "t1"}, {"id": "t2"}]
    with patch("src.app.get_traces", return_value=items):
        resp = client.get("/traces/corr-123")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["correlation_id"] == "corr-123"
    assert body["trace_count"] == 2
    assert body["traces"] == items


def test_list_validation_errors_empty(client):
    """Test /validation/errors returns empty list when no errors."""
    with patch("src.app.get_validation_errors", return_value=[]):
        resp = client.get("/validation/errors")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_errors"] == 0
    assert body["errors"] == []


def test_list_validation_errors_with_items(client):
    """Test /validation/errors returns provided errors."""
    errors = [{"field": "content", "message": "missing"}, {"field": "files", "message": "invalid"}]
    with patch("src.app.get_validation_errors", return_value=errors):
        resp = client.get("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == 2
    assert data["errors"] == errors


def test_delete_validation_errors_invokes_clear_and_returns_message(client):
    """Test DELETE /validation/errors calls clear_validation_errors and returns message."""
    with patch("src.app.clear_validation_errors") as mocked_clear:
        resp = client.delete("/validation/errors")
    mocked_clear.assert_called_once()
    assert resp.status_code == 200
    assert resp.get_json()["message"] == "Validation errors cleared"