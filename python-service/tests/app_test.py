import pytest
from types import SimpleNamespace
from unittest.mock import Mock

import src.app as app_module
from src.app import app as flask_app


@pytest.fixture
def client():
    """Provide a Flask test client."""
    flask_app.testing = True
    with flask_app.test_client() as client:
        yield client


@pytest.fixture
def mock_validation(monkeypatch):
    """Mock validation and sanitization helpers."""
    validate_review = Mock(return_value=[])
    validate_stats = Mock(return_value=[])
    sanitize = Mock(side_effect=lambda d: d)
    get_errs = Mock(return_value=[])
    clear_errs = Mock()
    monkeypatch.setattr(app_module, "validate_review_request", validate_review)
    monkeypatch.setattr(app_module, "validate_statistics_request", validate_stats)
    monkeypatch.setattr(app_module, "sanitize_request_data", sanitize)
    monkeypatch.setattr(app_module, "get_validation_errors", get_errs)
    monkeypatch.setattr(app_module, "clear_validation_errors", clear_errs)
    return {
        "validate_review": validate_review,
        "validate_stats": validate_stats,
        "sanitize": sanitize,
        "get_errs": get_errs,
        "clear_errs": clear_errs,
    }


def test_health_check_ok(client):
    """GET /health returns service status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


@pytest.mark.parametrize(
    "payload,use_json",
    [
        (None, False),  # No body
        ({}, True),     # Empty JSON
    ],
)
def test_review_code_missing_body_or_empty_json_returns_400(client, payload, use_json):
    """POST /review returns 400 when body is missing or empty JSON."""
    if use_json:
        resp = client.post("/review", json=payload)
    else:
        resp = client.post("/review")
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data


def test_review_code_validation_error_returns_422(client, monkeypatch):
    """POST /review returns 422 when request validation fails."""
    class FakeValidationError:
        def __init__(self, code):
            self.code = code

        def to_dict(self):
            return {"code": self.code, "message": "invalid"}

    monkeypatch.setattr(
        app_module, "validate_review_request", Mock(return_value=[FakeValidationError("ERR1")])
    )

    resp = client.post("/review", json={"content": "x"})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert isinstance(data["details"], list)
    assert data["details"][0]["code"] == "ERR1"


def test_review_code_success(client, monkeypatch, mock_validation):
    """POST /review returns analysis result on success."""
    issue = SimpleNamespace(severity="high", line=1, message="Problem", suggestion="Fix it")
    result = SimpleNamespace(
        score=85,
        issues=[issue],
        suggestions=["Consider refactoring"],
        complexity_score=3.2,
    )

    reviewer_mock = Mock()
    reviewer_mock.review_code.return_value = result
    monkeypatch.setattr(app_module, "reviewer", reviewer_mock)

    payload = {"content": "def a(): pass", "language": "python"}
    resp = client.post("/review", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["score"] == 85
    assert data["complexity_score"] == 3.2
    assert data["issues"][0]["severity"] == "high"
    assert data["issues"][0]["line"] == 1
    assert data["issues"][0]["message"] == "Problem"
    assert data["issues"][0]["suggestion"] == "Fix it"
    assert "correlation_id" in data  # value may be None depending on middleware


@pytest.mark.parametrize(
    "payload,use_json",
    [
        (None, False),
        ({}, True),
    ],
)
def test_review_function_missing_field_returns_400(client, payload, use_json):
    """POST /review/function returns 400 when 'function_code' is missing."""
    if use_json:
        resp = client.post("/review/function", json=payload)
    else:
        resp = client.post("/review/function")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Missing 'function_code' field"


def test_review_function_success(client, monkeypatch):
    """POST /review/function returns reviewer output."""
    reviewer_mock = Mock()
    reviewer_mock.review_function.return_value = {"ok": True, "issues": 0}
    monkeypatch.setattr(app_module, "reviewer", reviewer_mock)

    resp = client.post("/review/function", json={"function_code": "def f(): pass"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"ok": True, "issues": 0}
    reviewer_mock.review_function.assert_called_once()


@pytest.mark.parametrize(
    "payload,use_json",
    [
        (None, False),
        ({}, True),
    ],
)
def test_statistics_missing_body_returns_400(client, payload, use_json):
    """POST /statistics returns 400 when body is missing."""
    if use_json:
        resp = client.post("/statistics", json=payload)
    else:
        resp = client.post("/statistics")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_statistics_validation_error_returns_422(client, monkeypatch):
    """POST /statistics returns 422 when request validation fails."""
    class FakeValidationError:
        def __init__(self, code):
            self.code = code

        def to_dict(self):
            return {"code": self.code, "message": "invalid stats"}

    monkeypatch.setattr(
        app_module, "validate_statistics_request", Mock(return_value=[FakeValidationError("S001")])
    )

    resp = client.post("/statistics", json={"files": []})
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"][0]["code"] == "S001"


def test_statistics_success(client, monkeypatch, mock_validation):
    """POST /statistics returns aggregated statistics on success."""
    stats_obj = SimpleNamespace(
        total_files=3,
        average_score=87.5,
        total_issues=10,
        issues_by_severity={"high": 2, "low": 8},
        average_complexity=4.2,
        files_with_high_complexity=["a.py"],
        total_suggestions=5,
    )
    aggregator_mock = Mock()
    aggregator_mock.aggregate_reviews.return_value = stats_obj
    monkeypatch.setattr(app_module, "statistics_aggregator", aggregator_mock)

    resp = client.post("/statistics", json={"files": [{"content": "x"}]})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_files"] == 3
    assert data["average_score"] == 87.5
    assert data["issues_by_severity"]["high"] == 2
    assert data["total_suggestions"] == 5
    assert "correlation_id" in data


def test_list_traces_success(client, monkeypatch):
    """GET /traces returns all traces and counts."""
    monkeypatch.setattr(app_module, "get_all_traces", Mock(return_value=[{"id": "t1"}, {"id": "t2"}]))

    resp = client.get("/traces")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_traces"] == 2
    assert data["traces"] == [{"id": "t1"}, {"id": "t2"}]


def test_get_trace_not_found_returns_404(client, monkeypatch):
    """GET /traces/<id> returns 404 when no traces exist for the correlation id."""
    monkeypatch.setattr(app_module, "get_traces", Mock(return_value=[]))

    resp = client.get("/traces/abc")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "No traces found for correlation ID"


def test_get_trace_success(client, monkeypatch):
    """GET /traces/<id> returns traces for the given correlation id."""
    traces = [{"msg": "a"}, {"msg": "b"}]
    monkeypatch.setattr(app_module, "get_traces", Mock(return_value=traces))

    resp = client.get("/traces/corr-1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["correlation_id"] == "corr-1"
    assert data["trace_count"] == 2
    assert data["traces"] == traces


def test_list_validation_errors_success(client, monkeypatch):
    """GET /validation/errors returns accumulated validation errors."""
    errors = [{"field": "code", "message": "missing"}]
    monkeypatch.setattr(app_module, "get_validation_errors", Mock(return_value=errors))

    resp = client.get("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_errors"] == 1
    assert data["errors"] == errors


def test_delete_validation_errors_success(client, monkeypatch):
    """DELETE /validation/errors clears validation errors."""
    clearer = Mock()
    monkeypatch.setattr(app_module, "clear_validation_errors", clearer)

    resp = client.delete("/validation/errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["message"] == "Validation errors cleared"
    clearer.assert_called_once()


@pytest.mark.parametrize(
    "payload,use_json",
    [
        (None, False),
        ({}, True),
    ],
)
def test_analyze_coverage_missing_body_returns_400(client, payload, use_json):
    """POST /coverage/analyze returns 400 when body is missing."""
    if use_json:
        resp = client.post("/coverage/analyze", json=payload)
    else:
        resp = client.post("/coverage/analyze")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_analyze_coverage_missing_source_code_returns_400(client):
    """POST /coverage/analyze returns 400 when source_code is missing."""
    resp = client.post("/coverage/analyze", json={"test_code": "x", "executed_lines": []})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing 'source_code' field"


def test_analyze_coverage_success_with_slicing_and_summary(client, monkeypatch):
    """POST /coverage/analyze returns coverage report with sliced items and summary."""
    # Prepare fake report
    def fake_item(i):
        return SimpleNamespace(
            name=f"func_{i}",
            type=SimpleNamespace(value="function"),
            line_start=i,
            line_end=i + 10,
            complexity=i % 5 + 1,
            test_count=i % 3,
        )

    uncovered = [fake_item(i) for i in range(25)]
    high_complexity = [SimpleNamespace(
        name=f"hc_{i}",
        type=SimpleNamespace(value="function"),
        line_start=i,
        line_end=i + 5,
        complexity=10 + i
    ) for i in range(12)]

    report = SimpleNamespace(
        uncovered_items=uncovered,
        high_complexity_items=high_complexity,
        function_coverage_map={"f": {"covered": True}},
    )

    analyzer_mock = Mock()
    analyzer_mock.analyze_coverage.return_value = report
    analyzer_mock.generate_coverage_report_summary.return_value = {
        "summary": {"overall": 90.0},
        "metrics": {"lines": {"covered": 90, "total": 100}},
        "branch_coverage": {"covered": 10, "total": 12},
        "suggestions": ["Add tests"],
    }
    monkeypatch.setattr(app_module, "coverage_analyzer", analyzer_mock)

    resp = client.post("/coverage/analyze", json={"source_code": "def a():\n    pass"})
    assert resp.status_code == 200
    data = resp.get_json()
    cov = data["coverage_report"]
    assert cov["summary"]["overall"] == 90.0
    assert cov["metrics"]["lines"]["total"] == 100
    assert isinstance(cov["branch_coverage"], dict)
    assert len(cov["uncovered_items"]) == 20  # sliced to 20
    assert len(cov["high_complexity_items"]) == 10  # sliced to 10
    assert cov["function_coverage_map"] == {"f": {"covered": True}}
    assert "correlation_id" in data


def test_analyze_coverage_syntax_error_returns_400(client, monkeypatch):
    """POST /coverage/analyze returns 400 on SyntaxError."""
    analyzer_mock = Mock()
    analyzer_mock.analyze_coverage.side_effect = SyntaxError("bad syntax")
    monkeypatch.setattr(app_module, "coverage_analyzer", analyzer_mock)

    resp = client.post("/coverage/analyze", json={"source_code": "def a(:"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Invalid Python syntax in source code"
    assert "details" in data


def test_analyze_coverage_generic_error_returns_500(client, monkeypatch):
    """POST /coverage/analyze returns 500 on unexpected errors."""
    analyzer_mock = Mock()
    analyzer_mock.analyze_coverage.side_effect = Exception("boom")
    monkeypatch.setattr(app_module, "coverage_analyzer", analyzer_mock)

    resp = client.post("/coverage/analyze", json={"source_code": "def a(): pass"})
    assert resp.status_code == 500
    data = resp.get_json()
    assert data["error"] == "Failed to analyze coverage"
    assert "boom" in data["details"]


@pytest.mark.parametrize(
    "payload,use_json",
    [
        (None, False),
        ({}, True),
    ],
)
def test_generate_coverage_report_missing_body_returns_400(client, payload, use_json):
    """POST /coverage/report returns 400 when body is missing."""
    if use_json:
        resp = client.post("/coverage/report", json=payload)
    else:
        resp = client.post("/coverage/report")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_generate_coverage_report_missing_source_code_returns_400(client):
    """POST /coverage/report returns 400 when source_code is missing."""
    resp = client.post("/coverage/report", json={"test_code": "x"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing 'source_code' field"


def test_generate_coverage_report_success(client, monkeypatch):
    """POST /coverage/report returns detailed coverage report."""
    # Create fake report with all required attributes
    report = SimpleNamespace(
        coverage_percentage=82.3456,
        total_functions=10,
        covered_functions=8,
        total_classes=5,
        covered_classes=3,
        total_methods=12,
        covered_methods=9,
        total_lines=200,
        covered_lines=160,
        branch_coverage={"covered": 20, "total": 25},
        uncovered_items=[
            SimpleNamespace(
                name="func_x",
                type=SimpleNamespace(value="function"),
                line_start=1,
                line_end=10,
                complexity=7,
                test_count=0,
            )
        ],
        high_complexity_items=[
            SimpleNamespace(
                name="func_y",
                type=SimpleNamespace(value="function"),
                line_start=20,
                line_end=40,
                complexity=12,
            )
        ],
        suggestions=["Improve tests"],
        function_coverage_map={"func_x": {"covered": False}},
    )

    analyzer_mock = Mock()
    analyzer_mock.analyze_coverage.return_value = report
    monkeypatch.setattr(app_module, "coverage_analyzer", analyzer_mock)

    resp = client.post("/coverage/report", json={"source_code": "def a(): pass"})
    assert resp.status_code == 200
    data = resp.get_json()
    detailed = data["detailed_report"]
    assert detailed["overall_coverage_percentage"] == round(82.3456, 2)
    assert detailed["function_coverage"]["total"] == 10
    assert detailed["function_coverage"]["covered"] == 8
    assert detailed["function_coverage"]["percentage"] == 80.0
    assert detailed["class_coverage"]["percentage"] == round((3 / 5) * 100, 2)
    assert detailed["method_coverage"]["percentage"] == round((9 / 12) * 100, 2)
    assert detailed["line_coverage"]["percentage"] == round((160 / 200) * 100, 2)
    assert detailed["branch_coverage"]["total"] == 25
    assert detailed["all_uncovered_items"][0]["name"] == "func_x"
    assert detailed["all_high_complexity_items"][0]["name"] == "func_y"
    assert detailed["suggestions"] == ["Improve tests"]
    assert detailed["function_coverage_map"] == {"func_x": {"covered": False}}
    assert "correlation_id" in data


def test_generate_coverage_report_syntax_error_returns_400(client, monkeypatch):
    """POST /coverage/report returns 400 on SyntaxError."""
    analyzer_mock = Mock()
    analyzer_mock.analyze_coverage.side_effect = SyntaxError("bad syntax")
    monkeypatch.setattr(app_module, "coverage_analyzer", analyzer_mock)

    resp = client.post("/coverage/report", json={"source_code": "def a(:"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Invalid Python syntax in source code"
    assert "details" in data


def test_generate_coverage_report_generic_error_returns_500(client, monkeypatch):
    """POST /coverage/report returns 500 on unexpected errors."""
    analyzer_mock = Mock()
    analyzer_mock.analyze_coverage.side_effect = Exception("crash")
    monkeypatch.setattr(app_module, "coverage_analyzer", analyzer_mock)

    resp = client.post("/coverage/report", json={"source_code": "def a(): pass"})
    assert resp.status_code == 500
    data = resp.get_json()
    assert data["error"] == "Failed to generate coverage report"
    assert "crash" in data["details"]