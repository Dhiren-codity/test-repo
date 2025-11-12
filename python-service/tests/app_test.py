import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

# ----- Create stub modules for external dependencies before importing src.app -----
# Stub: src.code_reviewer
code_reviewer_stub = types.ModuleType("src.code_reviewer")


class StubCodeReviewer:
    def review_code(self, content, language):
        return SimpleNamespace(
            score=85,
            issues=[],
            suggestions=["Use type hints"],
            complexity_score=3.2,
        )

    def review_function(self, function_code):
        return {"status": "ok", "details": "Function reviewed"}


code_reviewer_stub.CodeReviewer = StubCodeReviewer

# Stub: src.statistics
statistics_stub = types.ModuleType("src.statistics")


class StubStatisticsAggregator:
    def aggregate_reviews(self, files):
        return SimpleNamespace(
            total_files=len(files),
            average_score=0.0,
            total_issues=0,
            issues_by_severity={},
            average_complexity=0.0,
            files_with_high_complexity=[],
            total_suggestions=0,
        )


statistics_stub.StatisticsAggregator = StubStatisticsAggregator

# Stub: src.correlation_middleware
correlation_middleware_stub = types.ModuleType("src.correlation_middleware")


class StubCorrelationIDMiddleware:
    def __init__(self, app):
        from flask import request, g

        @app.before_request
        def _set_correlation_id():
            cid = request.headers.get("X-Correlation-ID", "stub-correlation-id")
            g.correlation_id = cid


def stub_get_traces(correlation_id):
    return [{"step": "example", "msg": "trace"}] if correlation_id == "exists" else []


def stub_get_all_traces():
    return [{"correlation_id": "exists", "trace": "data"}]


correlation_middleware_stub.CorrelationIDMiddleware = StubCorrelationIDMiddleware
correlation_middleware_stub.get_traces = stub_get_traces
correlation_middleware_stub.get_all_traces = stub_get_all_traces

# Stub: src.request_validator
request_validator_stub = types.ModuleType("src.request_validator")
_VALIDATION_ERRORS_STORE = []


def stub_validate_review_request(data):
    return []


def stub_validate_statistics_request(data):
    return []


def stub_sanitize_request_data(data):
    return data


def stub_get_validation_errors():
    return list(_VALIDATION_ERRORS_STORE)


def stub_clear_validation_errors():
    _VALIDATION_ERRORS_STORE.clear()


request_validator_stub.validate_review_request = stub_validate_review_request
request_validator_stub.validate_statistics_request = stub_validate_statistics_request
request_validator_stub.sanitize_request_data = stub_sanitize_request_data
request_validator_stub.get_validation_errors = stub_get_validation_errors
request_validator_stub.clear_validation_errors = stub_clear_validation_errors

# Inject stubs into sys.modules
sys.modules["src.code_reviewer"] = code_reviewer_stub
sys.modules["src.statistics"] = statistics_stub
sys.modules["src.correlation_middleware"] = correlation_middleware_stub
sys.modules["src.request_validator"] = request_validator_stub


# ----- Fixtures -----
@pytest.fixture
def flask_app():
    """Provide the Flask app from src.app"""
    from src.app import app
    return app


@pytest.fixture
def client(flask_app):
    """Provide a Flask test client"""
    return flask_app.test_client()


# ----- Tests -----
def test_health_check_ok(client):
    """GET /health should return a healthy status with service name"""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "healthy", "service": "python-reviewer"}


@pytest.mark.parametrize(
    "payload,expected_status,expected_error",
    [
        (None, 400, "Missing request body"),
        ({}, 422, "Validation failed"),
    ],
)
def test_review_code_error_cases(client, payload, expected_status, expected_error):
    """POST /review should handle missing body and validation errors appropriately"""
    with patch("src.app.validate_review_request") as mock_validate:
        if payload is None:
            # The endpoint checks for not data before validation function is invoked.
            pass
        else:
            # Simulate validation errors for empty dict payload
            FakeErr = type("FakeErr", (), {"to_dict": lambda self: {"field": "content", "message": "required"}})
            mock_validate.return_value = [FakeErr()]
        res = client.post("/review", json=payload) if payload is not None else client.post("/review")
        assert res.status_code == expected_status
        data = res.get_json()
        assert "error" in data
        assert data["error"] == expected_error
        if expected_status == 422:
            assert "details" in data
            assert isinstance(data["details"], list)
            assert data["details"][0]["field"] == "content"


def test_review_code_happy_path_returns_review_and_correlation_id(client):
    """POST /review should return review result with correlation id and serialized issues"""
    issues = [
        SimpleNamespace(severity="high", line=10, message="Bad practice", suggestion="Refactor"),
        SimpleNamespace(severity="low", line=5, message="Nit", suggestion="Rename var"),
    ]
    review_result = SimpleNamespace(
        score=92,
        issues=issues,
        suggestions=["Consider using list comprehension"],
        complexity_score=4.5,
    )
    with patch("src.app.validate_review_request", return_value=[]), \
         patch("src.app.sanitize_request_data", side_effect=lambda d: d), \
         patch("src.app.reviewer") as mock_reviewer:
        mock_reviewer.review_code.return_value = review_result

        res = client.post(
            "/review",
            json={"content": "print('hello')", "language": "python"},
            headers={"X-Correlation-ID": "abc-123"},
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["score"] == 92
        assert data["complexity_score"] == 4.5
        assert data["suggestions"] == ["Consider using list comprehension"]
        assert data["correlation_id"] == "abc-123"
        assert isinstance(data["issues"], list)
        assert data["issues"][0] == {
            "severity": "high",
            "line": 10,
            "message": "Bad practice",
            "suggestion": "Refactor",
        }


@pytest.mark.parametrize(
    "payload,expected_status,expected_error",
    [
        (None, 400, "Missing 'function_code' field"),
        ({}, 400, "Missing 'function_code' field"),
    ],
)
def test_review_function_error_cases(client, payload, expected_status, expected_error):
    """POST /review/function should return 400 when function_code is missing"""
    res = client.post("/review/function", json=payload) if payload is not None else client.post("/review/function")
    assert res.status_code == expected_status
    assert res.get_json()["error"] == expected_error


def test_review_function_happy_path(client):
    """POST /review/function should return review data from reviewer"""
    with patch("src.app.reviewer") as mock_reviewer:
        mock_reviewer.review_function.return_value = {"status": "ok", "issues": ["x", "y"]}
        res = client.post("/review/function", json={"function_code": "def foo(): pass"})
        assert res.status_code == 200
        assert res.get_json() == {"status": "ok", "issues": ["x", "y"]}


def test_statistics_missing_body_returns_400(client):
    """POST /statistics should return 400 when body is missing"""
    res = client.post("/statistics")
    assert res.status_code == 400
    assert res.get_json()["error"] == "Missing request body"


def test_statistics_validation_error_returns_422(client):
    """POST /statistics should return 422 when validation fails"""
    FakeErr = type("FakeErr", (), {"to_dict": lambda self: {"field": "files", "message": "invalid"}})
    with patch("src.app.validate_statistics_request", return_value=[FakeErr()]):
        res = client.post("/statistics", json={})
        assert res.status_code == 422
        body = res.get_json()
        assert body["error"] == "Validation failed"
        assert isinstance(body["details"], list)
        assert body["details"][0]["field"] == "files"


def test_statistics_happy_path_includes_correlation_id_and_aggregates(client):
    """POST /statistics should return aggregated stats and correlation id"""
    stats_obj = SimpleNamespace(
        total_files=2,
        average_score=88.5,
        total_issues=4,
        issues_by_severity={"high": 1, "medium": 2, "low": 1},
        average_complexity=3.3,
        files_with_high_complexity=["a.py"],
        total_suggestions=5,
    )
    with patch("src.app.validate_statistics_request", return_value=[]), \
         patch("src.app.sanitize_request_data", side_effect=lambda d: d), \
         patch("src.app.statistics_aggregator") as mock_stats:
        mock_stats.aggregate_reviews.return_value = stats_obj
        res = client.post("/statistics", json={"files": [{"name": "a.py"}, {"name": "b.py"}]}, headers={"X-Correlation-ID": "cid-789"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["total_files"] == 2
        assert data["average_score"] == 88.5
        assert data["total_issues"] == 4
        assert data["issues_by_severity"] == {"high": 1, "medium": 2, "low": 1}
        assert data["average_complexity"] == 3.3
        assert data["files_with_high_complexity"] == ["a.py"]
        assert data["total_suggestions"] == 5
        assert data["correlation_id"] == "cid-789"


def test_list_traces_returns_all_traces(client):
    """GET /traces should return values from get_all_traces"""
    traces = [{"id": 1}, {"id": 2}]
    with patch("src.app.get_all_traces", return_value=traces):
        res = client.get("/traces")
        assert res.status_code == 200
        data = res.get_json()
        assert data["total_traces"] == 2
        assert data["traces"] == traces


def test_get_trace_not_found_returns_404(client):
    """GET /traces/<correlation_id> should 404 when no traces exist for ID"""
    with patch("src.app.get_traces", return_value=[]):
        res = client.get("/traces/unknown")
        assert res.status_code == 404
        assert res.get_json()["error"] == "No traces found for correlation ID"


def test_get_trace_found_returns_trace_data(client):
    """GET /traces/<correlation_id> should return traces and count when found"""
    traces = [{"evt": "a"}, {"evt": "b"}]
    with patch("src.app.get_traces", return_value=traces):
        res = client.get("/traces/exists")
        assert res.status_code == 200
        data = res.get_json()
        assert data["correlation_id"] == "exists"
        assert data["trace_count"] == 2
        assert data["traces"] == traces


def test_list_validation_errors_returns_store(client):
    """GET /validation/errors should return all validation errors"""
    sample_errors = [{"field": "content", "message": "required"}, {"field": "files", "message": "empty"}]
    with patch("src.app.get_validation_errors", return_value=sample_errors):
        res = client.get("/validation/errors")
        assert res.status_code == 200
        data = res.get_json()
        assert data["total_errors"] == 2
        assert data["errors"] == sample_errors


def test_delete_validation_errors_clears_store(client):
    """DELETE /validation/errors should invoke clear_validation_errors and return a message"""
    with patch("src.app.clear_validation_errors") as mock_clear:
        res = client.delete("/validation/errors")
        assert res.status_code == 200
        assert res.get_json()["message"] == "Validation errors cleared"
        mock_clear.assert_called_once()