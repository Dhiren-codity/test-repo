import sys
import types
import pytest

# Create fake external modules before importing src.app

# Fake src.code_reviewer
code_reviewer_module = types.ModuleType("src.code_reviewer")


class FakeIssue:
    def __init__(self, severity="medium", line=1, message="Sample issue", suggestion="Consider change"):
        self.severity = severity
        self.line = line
        self.message = message
        self.suggestion = suggestion


class FakeReviewResult:
    def __init__(self, score=85, issues=None, suggestions=None, complexity_score=3.2):
        self.score = score
        self.issues = issues if issues is not None else [FakeIssue()]
        self.suggestions = suggestions if suggestions is not None else ["Use best practices"]
        self.complexity_score = complexity_score


class CodeReviewer:
    def review_code(self, content, language="python"):
        # Produce deterministic result based on content length to diversify a bit
        score = 100 - min(len(content), 20)
        issues = [FakeIssue(severity="low" if len(content) > 0 else "high", line=1, message="Test issue", suggestion="Fix it")]
        suggestions = ["Refactor function", "Add docstring"]
        complexity_score = 1.5 + (len(content) % 3) * 0.5
        return FakeReviewResult(score=score, issues=issues, suggestions=suggestions, complexity_score=complexity_score)

    def review_function(self, function_code):
        # Trivial "analysis" with controlled output
        if "def " in function_code:
            return {"valid": True, "issues": [], "summary": "Function looks fine"}
        return {"valid": False, "issues": [{"type": "validation", "message": "No function found"}]}


code_reviewer_module.CodeReviewer = CodeReviewer
sys.modules["src.code_reviewer"] = code_reviewer_module

# Fake src.statistics
statistics_module = types.ModuleType("src.statistics")


class FakeStats:
    def __init__(
        self,
        total_files=1,
        average_score=90.5,
        total_issues=2,
        issues_by_severity=None,
        average_complexity=2.1,
        files_with_high_complexity=None,
        total_suggestions=3,
    ):
        self.total_files = total_files
        self.average_score = average_score
        self.total_issues = total_issues
        self.issues_by_severity = issues_by_severity if issues_by_severity is not None else {"low": 1, "medium": 1, "high": 0}
        self.average_complexity = average_complexity
        self.files_with_high_complexity = files_with_high_complexity if files_with_high_complexity is not None else []
        self.total_suggestions = total_suggestions


class StatisticsAggregator:
    def aggregate_reviews(self, files):
        count = len(files)
        return FakeStats(
            total_files=count,
            average_score=88.0 if count else 0.0,
            total_issues=5 * count,
            issues_by_severity={"low": 2 * count, "medium": 2 * count, "high": 1 * count},
            average_complexity=2.0 + 0.1 * count,
            files_with_high_complexity=[i for i, _ in enumerate(files)] if count else [],
            total_suggestions=3 * count,
        )


statistics_module.StatisticsAggregator = StatisticsAggregator
sys.modules["src.statistics"] = statistics_module

# Fake src.correlation_middleware
correlation_module = types.ModuleType("src.correlation_middleware")
from flask import g, request  # noqa: E402


class CorrelationIDMiddleware:
    def __init__(self, app):
        @app.before_request
        def _set_correlation_id():
            cid = request.headers.get("X-Correlation-ID")
            g.correlation_id = cid if cid else None


# In-memory traces (simple list of dicts)
TRACES = []


def get_traces(correlation_id):
    return [t for t in TRACES if t.get("correlation_id") == correlation_id]


def get_all_traces():
    return list(TRACES)


correlation_module.CorrelationIDMiddleware = CorrelationIDMiddleware
correlation_module.get_traces = get_traces
correlation_module.get_all_traces = get_all_traces
correlation_module.TRACES = TRACES
sys.modules["src.correlation_middleware"] = correlation_module

# Fake src.request_validator
request_validator_module = types.ModuleType("src.request_validator")


class SimpleValidationError:
    def __init__(self, field, message, code="invalid"):
        self.field = field
        self.message = message
        self.code = code

    def to_dict(self):
        return {"field": self.field, "message": self.message, "code": self.code}


_VALIDATION_ERRORS_STORE = []


def validate_review_request(data):
    errors = []
    if "content" not in data or not isinstance(data.get("content"), str) or not data.get("content"):
        err = SimpleValidationError("content", "Content is required", "required")
        errors.append(err)
        _VALIDATION_ERRORS_STORE.append(err.to_dict())
    lang = data.get("language")
    if lang is not None and not isinstance(lang, str):
        err = SimpleValidationError("language", "Language must be a string", "type_error")
        errors.append(err)
        _VALIDATION_ERRORS_STORE.append(err.to_dict())
    return errors


def validate_statistics_request(data):
    errors = []
    files = data.get("files")
    if files is None:
        err = SimpleValidationError("files", "Files field is required", "required")
        errors.append(err)
        _VALIDATION_ERRORS_STORE.append(err.to_dict())
    elif not isinstance(files, list):
        err = SimpleValidationError("files", "Files must be a list", "type_error")
        errors.append(err)
        _VALIDATION_ERRORS_STORE.append(err.to_dict())
    return errors


def sanitize_request_data(data):
    return data


def get_validation_errors():
    return list(_VALIDATION_ERRORS_STORE)


def clear_validation_errors():
    _VALIDATION_ERRORS_STORE.clear()


request_validator_module.validate_review_request = validate_review_request
request_validator_module.validate_statistics_request = validate_statistics_request
request_validator_module.sanitize_request_data = sanitize_request_data
request_validator_module.get_validation_errors = get_validation_errors
request_validator_module.clear_validation_errors = clear_validation_errors
request_validator_module.SimpleValidationError = SimpleValidationError
request_validator_module._VALIDATION_ERRORS_STORE = _VALIDATION_ERRORS_STORE
sys.modules["src.request_validator"] = request_validator_module

# Now we can safely import the Flask app
from src.app import app  # noqa: E402


@pytest.fixture(autouse=True)
def reset_stores():
    """Reset in-memory fake stores before and after each test."""
    request_validator_module._VALIDATION_ERRORS_STORE.clear()
    correlation_module.TRACES.clear()
    yield
    request_validator_module._VALIDATION_ERRORS_STORE.clear()
    correlation_module.TRACES.clear()


@pytest.fixture
def client():
    """Provide a Flask test client."""
    with app.test_client() as c:
        yield c


def test_health_check_ok(client):
    """GET /health returns service status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "healthy"
    assert body["service"] == "python-reviewer"


def test_review_code_missing_body_returns_400(client):
    """POST /review without a body returns 400."""
    resp = client.post("/review")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_review_code_validation_error_records_and_returns_422(client):
    """POST /review with invalid data returns 422 and records validation errors."""
    resp = client.post("/review", json={})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "Validation failed"
    assert isinstance(body["details"], list)
    assert any(d["field"] == "content" for d in body["details"])

    # Verify errors are recorded
    err_resp = client.get("/validation/errors")
    assert err_resp.status_code == 200
    errs = err_resp.get_json()
    assert errs["total_errors"] >= 1
    assert any(e["field"] == "content" for e in errs["errors"])


@pytest.mark.parametrize(
    "cid_header,expected_cid",
    [
        (None, None),
        ("abc-123", "abc-123"),
    ],
)
def test_review_code_success_includes_correlation_id(client, cid_header, expected_cid):
    """POST /review with valid data returns analysis and includes correlation_id if provided."""
    headers = {}
    if cid_header:
        headers["X-Correlation-ID"] = cid_header
    data = {"content": "print('hello')", "language": "python"}
    resp = client.post("/review", json=data, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert "score" in body and isinstance(body["score"], (int, float))
    assert isinstance(body["issues"], list) and len(body["issues"]) >= 1
    assert "suggestions" in body and isinstance(body["suggestions"], list)
    assert "complexity_score" in body
    assert body.get("correlation_id") == expected_cid


def test_review_function_missing_field_returns_400(client):
    """POST /review/function without 'function_code' returns 400."""
    resp = client.post("/review/function", json={"content": "def f(): pass"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing 'function_code' field"


def test_review_function_success_returns_result(client):
    """POST /review/function with valid function returns reviewer result."""
    resp = client.post("/review/function", json={"function_code": "def f():\n    return 1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["valid"] is True
    assert isinstance(body["issues"], list)


def test_statistics_missing_body_returns_400(client):
    """POST /statistics without a body returns 400."""
    resp = client.post("/statistics")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


@pytest.mark.parametrize(
    "payload,expected_field",
    [
        ({}, "files"),
        ({"files": "not-a-list"}, "files"),
    ],
)
def test_statistics_validation_error_returns_422_and_records(client, payload, expected_field):
    """POST /statistics with invalid payload returns 422 and logs validation errors."""
    resp = client.post("/statistics", json=payload)
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "Validation failed"
    assert any(d["field"] == expected_field for d in body["details"])

    errs = client.get("/validation/errors").get_json()
    assert errs["total_errors"] >= 1
    assert any(e["field"] == expected_field for e in errs["errors"])


def test_statistics_success_includes_correlation_id(client):
    """POST /statistics with valid data returns aggregated stats and correlation_id if header set."""
    headers = {"X-Correlation-ID": "stats-456"}
    files = [
        {"content": "print('a')", "language": "python"},
        {"content": "x=1", "language": "python"},
    ]
    resp = client.post("/statistics", json={"files": files}, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_files"] == 2
    assert body["average_score"] == pytest.approx(88.0)
    assert body["total_issues"] == 10
    assert body["issues_by_severity"]["high"] == 2
    assert body["average_complexity"] == pytest.approx(2.2)
    assert body["total_suggestions"] == 6
    assert body["correlation_id"] == "stats-456"


def test_traces_list_and_get_trace_found_and_not_found(client):
    """GET /traces lists all traces; GET /traces/<id> returns traces for the given correlation id or 404."""
    # Prepopulate fake traces
    correlation_module.TRACES.extend(
        [
            {"correlation_id": "c-1", "event": "review_started"},
            {"correlation_id": "c-2", "event": "review_completed"},
            {"correlation_id": "c-1", "event": "statistics_generated"},
        ]
    )

    # List all traces
    list_resp = client.get("/traces")
    assert list_resp.status_code == 200
    all_traces = list_resp.get_json()
    assert all_traces["total_traces"] == 3
    assert isinstance(all_traces["traces"], list)
    assert len(all_traces["traces"]) == 3

    # Get for existing correlation id
    get_resp = client.get("/traces/c-1")
    assert get_resp.status_code == 200
    data = get_resp.get_json()
    assert data["correlation_id"] == "c-1"
    assert data["trace_count"] == 2
    assert all(t["correlation_id"] == "c-1" for t in data["traces"])

    # Not found
    nf_resp = client.get("/traces/does-not-exist")
    assert nf_resp.status_code == 404
    assert nf_resp.get_json()["error"] == "No traces found for correlation ID"


def test_validation_errors_list_and_delete(client):
    """GET /validation/errors returns accumulated errors; DELETE clears them."""
    # Generate some validation errors via endpoints
    client.post("/review", json={})
    client.post("/statistics", json={})

    resp = client.get("/validation/errors")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_errors"] >= 2
    assert isinstance(body["errors"], list)
    assert any(e["field"] == "content" for e in body["errors"])
    assert any(e["field"] == "files" for e in body["errors"])

    del_resp = client.delete("/validation/errors")
    assert del_resp.status_code == 200
    assert del_resp.get_json()["message"] == "Validation errors cleared"

    resp2 = client.get("/validation/errors")
    assert resp2.status_code == 200
    body2 = resp2.get_json()
    assert body2["total_errors"] == 0
    assert body2["errors"] == []