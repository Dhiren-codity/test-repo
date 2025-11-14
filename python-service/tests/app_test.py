import pytest
from unittest.mock import Mock
from types import SimpleNamespace

from src.app import app as flask_app


@pytest.fixture
def client():
    """Flask test client fixture."""
    with flask_app.test_client() as client:
        yield client


def test_health_check_ok(client):
    """Test health_check returns healthy status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


def test_review_code_missing_body_returns_400(client):
    """Test review_code returns 400 when request body is missing."""
    resp = client.post("/review")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


@pytest.mark.parametrize("error_count", [1, 2])
def test_review_code_validation_error_422(monkeypatch, client, error_count):
    """Test review_code returns 422 with validation error details."""
    class DummyValidationError:
        def __init__(self, i):
            self.i = i

        def to_dict(self):
            return {"field": f"field_{self.i}", "message": f"error_{self.i}"}

    def fake_validate_review_request(_data):
        return [DummyValidationError(i) for i in range(error_count)]

    monkeypatch.setattr("src.app.validate_review_request", fake_validate_review_request)

    resp = client.post("/review", json={"content": "print('hi')"})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert isinstance(data["details"], list)
    assert len(data["details"]) == error_count


def test_review_code_success_returns_review_result(monkeypatch, client):
    """Test review_code returns 200 with review result payload."""
    # Patch validation and sanitization
    monkeypatch.setattr("src.app.validate_review_request", lambda data: [])
    monkeypatch.setattr("src.app.sanitize_request_data", lambda data: data)

    # Prepare mock reviewer and result
    issues = [
        SimpleNamespace(severity="high", line=10, message="Use of eval", suggestion="Avoid using eval"),
        SimpleNamespace(severity="low", line=2, message="Trailing whitespace", suggestion="Remove trailing spaces"),
    ]
    review_result = SimpleNamespace(
        score=85,
        issues=issues,
        suggestions=["Use list comprehension", "Add docstrings"],
        complexity_score=3.2,
    )

    mock_reviewer = Mock()
    mock_reviewer.review_code.return_value = review_result
    monkeypatch.setattr("src.app", "reviewer", mock_reviewer)

    payload = {"content": "def foo(): pass", "language": "python"}
    resp = client.post("/review", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["score"] == 85
    assert data["complexity_score"] == 3.2
    assert data["suggestions"] == ["Use list comprehension", "Add docstrings"]
    assert "correlation_id" in data  # may be None if middleware not active

    assert isinstance(data["issues"], list)
    assert len(data["issues"]) == 2
    assert data["issues"][0]["severity"] == "high"
    assert data["issues"][0]["line"] == 10
    assert data["issues"][0]["message"] == "Use of eval"
    assert data["issues"][0]["suggestion"] == "Avoid using eval"

    mock_reviewer.review_code.assert_called_once_with("def foo(): pass", "python")


def test_review_function_missing_field_400(client):
    """Test review_function returns 400 when function_code is missing."""
    resp = client.post("/review/function", json={})
    assert resp.status_code == 400
    assert "Missing 'function_code' field" in resp.get_json()["error"]


def test_review_function_success_returns_json(monkeypatch, client):
    """Test review_function returns 200 with reviewer output."""
    mock_reviewer = Mock()
    expected = {"function": "foo", "findings": [{"severity": "info", "message": "ok"}]}
    mock_reviewer.review_function.return_value = expected
    monkeypatch.setattr("src.app", "reviewer", mock_reviewer)

    resp = client.post("/review/function", json={"function_code": "def foo(): pass"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == expected
    mock_reviewer.review_function.assert_called_once_with("def foo(): pass")


def test_get_statistics_missing_body_400(client):
    """Test get_statistics returns 400 when request body is missing."""
    resp = client.post("/statistics")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


@pytest.mark.parametrize("error_count", [1, 3])
def test_get_statistics_validation_error_422(monkeypatch, client, error_count):
    """Test get_statistics returns 422 with validation error details."""
    class DummyValidationError:
        def __init__(self, i):
            self.i = i

        def to_dict(self):
            return {"field": f"file_{self.i}", "message": f"invalid_{self.i}"}

    def fake_validate_statistics_request(_data):
        return [DummyValidationError(i) for i in range(error_count)]

    monkeypatch.setattr("src.app.validate_statistics_request", fake_validate_statistics_request)

    resp = client.post("/statistics", json={"files": []})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert isinstance(data["details"], list)
    assert len(data["details"]) == error_count


def test_get_statistics_success_returns_aggregated_stats(monkeypatch, client):
    """Test get_statistics returns 200 with aggregated statistics."""
    monkeypatch.setattr("src.app.validate_statistics_request", lambda data: [])
    monkeypatch.setattr("src.app.sanitize_request_data", lambda data: data)

    stats_obj = SimpleNamespace(
        total_files=5,
        average_score=88.2,
        total_issues=14,
        issues_by_severity={"high": 2, "medium": 5, "low": 7},
        average_complexity=3.7,
        files_with_high_complexity=["a.py", "b.py"],
        total_suggestions=9,
    )
    mock_stats_aggregator = Mock()
    mock_stats_aggregator.aggregate_reviews.return_value = stats_obj
    monkeypatch.setattr("src.app", "statistics_aggregator", mock_stats_aggregator)

    payload = {"files": [{"path": "a.py", "content": "print()"}]}
    resp = client.post("/statistics", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["total_files"] == 5
    assert data["average_score"] == 88.2
    assert data["total_issues"] == 14
    assert data["issues_by_severity"] == {"high": 2, "medium": 5, "low": 7}
    assert data["average_complexity"] == 3.7
    assert data["files_with_high_complexity"] == ["a.py", "b.py"]
    assert data["total_suggestions"] == 9
    assert "correlation_id" in data

    mock_stats_aggregator.aggregate_reviews.assert_called_once_with(payload["files"])


def test_list_traces_returns_all_traces(monkeypatch, client):
    """Test list_traces returns all traces and total count."""
    traces = [{"id": "t1"}, {"id": "t2"}]
    monkeypatch.setattr("src.app.get_all_traces", lambda: traces)

    resp = client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == 2
    assert data["traces"] == traces


def test_get_trace_not_found_404(monkeypatch, client):
    """Test get_trace returns 404 when no traces are found."""
    monkeypatch.setattr("src.app.get_traces", lambda cid: [])

    resp = client.get("/traces/abc123")
    assert resp.status_code == 404
    assert "No traces found" in resp.get_json()["error"]


def test_get_trace_success_200(monkeypatch, client):
    """Test get_trace returns trace details when found."""
    tlist = [{"level": "info", "msg": "started"}]
    monkeypatch.setattr("src.app.get_traces", lambda cid: tlist)

    correlation_id = "corr-1"
    resp = client.get(f"/traces/{correlation_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] == correlation_id
    assert data["trace_count"] == len(tlist)
    assert data["traces"] == tlist


def test_list_validation_errors_returns_errors(monkeypatch, client):
    """Test list_validation_errors returns errors and total count."""
    errors = [
        {"field": "content", "message": "too large"},
        {"field": "language", "message": "unsupported"},
    ]
    monkeypatch.setattr("src.app.get_validation_errors", lambda: errors)

    resp = client.get("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == 2
    assert data["errors"] == errors


def test_delete_validation_errors_clears_and_returns_message(monkeypatch, client):
    """Test delete_validation_errors clears stored errors."""
    called = {"val": False}

    def fake_clear():
        called["val"] = True

    monkeypatch.setattr("src.app.clear_validation_errors", fake_clear)

    resp = client.delete("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["message"] == "Validation errors cleared"
    assert called["val"] is True