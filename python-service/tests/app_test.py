# tests/conftest.py
import sys
import types
from flask import g
import pytest

# Create stub modules for external dependencies before importing src.app
# so that from src.app import app works without missing modules.

# Stub for src.code_reviewer
code_reviewer_module = types.ModuleType("src.code_reviewer")


class StubIssue:
    def __init__(self, severity="warning", line=1, message="msg", suggestion="sugg"):
        self.severity = severity
        self.line = line
        self.message = message
        self.suggestion = suggestion


class StubReviewResult:
    def __init__(self, score=90, issues=None, suggestions=None, complexity_score=3.2):
        self.score = score
        self.issues = issues or [StubIssue()]
        self.suggestions = suggestions or ["use better var names"]
        self.complexity_score = complexity_score


class CodeReviewer:
    def review_code(self, content, language):
        return StubReviewResult()

    def review_function(self, function_code):
        return {"ok": True, "details": "function reviewed"}


code_reviewer_module.CodeReviewer = CodeReviewer
code_reviewer_module.StubIssue = StubIssue
code_reviewer_module.StubReviewResult = StubReviewResult
sys.modules["src.code_reviewer"] = code_reviewer_module

# Stub for src.statistics
statistics_module = types.ModuleType("src.statistics")


class StubStatistics:
    def __init__(
        self,
        total_files=2,
        average_score=85.5,
        total_issues=5,
        issues_by_severity=None,
        average_complexity=2.7,
        files_with_high_complexity=None,
        total_suggestions=4,
    ):
        self.total_files = total_files
        self.average_score = average_score
        self.total_issues = total_issues
        self.issues_by_severity = issues_by_severity or {"error": 1, "warning": 4}
        self.average_complexity = average_complexity
        self.files_with_high_complexity = files_with_high_complexity or ["a.py"]
        self.total_suggestions = total_suggestions


class StatisticsAggregator:
    def aggregate_reviews(self, files):
        return StubStatistics(total_files=len(files))


statistics_module.StatisticsAggregator = StatisticsAggregator
statistics_module.StubStatistics = StubStatistics
sys.modules["src.statistics"] = statistics_module

# Stub for src.correlation_middleware
correlation_module = types.ModuleType("src.correlation_middleware")

# simple in-memory traces for stubs
_STUB_TRACES = {}


class CorrelationIDMiddleware:
    def __init__(self, app):
        @app.before_request
        def _set_correlation():
            # Default correlation id for tests
            g.correlation_id = "test-correlation-id"


def get_traces(correlation_id):
    return _STUB_TRACES.get(correlation_id, [])


def get_all_traces():
    all_items = []
    for items in _STUB_TRACES.values():
        all_items.extend(items)
    return all_items


correlation_module.CorrelationIDMiddleware = CorrelationIDMiddleware
correlation_module.get_traces = get_traces
correlation_module.get_all_traces = get_all_traces
sys.modules["src.correlation_middleware"] = correlation_module

# Stub for src.request_validator
request_validator_module = types.ModuleType("src.request_validator")
_VALIDATION_ERRORS = []


class StubValidationError:
    def __init__(self, code="invalid", field="content", message="error"):
        self.code = code
        self.field = field
        self.message = message

    def to_dict(self):
        return {"code": self.code, "field": self.field, "message": self.message}


def validate_review_request(data):
    return []


def validate_statistics_request(data):
    return []


def sanitize_request_data(data):
    return data


def get_validation_errors():
    return list(_VALIDATION_ERRORS)


def clear_validation_errors():
    _VALIDATION_ERRORS.clear()


request_validator_module.validate_review_request = validate_review_request
request_validator_module.validate_statistics_request = validate_statistics_request
request_validator_module.sanitize_request_data = sanitize_request_data
request_validator_module.get_validation_errors = get_validation_errors
request_validator_module.clear_validation_errors = clear_validation_errors
request_validator_module.StubValidationError = StubValidationError
request_validator_module._VALIDATION_ERRORS = _VALIDATION_ERRORS
sys.modules["src.request_validator"] = request_validator_module

# Now import the Flask app after stubs are in place
from src.app import app as flask_app  # noqa: E402


@pytest.fixture
def client():
    """Provide a Flask test client for the app."""
    return flask_app.test_client()


@pytest.fixture
def stub_modules():
    """Expose stub modules to tests for direct manipulation if needed."""
    return {
        "code_reviewer": code_reviewer_module,
        "statistics": statistics_module,
        "correlation": correlation_module,
        "request_validator": request_validator_module,
    }


# tests/test_app_endpoints.py
import pytest
from unittest.mock import patch
from src.app import app  # ensure exact import per requirements


def test_health_check_ok(client):
    """GET /health should return service health JSON."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "healthy", "service": "python-reviewer"}


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},  # empty dict is falsy -> treated as missing
    ],
)
def test_review_code_missing_body(client, payload):
    """POST /review should return 400 when body is missing or empty."""
    if payload is None:
        resp = client.post("/review")
    else:
        resp = client.post("/review", json=payload)

    assert resp.status_code == 400
    assert resp.get_json() == {"error": "Missing request body"}


def test_review_code_validation_error(client, stub_modules):
    """POST /review should return 422 with details when validation fails."""
    stub_error = stub_modules["request_validator"].StubValidationError(
        code="missing", field="content", message="Content is required"
    )
    with patch("src.app.validate_review_request", return_value=[stub_error]):
        resp = client.post("/review", json={"language": "python"})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "Validation failed"
    assert body["details"] == [stub_error.to_dict()]


def test_review_code_success_maps_result_and_correlation_id(client):
    """POST /review should map reviewer result to response and include correlation_id."""
    class MockIssue:
        def __init__(self):
            self.severity = "error"
            self.line = 10
            self.message = "Avoid eval"
            self.suggestion = "Use ast.literal_eval"

    class MockResult:
        def __init__(self):
            self.score = 75
            self.issues = [MockIssue()]
            self.suggestions = ["Refactor into smaller functions"]
            self.complexity_score = 5.6

    with patch("src.app.validate_review_request", return_value=[]), patch(
        "src.app.sanitize_request_data", side_effect=lambda d: d
    ), patch("src.app.reviewer.review_code", return_value=MockResult()):
        resp = client.post(
            "/review",
            json={"content": "eval('1+1')", "language": "python"},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["score"] == 75
    assert body["issues"] == [
        {
            "severity": "error",
            "line": 10,
            "message": "Avoid eval",
            "suggestion": "Use ast.literal_eval",
        }
    ]
    assert body["suggestions"] == ["Refactor into smaller functions"]
    assert body["complexity_score"] == 5.6
    # correlation id should be set by stub middleware
    assert body["correlation_id"] == "test-correlation-id"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},  # missing function_code
    ],
)
def test_review_function_missing_field(client, payload):
    """POST /review/function should 400 when function_code is missing."""
    if payload is None:
        resp = client.post("/review/function")
    else:
        resp = client.post("/review/function", json=payload)
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "Missing 'function_code' field"}


def test_review_function_success_returns_reviewer_output(client):
    """POST /review/function should return underlying reviewer output."""
    expected = {"ok": True, "details": "all good"}
    with patch("src.app.reviewer.review_function", return_value=expected):
        resp = client.post("/review/function", json={"function_code": "def f(): pass"})
    assert resp.status_code == 200
    assert resp.get_json() == expected


@pytest.mark.parametrize(
    "payload, expected_status, expected_error",
    [
        (None, 400, {"error": "Missing request body"}),
    ],
)
def test_statistics_missing_body(client, payload, expected_status, expected_error):
    """POST /statistics should validate presence of request body."""
    if payload is None:
        resp = client.post("/statistics")
    else:
        resp = client.post("/statistics", json=payload)
    assert resp.status_code == expected_status
    assert resp.get_json() == expected_error


def test_statistics_validation_error(client, stub_modules):
    """POST /statistics should return 422 when validation fails."""
    stub_error = stub_modules["request_validator"].StubValidationError(
        code="invalid", field="files", message="Files must be a list"
    )
    with patch("src.app.validate_statistics_request", return_value=[stub_error]):
        resp = client.post("/statistics", json={"files": "not-a-list"})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "Validation failed"
    assert body["details"] == [stub_error.to_dict()]


def test_statistics_success_maps_aggregator_result_and_correlation_id(client):
    """POST /statistics should map aggregator result to response and include correlation_id."""
    class MockStats:
        def __init__(self):
            self.total_files = 3
            self.average_score = 88.8
            self.total_issues = 7
            self.issues_by_severity = {"error": 2, "warning": 5}
            self.average_complexity = 3.9
            self.files_with_high_complexity = ["a.py", "b.py"]
            self.total_suggestions = 9

    with patch("src.app.validate_statistics_request", return_value=[]), patch(
        "src.app.sanitize_request_data", side_effect=lambda d: d
    ), patch("src.app.statistics_aggregator.aggregate_reviews", return_value=MockStats()):
        resp = client.post("/statistics", json={"files": ["a.py", "b.py", "c.py"]})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_files"] == 3
    assert body["average_score"] == 88.8
    assert body["total_issues"] == 7
    assert body["issues_by_severity"] == {"error": 2, "warning": 5}
    assert body["average_complexity"] == 3.9
    assert body["files_with_high_complexity"] == ["a.py", "b.py"]
    assert body["total_suggestions"] == 9
    assert body["correlation_id"] == "test-correlation-id"


def test_list_traces_returns_all(client):
    """GET /traces should return total count and list of all traces."""
    traces = [
        {"id": "t1", "msg": "one"},
        {"id": "t2", "msg": "two"},
    ]
    with patch("src.app.get_all_traces", return_value=traces):
        resp = client.get("/traces")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_traces"] == 2
    assert body["traces"] == traces


def test_get_trace_404_when_not_found(client):
    """GET /traces/<id> should 404 when no traces for correlation id."""
    with patch("src.app.get_traces", return_value=[]):
        resp = client.get("/traces/unknown-id")
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "No traces found for correlation ID"}


def test_get_trace_returns_traces_for_id(client):
    """GET /traces/<id> should return traces for given correlation id."""
    correlation_id = "abc-123"
    traces = [{"event": "start"}, {"event": "end"}]

    def _get_traces(arg_id):
        return traces if arg_id == correlation_id else []

    with patch("src.app.get_traces", side_effect=_get_traces):
        resp = client.get(f"/traces/{correlation_id}")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["correlation_id"] == correlation_id
    assert body["trace_count"] == len(traces)
    assert body["traces"] == traces


def test_list_validation_errors_returns_items(client):
    """GET /validation/errors should return total and list of validation errors."""
    errors = [
        {"code": "missing", "field": "content", "message": "Required"},
        {"code": "invalid", "field": "language", "message": "Unsupported"},
    ]
    with patch("src.app.get_validation_errors", return_value=errors):
        resp = client.get("/validation/errors")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_errors"] == 2
    assert body["errors"] == errors


def test_delete_validation_errors_clears_items(client):
    """DELETE /validation/errors should call clear_validation_errors and return message."""
    with patch("src.app.clear_validation_errors") as clear_mock:
        resp = client.delete("/validation/errors")
    assert resp.status_code == 200
    assert resp.get_json() == {"message": "Validation errors cleared"}
    assert clear_mock.called is True