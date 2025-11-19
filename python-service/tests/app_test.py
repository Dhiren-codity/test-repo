import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

# ---------------------------------------------------------------------------
# Provide fake submodules for dependencies that may not exist in the test env
# ---------------------------------------------------------------------------
if 'src.code_reviewer' not in sys.modules:
    m = types.ModuleType('src.code_reviewer')

    class CodeReviewer:
        def review_code(self, content, language):
            return {}

        def review_function(self, function_code):
            return {}

    m.CodeReviewer = CodeReviewer
    sys.modules['src.code_reviewer'] = m

if 'src.statistics' not in sys.modules:
    m = types.ModuleType('src.statistics')

    class StatisticsAggregator:
        def aggregate_reviews(self, files):
            return {}

    m.StatisticsAggregator = StatisticsAggregator
    sys.modules['src.statistics'] = m

if 'src.correlation_middleware' not in sys.modules:
    m = types.ModuleType('src.correlation_middleware')

    class CorrelationIDMiddleware:
        def __init__(self, app):
            self.app = app

    def get_traces(correlation_id):
        return []

    def get_all_traces():
        return []

    m.CorrelationIDMiddleware = CorrelationIDMiddleware
    m.get_traces = get_traces
    m.get_all_traces = get_all_traces
    sys.modules['src.correlation_middleware'] = m

if 'src.request_validator' not in sys.modules:
    m = types.ModuleType('src.request_validator')

    def validate_review_request(data):
        return []

    def validate_statistics_request(data):
        return []

    def sanitize_request_data(data):
        return data

    _errors = []

    def get_validation_errors():
        return list(_errors)

    def clear_validation_errors():
        _errors.clear()

    m.validate_review_request = validate_review_request
    m.validate_statistics_request = validate_statistics_request
    m.sanitize_request_data = sanitize_request_data
    m.get_validation_errors = get_validation_errors
    m.clear_validation_errors = clear_validation_errors
    sys.modules['src.request_validator'] = m

# Import the Flask app and module-level objects under test
from src.app import app, reviewer, statistics_aggregator  # noqa: E402


@pytest.fixture
def client():
    """Provide a Flask test client."""
    app.testing = True
    with app.test_client() as client:
        yield client


def test_health_check_ok(client):
    """GET /health returns service health JSON."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


def test_review_code_missing_body_returns_400(client):
    """POST /review with no body returns 400 error."""
    resp = client.post("/review")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_review_code_validation_errors_returns_422(client, monkeypatch):
    """POST /review returns 422 with validation error details."""

    class DummyError:
        def __init__(self, field, message):
            self.field = field
            self.message = message

        def to_dict(self):
            return {"field": self.field, "message": self.message}

    monkeypatch.setattr("src.app.validate_review_request", lambda data: [DummyError("content", "required")])

    resp = client.post("/review", json={"content": "", "language": "python"})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"] == [{"field": "content", "message": "required"}]


def test_review_code_success_returns_expected_payload(client, monkeypatch):
    """POST /review returns 200 and expected review payload."""
    # No validation errors
    monkeypatch.setattr("src.app.validate_review_request", lambda data: [])
    # Sanitization returns expected fields
    monkeypatch.setattr("src.app.sanitize_request_data", lambda data: {"content": "print(1)", "language": "python"})

    issue1 = SimpleNamespace(severity="error", line=1, message="Bad practice", suggestion="Avoid")
    issue2 = SimpleNamespace(severity="warning", line=2, message="Consider change", suggestion="Refactor")
    result = SimpleNamespace(
        score=88,
        issues=[issue1, issue2],
        suggestions=["Use better naming"],
        complexity_score=3.7,
    )
    monkeypatch.setattr(reviewer, "review_code", Mock(return_value=result))

    resp = client.post("/review", json={"content": "ignored", "language": "ignored"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["score"] == 88
    assert data["issues"] == [
        {"severity": "error", "line": 1, "message": "Bad practice", "suggestion": "Avoid"},
        {"severity": "warning", "line": 2, "message": "Consider change", "suggestion": "Refactor"},
    ]
    assert data["suggestions"] == ["Use better naming"]
    assert data["complexity_score"] == 3.7
    assert "correlation_id" in data


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
    ],
)
def test_review_function_missing_field_returns_400(client, payload):
    """POST /review/function requires 'function_code' field."""
    if payload is None:
        resp = client.post("/review/function")
    else:
        resp = client.post("/review/function", json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing 'function_code' field"


def test_review_function_success(client, monkeypatch):
    """POST /review/function returns JSON from reviewer.review_function."""
    expected = {"issues": [], "score": 100, "notes": "ok"}
    monkeypatch.setattr(reviewer, "review_function", Mock(return_value=expected))

    resp = client.post("/review/function", json={"function_code": "def foo(): pass"})
    assert resp.status_code == 200
    assert resp.get_json() == expected


def test_statistics_missing_body_returns_400(client):
    """POST /statistics with no body returns 400."""
    resp = client.post("/statistics")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_statistics_validation_errors_returns_422(client, monkeypatch):
    """POST /statistics returns 422 with validation errors."""

    class DummyError:
        def __init__(self, field, message):
            self.field = field
            self.message = message

        def to_dict(self):
            return {"field": self.field, "message": self.message}

    monkeypatch.setattr("src.app.validate_statistics_request", lambda data: [DummyError("files", "invalid")])

    resp = client.post("/statistics", json={"files": "not-a-list"})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"] == [{"field": "files", "message": "invalid"}]


def test_statistics_success_returns_aggregates(client, monkeypatch):
    """POST /statistics returns aggregated stats."""
    monkeypatch.setattr("src.app.validate_statistics_request", lambda data: [])
    monkeypatch.setattr("src.app.sanitize_request_data", lambda data: {"files": [{"content": "x"}, {"content": "y"}]})

    stats_obj = SimpleNamespace(
        total_files=2,
        average_score=91.2,
        total_issues=4,
        issues_by_severity={"error": 1, "warning": 3},
        average_complexity=4.3,
        files_with_high_complexity=["a.py"],
        total_suggestions=7,
    )
    monkeypatch.setattr(statistics_aggregator, "aggregate_reviews", Mock(return_value=stats_obj))

    resp = client.post("/statistics", json={"files": []})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_files"] == 2
    assert data["average_score"] == 91.2
    assert data["total_issues"] == 4
    assert data["issues_by_severity"] == {"error": 1, "warning": 3}
    assert data["average_complexity"] == 4.3
    assert data["files_with_high_complexity"] == ["a.py"]
    assert data["total_suggestions"] == 7
    assert "correlation_id" in data


def test_list_traces_returns_total_and_items(client, monkeypatch):
    """GET /traces returns total_traces and traces list."""
    traces = [{"id": "t1"}, {"id": "t2"}, {"id": "t3"}]
    monkeypatch.setattr("src.app.get_all_traces", lambda: traces)

    resp = client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == 3
    assert data["traces"] == traces


@pytest.mark.parametrize(
    "traces, status_code, expected",
    [
        ([], 404, {"error": "No traces found for correlation ID"}),
        ([{"step": 1}], 200, {"trace_count": 1}),
    ],
)
def test_get_trace_by_correlation_id(client, monkeypatch, traces, status_code, expected):
    """GET /traces/<id> returns 404 when not found, otherwise trace details."""
    monkeypatch.setattr("src.app.get_traces", lambda cid: traces)

    resp = client.get("/traces/corr-123")
    assert resp.status_code == status_code
    data = resp.get_json()
    if status_code == 404:
        assert data == expected
    else:
        assert data["correlation_id"] == "corr-123"
        assert data["trace_count"] == expected["trace_count"]
        assert data["traces"] == traces


def test_list_validation_errors_returns_errors(client, monkeypatch):
    """GET /validation/errors returns total and error items."""
    errors = [{"field": "content", "message": "missing"}, {"field": "files", "message": "invalid type"}]
    monkeypatch.setattr("src.app.get_validation_errors", lambda: errors)

    resp = client.get("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == len(errors)
    assert data["errors"] == errors


def test_delete_validation_errors_clears_and_returns_message(client, monkeypatch):
    """DELETE /validation/errors clears errors and returns confirmation message."""
    clear_mock = Mock()
    monkeypatch.setattr("src.app.clear_validation_errors", clear_mock)

    resp = client.delete("/validation/errors")
    assert resp.status_code == 200
    assert resp.get_json() == {"message": "Validation errors cleared"}
    clear_mock.assert_called_once()