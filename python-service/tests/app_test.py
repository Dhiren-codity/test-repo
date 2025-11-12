import sys
import types
from uuid import uuid4

# ----- Inject fakes for external dependencies before importing src.app -----

# Fake src.code_reviewer
code_reviewer_module = types.ModuleType("src.code_reviewer")


class FakeIssue:
    def __init__(self, severity="warning", line=1, message="Issue found", suggestion="Fix it"):
        self.severity = severity
        self.line = line
        self.message = message
        self.suggestion = suggestion


class FakeReviewResult:
    def __init__(self, score=100, issues=None, suggestions=None, complexity_score=1):
        self.score = score
        self.issues = issues or []
        self.suggestions = suggestions or []
        self.complexity_score = complexity_score


class CodeReviewer:
    def review_code(self, content, language="python"):
        # Very simple analysis: add issue if "TODO" in code
        issues = []
        if isinstance(content, str) and "TODO" in content:
            issues.append(FakeIssue(severity="warning", line=1, message="TODO found", suggestion="Remove TODO"))
        lines = content.count("\n") + 1 if isinstance(content, str) and content else 0
        score = max(0, 100 - len(issues) * 5)
        return FakeReviewResult(score=score, issues=issues, suggestions=["Consider refactoring"], complexity_score=lines)

    def review_function(self, function_code):
        # Return a dict that is JSON serializable
        return {"ok": True, "length": len(function_code or "")}


code_reviewer_module.CodeReviewer = CodeReviewer
code_reviewer_module.FakeIssue = FakeIssue
code_reviewer_module.FakeReviewResult = FakeReviewResult
sys.modules["src.code_reviewer"] = code_reviewer_module

# Fake src.statistics
statistics_module = types.ModuleType("src.statistics")


class StatsResult:
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
        self.issues_by_severity = issues_by_severity or {"info": 0, "warning": 0, "error": 0}
        self.average_complexity = average_complexity
        self.files_with_high_complexity = files_with_high_complexity or []
        self.total_suggestions = total_suggestions


class StatisticsAggregator:
    def aggregate_reviews(self, files):
        count = len(files or [])
        # Fake some numbers deterministically
        average_score = 90.0 if count else 0.0
        total_issues = count  # one per file
        issues_by_severity = {"info": 0, "warning": count, "error": 0}
        average_complexity = 2.0 if count else 0.0
        files_with_high_complexity = [i for i in range(count) if i % 2 == 0]
        total_suggestions = count * 2
        return StatsResult(
            total_files=count,
            average_score=average_score,
            total_issues=total_issues,
            issues_by_severity=issues_by_severity,
            average_complexity=average_complexity,
            files_with_high_complexity=files_with_high_complexity,
            total_suggestions=total_suggestions,
        )


statistics_module.StatisticsAggregator = StatisticsAggregator
statistics_module.StatsResult = StatsResult
sys.modules["src.statistics"] = statistics_module

# Fake src.correlation_middleware
correlation_middleware_module = types.ModuleType("src.correlation_middleware")

_TRACES = {}  # correlation_id -> list of trace dicts


def _flatten_traces():
    all_items = []
    for cid, items in _TRACES.items():
        for item in items:
            all_items.append(item)
    return all_items


def clear_traces():
    _TRACES.clear()


def get_traces(correlation_id):
    return list(_TRACES.get(correlation_id, []))


def get_all_traces():
    return _flatten_traces()


class CorrelationIDMiddleware:
    def __init__(self, app):
        from flask import g, request

        @app.before_request
        def _before():
            # assign provided header or generate one
            cid = request.headers.get("X-Correlation-ID") or f"corr-{uuid4()}"
            g.correlation_id = cid

        @app.after_request
        def _after(response):
            from flask import g, request as req
            cid = getattr(g, "correlation_id", None) or "unknown"
            rec = {
                "correlation_id": cid,
                "path": req.path,
                "method": req.method,
                "status_code": response.status_code,
            }
            _TRACES.setdefault(cid, []).append(rec)
            return response


correlation_middleware_module.CorrelationIDMiddleware = CorrelationIDMiddleware
correlation_middleware_module.get_traces = get_traces
correlation_middleware_module.get_all_traces = get_all_traces
correlation_middleware_module.clear_traces = clear_traces
sys.modules["src.correlation_middleware"] = correlation_middleware_module

# Fake src.request_validator
request_validator_module = types.ModuleType("src.request_validator")

_VALIDATION_ERRORS = []


class Error:
    def __init__(self, field, code, message):
        self.field = field
        self.code = code
        self.message = message

    def to_dict(self):
        return {"field": self.field, "code": self.code, "message": self.message}


def validate_review_request(data):
    # Ensure content is present and a non-empty string
    if not isinstance(data, dict) or "content" not in data or not isinstance(data.get("content"), str) or not data.get("content"):
        err = Error("content", "required", "Content is required and must be a non-empty string")
        _VALIDATION_ERRORS.append(err.to_dict())
        return [err]
    return []


def validate_statistics_request(data):
    if not isinstance(data, dict) or "files" not in data or not isinstance(data.get("files"), list):
        err = Error("files", "invalid", "Files must be a list")
        _VALIDATION_ERRORS.append(err.to_dict())
        return [err]
    return []


def sanitize_request_data(data):
    # No-op sanitize that returns a shallow copy
    return dict(data) if isinstance(data, dict) else data


def get_validation_errors():
    return list(_VALIDATION_ERRORS)


def clear_validation_errors():
    _VALIDATION_ERRORS.clear()


request_validator_module.validate_review_request = validate_review_request
request_validator_module.validate_statistics_request = validate_statistics_request
request_validator_module.sanitize_request_data = sanitize_request_data
request_validator_module.get_validation_errors = get_validation_errors
request_validator_module.clear_validation_errors = clear_validation_errors
request_validator_module.Error = Error
sys.modules["src.request_validator"] = request_validator_module

# ----- Now import the app under test -----
import pytest
from unittest.mock import Mock
from types import SimpleNamespace
from src.app import app


@pytest.fixture(autouse=True)
def reset_state():
    """Reset global state (traces, validation errors) before each test."""
    sys.modules["src.correlation_middleware"].clear_traces()
    sys.modules["src.request_validator"].clear_validation_errors()
    yield
    sys.modules["src.correlation_middleware"].clear_traces()
    sys.modules["src.request_validator"].clear_validation_errors()


@pytest.fixture
def client():
    """Provide a Flask test client."""
    with app.test_client() as c:
        yield c


def test_health_check_ok(client):
    """GET /health returns service status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"status": "healthy", "service": "python-reviewer"}


def test_review_code_missing_body_returns_400(client):
    """POST /review with no JSON body returns 400."""
    resp = client.post("/review")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


@pytest.mark.parametrize(
    "payload",
    [
        {},  # missing content
        {"content": ""},  # empty content
        {"content": None},  # non-string
        {"language": "python"},  # missing content
    ],
)
def test_review_code_validation_error_returns_422(client, payload):
    """POST /review with invalid payload returns 422 and details."""
    resp = client.post("/review", json=payload)
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert isinstance(data["details"], list)
    assert len(data["details"]) >= 1
    assert "field" in data["details"][0]


def test_review_code_success_with_correlation_id(client):
    """POST /review returns analysis and includes correlation_id from header."""
    headers = {"X-Correlation-ID": "abc-123"}
    payload = {"content": "print('hi')\n# TODO", "language": "python"}
    resp = client.post("/review", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "score" in data
    assert "issues" in data and isinstance(data["issues"], list)
    assert "suggestions" in data and isinstance(data["suggestions"], list)
    assert "complexity_score" in data
    assert data["correlation_id"] == "abc-123"


def test_review_code_uses_reviewer_and_shapes_response(client, monkeypatch):
    """POST /review delegates to reviewer.review_code and shapes the response."""
    # Prepare a mock reviewer
    mock_issue = SimpleNamespace(severity="error", line=5, message="Boom", suggestion="Fix boom")
    mock_result = SimpleNamespace(score=42, issues=[mock_issue], suggestions=["do X"], complexity_score=7)

    import src.app as app_module
    mock_reviewer = Mock()
    mock_reviewer.review_code.return_value = mock_result
    monkeypatch.setattr(app_module, "reviewer", mock_reviewer)

    payload = {"content": "valid code", "language": "python"}
    headers = {"X-Correlation-ID": "cid-999"}
    resp = client.post("/review", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()

    mock_reviewer.review_code.assert_called_once_with("valid code", "python")
    assert data["score"] == 42
    assert data["complexity_score"] == 7
    assert data["issues"] == [
        {
            "severity": "error",
            "line": 5,
            "message": "Boom",
            "suggestion": "Fix boom",
        }
    ]
    assert data["suggestions"] == ["do X"]
    assert data["correlation_id"] == "cid-999"


def test_review_function_missing_field_returns_400(client):
    """POST /review/function without function_code returns 400."""
    resp = client.post("/review/function", json={})
    assert resp.status_code == 400
    assert "Missing 'function_code' field" in resp.get_json()["error"]


def test_review_function_success(client):
    """POST /review/function returns reviewer response."""
    payload = {"function_code": "def foo():\n    return 1"}
    resp = client.post("/review/function", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["length"] == len(payload["function_code"])


def test_statistics_missing_body_returns_400(client):
    """POST /statistics without body returns 400."""
    resp = client.post("/statistics")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


@pytest.mark.parametrize(
    "payload",
    [
        {},  # missing files
        {"files": "not-a-list"},
        {"files": None},
    ],
)
def test_statistics_validation_error_returns_422(client, payload):
    """POST /statistics with invalid payload returns 422 and details."""
    resp = client.post("/statistics", json=payload)
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert isinstance(data["details"], list)
    assert len(data["details"]) >= 1
    assert data["details"][0]["field"] == "files"


def test_statistics_success_with_correlation_id(client):
    """POST /statistics returns aggregated stats and includes correlation_id."""
    headers = {"X-Correlation-ID": "stat-123"}
    payload = {
        "files": [
            {"content": "print(1)", "language": "python"},
            {"content": "pass", "language": "python"},
        ]
    }
    resp = client.post("/statistics", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_files"] == 2
    assert "average_score" in data
    assert "total_issues" in data
    assert "issues_by_severity" in data and isinstance(data["issues_by_severity"], dict)
    assert "average_complexity" in data
    assert "files_with_high_complexity" in data and isinstance(data["files_with_high_complexity"], list)
    assert "total_suggestions" in data
    assert data["correlation_id"] == "stat-123"


def test_list_traces_and_get_trace(client):
    """GET /traces lists traces; GET /traces/<id> retrieves specific correlation's traces."""
    # Generate traces
    client.get("/health", headers={"X-Correlation-ID": "t-1"})
    client.post("/review", json={"content": "print(1)"}, headers={"X-Correlation-ID": "t-2"})

    # List all traces
    resp_list = client.get("/traces")
    assert resp_list.status_code == 200
    data = resp_list.get_json()
    assert "total_traces" in data and data["total_traces"] >= 2
    assert "traces" in data and isinstance(data["traces"], list)
    assert any(t["correlation_id"] == "t-1" for t in data["traces"])

    # Get a specific trace
    resp_get = client.get("/traces/t-1")
    assert resp_get.status_code == 200
    data2 = resp_get.get_json()
    assert data2["correlation_id"] == "t-1"
    assert data2["trace_count"] >= 1
    assert isinstance(data2["traces"], list)

    # Unknown correlation
    resp_404 = client.get("/traces/unknown-id")
    assert resp_404.status_code == 404
    assert resp_404.get_json()["error"] == "No traces found for correlation ID"


def test_validation_errors_endpoints_flow(client):
    """Validation errors are listed and can be cleared."""
    # Trigger a validation error via /review
    resp_bad = client.post("/review", json={})
    assert resp_bad.status_code == 422

    # List validation errors
    resp_list = client.get("/validation/errors")
    assert resp_list.status_code == 200
    data = resp_list.get_json()
    assert "total_errors" in data and data["total_errors"] >= 1
    assert "errors" in data and isinstance(data["errors"], list)
    assert all(isinstance(e, dict) for e in data["errors"])

    # Clear validation errors
    resp_clear = client.delete("/validation/errors")
    assert resp_clear.status_code == 200
    assert resp_clear.get_json()["message"] == "Validation errors cleared"

    # Verify cleared
    resp_list2 = client.get("/validation/errors")
    assert resp_list2.status_code == 200
    data2 = resp_list2.get_json()
    assert data2["total_errors"] == 0
    assert data2["errors"] == []