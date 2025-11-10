import sys
import types
import pytest
from unittest.mock import Mock

# ---- Create fake external modules before importing src.app ----

# Fake src.request_validator module
req_validator = types.ModuleType("src.request_validator")

class SimpleValidationError:
    def __init__(self, field, message, code=None):
        self.field = field
        self.message = message
        self.code = code or "invalid"

    def to_dict(self):
        return {"field": self.field, "message": self.message, "code": self.code}

req_validator.SimpleValidationError = SimpleValidationError
req_validator.VALIDATION_ERRORS = []

def validate_review_request(data):
    return []

def validate_statistics_request(data):
    return []

def sanitize_request_data(data):
    return data or {}

def get_validation_errors():
    return list(req_validator.VALIDATION_ERRORS)

def clear_validation_errors():
    req_validator.VALIDATION_ERRORS.clear()

req_validator.validate_review_request = validate_review_request
req_validator.validate_statistics_request = validate_statistics_request
req_validator.sanitize_request_data = sanitize_request_data
req_validator.get_validation_errors = get_validation_errors
req_validator.clear_validation_errors = clear_validation_errors

sys.modules["src.request_validator"] = req_validator

# Fake src.correlation_middleware module
corr_mw = types.ModuleType("src.correlation_middleware")
corr_mw.TRACES = {}

def get_traces(correlation_id):
    return list(corr_mw.TRACES.get(correlation_id, []))

def get_all_traces():
    all_items = []
    for lst in corr_mw.TRACES.values():
        all_items.extend(lst)
    return all_items

class CorrelationIDMiddleware:
    def __init__(self, app):
        from flask import request, g

        @app.before_request
        def _set_correlation_id():
            cid = request.headers.get("X-Correlation-ID", "cid-test")
            g.correlation_id = cid

        @app.after_request
        def _collect_trace(response):
            from flask import request, g
            cid = getattr(g, "correlation_id", None) or "cid-unknown"
            trace = {
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "correlation_id": cid,
            }
            corr_mw.TRACES.setdefault(cid, []).append(trace)
            return response

corr_mw.CorrelationIDMiddleware = CorrelationIDMiddleware
corr_mw.get_traces = get_traces
corr_mw.get_all_traces = get_all_traces

sys.modules["src.correlation_middleware"] = corr_mw

# Fake src.code_reviewer module
code_reviewer_mod = types.ModuleType("src.code_reviewer")

class Issue:
    def __init__(self, severity, line, message, suggestion):
        self.severity = severity
        self.line = line
        self.message = message
        self.suggestion = suggestion

class ReviewResult:
    def __init__(self, score=1.0, issues=None, suggestions=None, complexity_score=0.0):
        self.score = score
        self.issues = issues or []
        self.suggestions = suggestions or []
        self.complexity_score = complexity_score

class CodeReviewer:
    def review_code(self, content, language):
        return ReviewResult(score=0.5, issues=[], suggestions=[], complexity_score=1.0)

    def review_function(self, function_code):
        return {"status": "ok", "function_reviewed": True}

code_reviewer_mod.Issue = Issue
code_reviewer_mod.ReviewResult = ReviewResult
code_reviewer_mod.CodeReviewer = CodeReviewer

sys.modules["src.code_reviewer"] = code_reviewer_mod

# Fake src.statistics module
stats_mod = types.ModuleType("src.statistics")

class Stats:
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
        return Stats(total_files=len(files))

stats_mod.Stats = Stats
stats_mod.StatisticsAggregator = StatisticsAggregator

sys.modules["src.statistics"] = stats_mod

# ---- Import the app under test (must use the exact import) ----
from src.app import app, reviewer, statistics_aggregator  # noqa: E402
import src.app as app_module  # for monkeypatch targets


@pytest.fixture(scope="module")
def client():
    """Provide a Flask test client for the app."""
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_state():
    """Reset fake middleware traces and validation errors between tests."""
    corr_mw.TRACES.clear()
    req_validator.VALIDATION_ERRORS.clear()
    yield
    corr_mw.TRACES.clear()
    req_validator.VALIDATION_ERRORS.clear()


def test_health_check_ok(client):
    """GET /health returns service status information."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


@pytest.mark.parametrize(
    "endpoint, payload, expected_status, expected_error",
    [
        ("/review", None, 400, "Missing request body"),
        ("/statistics", None, 400, "Missing request body"),
    ],
)
def test_endpoints_missing_body_returns_400(client, endpoint, payload, expected_status, expected_error):
    """POST endpoints should return 400 when request body is missing."""
    resp = client.post(endpoint, json=payload)
    assert resp.status_code == expected_status
    data = resp.get_json()
    assert data["error"] == expected_error


def test_review_function_missing_field_returns_400(client):
    """POST /review/function returns 400 when 'function_code' is missing."""
    resp = client.post("/review/function", json={"not_function_code": "def f(): pass"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing 'function_code' field"


def test_review_code_validation_error_returns_422(client, monkeypatch):
    """POST /review returns 422 when validation fails with details."""
    class Err:
        def __init__(self, field, message):
            self.field = field
            self.message = message

        def to_dict(self):
            return {"field": self.field, "message": self.message}

    monkeypatch.setattr(app_module, "validate_review_request", lambda data: [Err("content", "is required")])

    resp = client.post("/review", json={"content": ""})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert isinstance(data["details"], list)
    assert data["details"][0]["field"] == "content"
    assert data["details"][0]["message"] == "is required"


def test_statistics_validation_error_returns_422(client, monkeypatch):
    """POST /statistics returns 422 when validation fails with details."""
    class Err:
        def __init__(self, field, message):
            self.field = field
            self.message = message

        def to_dict(self):
            return {"field": self.field, "message": self.message}

    monkeypatch.setattr(app_module, "validate_statistics_request", lambda data: [Err("files", "must be a non-empty list")])

    resp = client.post("/statistics", json={"files": []})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"][0]["field"] == "files"
    assert data["details"][0]["message"] == "must be a non-empty list"


def test_review_code_success_maps_fields_and_correlation_and_traces(client, monkeypatch):
    """POST /review maps reviewer result to response and includes correlation_id, traces are recorded."""
    # Prepare a fake review result
    issues = [
        code_reviewer_mod.Issue(severity="high", line=10, message="Bad practice", suggestion="Use context manager"),
        code_reviewer_mod.Issue(severity="low", line=2, message="Nit: spacing", suggestion="Remove trailing space"),
    ]

    class FakeResult:
        def __init__(self):
            self.score = 0.85
            self.issues = issues
            self.suggestions = ["Refactor function foo", "Add docstring to bar"]
            self.complexity_score = 5.3

    monkeypatch.setattr(reviewer, "review_code", lambda content, language: FakeResult())

    headers = {"X-Correlation-ID": "cid-123"}
    payload = {"content": "print('hello')", "language": "python"}
    resp = client.post("/review", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["score"] == 0.85
    assert data["complexity_score"] == 5.3
    assert data["correlation_id"] == "cid-123"
    assert isinstance(data["issues"], list)
    assert len(data["issues"]) == 2
    assert data["issues"][0]["severity"] == "high"
    assert data["issues"][0]["line"] == 10
    assert data["issues"][0]["message"] == "Bad practice"
    assert data["issues"][0]["suggestion"] == "Use context manager"

    # Traces recorded for this correlation id
    t_resp = client.get("/traces/cid-123")
    assert t_resp.status_code == 200
    t_data = t_resp.get_json()
    assert t_data["correlation_id"] == "cid-123"
    assert t_data["trace_count"] >= 1
    assert isinstance(t_data["traces"], list)
    assert any(tr["path"] == "/review" for tr in t_data["traces"])


def test_review_function_success_returns_backend_result(client, monkeypatch):
    """POST /review/function returns exactly what reviewer.review_function returns."""
    expected = {"ok": True, "count": 1, "note": "function analyzed"}
    monkeypatch.setattr(reviewer, "review_function", lambda function_code: expected)

    resp = client.post("/review/function", json={"function_code": "def f():\n    return 1\n"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == expected


def test_statistics_success_returns_fields_and_correlation(client, monkeypatch):
    """POST /statistics returns aggregated stats and includes correlation_id."""
    # Prepare a fake stats result
    stats_result = stats_mod.Stats(
        total_files=3,
        average_score=0.76,
        total_issues=12,
        issues_by_severity={"high": 3, "medium": 5, "low": 4},
        average_complexity=7.1,
        files_with_high_complexity=["a.py", "b.py"],
        total_suggestions=9,
    )

    monkeypatch.setattr(statistics_aggregator, "aggregate_reviews", lambda files: stats_result)

    headers = {"X-Correlation-ID": "cid-stats"}
    payload = {"files": [{"name": "a.py"}, {"name": "b.py"}, {"name": "c.py"}]}
    resp = client.post("/statistics", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["total_files"] == 3
    assert data["average_score"] == 0.76
    assert data["total_issues"] == 12
    assert data["issues_by_severity"] == {"high": 3, "medium": 5, "low": 4}
    assert data["average_complexity"] == 7.1
    assert data["files_with_high_complexity"] == ["a.py", "b.py"]
    assert data["total_suggestions"] == 9
    assert data["correlation_id"] == "cid-stats"


def test_get_trace_not_found_returns_404(client):
    """GET /traces/<id> returns 404 when correlation ID has no traces."""
    resp = client.get("/traces/does-not-exist")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["error"] == "No traces found for correlation ID"


def test_list_traces_endpoint_reports_totals(client):
    """GET /traces returns total count and traces list."""
    # Create some traces by making requests with two different correlation IDs
    client.get("/health", headers={"X-Correlation-ID": "cid-a"})
    client.get("/health", headers={"X-Correlation-ID": "cid-b"})
    client.get("/health", headers={"X-Correlation-ID": "cid-a"})

    resp = client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "total_traces" in data and "traces" in data
    assert data["total_traces"] == len(data["traces"])
    assert data["total_traces"] >= 3
    assert all("correlation_id" in t for t in data["traces"])


def test_validation_errors_list_and_delete(client):
    """GET /validation/errors returns accumulated errors; DELETE clears them."""
    # Pre-populate fake validation errors store
    req_validator.VALIDATION_ERRORS.extend(
        [
            {"field": "content", "message": "too short"},
            {"field": "files", "message": "empty"},
        ]
    )

    # List
    resp_list = client.get("/validation/errors")
    assert resp_list.status_code == 200
    data = resp_list.get_json()
    assert data["total_errors"] == 2
    assert len(data["errors"]) == 2

    # Delete
    resp_del = client.delete("/validation/errors")
    assert resp_del.status_code == 200
    msg = resp_del.get_json()
    assert msg["message"] == "Validation errors cleared"

    # List again is empty
    resp_list2 = client.get("/validation/errors")
    assert resp_list2.status_code == 200
    data2 = resp_list2.get_json()
    assert data2["total_errors"] == 0
    assert data2["errors"] == []


@pytest.mark.parametrize(
    "endpoint, payload, header_cid",
    [
        ("/review", {"content": "x", "language": "python"}, "cid-p-1"),
        ("/statistics", {"files": [{"name": "a"}]}, "cid-p-2"),
    ],
)
def test_endpoints_echo_correlation_id_when_header_present(client, monkeypatch, endpoint, payload, header_cid):
    """Endpoints include correlation_id from request header when present."""
    if endpoint == "/review":
        class FakeResult:
            def __init__(self):
                self.score = 1.0
                self.issues = []
                self.suggestions = []
                self.complexity_score = 0.0
        monkeypatch.setattr(reviewer, "review_code", lambda content, language: FakeResult())
    elif endpoint == "/statistics":
        res = stats_mod.Stats(total_files=1)
        monkeypatch.setattr(statistics_aggregator, "aggregate_reviews", lambda files: res)

    resp = client.post(endpoint, json=payload, headers={"X-Correlation-ID": header_cid})
    assert resp.status_code in (200, 201)
    body = resp.get_json()
    assert body["correlation_id"] == header_cid