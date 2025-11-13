import sys
import types
import pytest
from unittest.mock import Mock

@pytest.fixture
def app_context(monkeypatch):
    """
    Prepare stub modules for src.* dependencies, then import the Flask app and return
    a testing context with client and references to key components for patching.
    """
    # Create stub module for src.request_validator
    rv_mod = types.ModuleType("src.request_validator")

    class ValidationError:
        def __init__(self, field="field", message="invalid", code="invalid"):
            self.field = field
            self.message = message
            self.code = code

        def to_dict(self):
            return {"field": self.field, "message": self.message, "code": self.code}

    rv_mod.ValidationError = ValidationError
    rv_mod._validation_errors = []

    def validate_review_request(data):
        return []

    def validate_statistics_request(data):
        return []

    def sanitize_request_data(data):
        return data

    def get_validation_errors():
        return list(rv_mod._validation_errors)

    def clear_validation_errors():
        rv_mod._validation_errors.clear()

    rv_mod.validate_review_request = validate_review_request
    rv_mod.validate_statistics_request = validate_statistics_request
    rv_mod.sanitize_request_data = sanitize_request_data
    rv_mod.get_validation_errors = get_validation_errors
    rv_mod.clear_validation_errors = clear_validation_errors

    # Create stub module for src.code_reviewer
    cr_mod = types.ModuleType("src.code_reviewer")

    class Issue:
        def __init__(self, severity="low", line=1, message="ok", suggestion=None):
            self.severity = severity
            self.line = line
            self.message = message
            self.suggestion = suggestion

    class ReviewResult:
        def __init__(self):
            self.score = 85
            self.issues = [Issue(severity="medium", line=2, message="Minor issue", suggestion="Fix it")]
            self.suggestions = ["Improve variable names"]
            self.complexity_score = 3.2

    class CodeReviewer:
        def review_code(self, content, language):
            return ReviewResult()

        def review_function(self, function_code):
            return {"valid": True, "length": len(function_code or "")}

    cr_mod.CodeReviewer = CodeReviewer
    cr_mod.Issue = Issue
    cr_mod.ReviewResult = ReviewResult

    # Create stub module for src.statistics
    st_mod = types.ModuleType("src.statistics")

    class Stats:
        def __init__(self):
            self.total_files = 2
            self.average_score = 90.5
            self.total_issues = 3
            self.issues_by_severity = {"low": 1, "medium": 1, "high": 1}
            self.average_complexity = 4.5
            self.files_with_high_complexity = ["a.py"]
            self.total_suggestions = 5

    class StatisticsAggregator:
        def aggregate_reviews(self, files):
            return Stats()

    st_mod.StatisticsAggregator = StatisticsAggregator
    st_mod.Stats = Stats

    # Create stub module for src.test_coverage_analyzer
    tca_mod = types.ModuleType("src.test_coverage_analyzer")

    class ItemType:
        def __init__(self, value):
            self.value = value

    class CoverageItem:
        def __init__(self, name="func_a", type_val="function", line_start=1, line_end=5, complexity=1.0, test_count=0):
            self.name = name
            self.type = ItemType(type_val)
            self.line_start = line_start
            self.line_end = line_end
            self.complexity = complexity
            self.test_count = test_count

    class CoverageReport:
        def __init__(self):
            self.coverage_percentage = 80.1234
            self.total_functions = 2
            self.covered_functions = 1
            self.total_classes = 1
            self.covered_classes = 1
            self.total_methods = 0
            self.covered_methods = 0
            self.total_lines = 100
            self.covered_lines = 80
            self.branch_coverage = 75.0
            self.uncovered_items = [
                CoverageItem(name="func_b", type_val="function", line_start=10, line_end=20, complexity=2.5, test_count=0)
            ]
            self.high_complexity_items = [
                CoverageItem(name="ClassA", type_val="class", line_start=1, line_end=50, complexity=8.0, test_count=0)
            ]
            self.suggestions = ["Add tests for func_b"]
            self.function_coverage_map = {"func_a": {"covered": True}, "func_b": {"covered": False}}

    class TestCoverageAnalyzer:
        def analyze_coverage(self, source_code, test_code=None, executed_lines=None, executed_functions=None, executed_classes=None):
            return CoverageReport()

        def generate_coverage_report_summary(self, report):
            return {
                "summary": "Overall coverage",
                "metrics": {
                    "lines_total": report.total_lines,
                    "lines_covered": report.covered_lines,
                    "coverage_percent": round((report.covered_lines / max(1, report.total_lines)) * 100.0, 2),
                },
                "branch_coverage": report.branch_coverage,
                "suggestions": report.suggestions,
            }

    tca_mod.CoverageItem = CoverageItem
    tca_mod.TestCoverageAnalyzer = TestCoverageAnalyzer
    tca_mod.CoverageReport = CoverageReport
    tca_mod.ItemType = ItemType

    # Create stub module for src.correlation_middleware
    cm_mod = types.ModuleType("src.correlation_middleware")
    cm_mod.GLOBAL_TRACES = []
    cm_mod.TRACE_MAP = {}

    class CorrelationIDMiddleware:
        def __init__(self, app):
            self.app = app

    def get_traces(correlation_id):
        return cm_mod.TRACE_MAP.get(correlation_id, [])

    def get_all_traces():
        return list(cm_mod.GLOBAL_TRACES)

    cm_mod.CorrelationIDMiddleware = CorrelationIDMiddleware
    cm_mod.get_traces = get_traces
    cm_mod.get_all_traces = get_all_traces

    # Insert stub modules into sys.modules
    monkeypatch.setitem(sys.modules, "src.request_validator", rv_mod)
    monkeypatch.setitem(sys.modules, "src.code_reviewer", cr_mod)
    monkeypatch.setitem(sys.modules, "src.statistics", st_mod)
    monkeypatch.setitem(sys.modules, "src.test_coverage_analyzer", tca_mod)
    monkeypatch.setitem(sys.modules, "src.correlation_middleware", cm_mod)

    # Now import the app using the exact import signature
    from src.app import app as flask_app, reviewer, statistics_aggregator, coverage_analyzer

    app_module = sys.modules["src.app"]
    client = flask_app.test_client()

    ctx = {
        "client": client,
        "app_module": app_module,
        "reviewer": reviewer,
        "statistics_aggregator": statistics_aggregator,
        "coverage_analyzer": coverage_analyzer,
        "modules": {
            "request_validator": rv_mod,
            "code_reviewer": cr_mod,
            "statistics": st_mod,
            "test_coverage_analyzer": tca_mod,
            "correlation_middleware": cm_mod,
        },
    }
    return ctx


def test_health_check_ok(app_context):
    """Test /health returns service status"""
    client = app_context["client"]
    res = client.get("/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


@pytest.mark.parametrize("endpoint", [
    "/review",
    "/statistics",
    "/coverage/analyze",
    "/coverage/report",
])
def test_endpoints_missing_body_returns_400(app_context, endpoint):
    """Test endpoints that require a JSON body return 400 when body is missing"""
    client = app_context["client"]
    res = client.post(endpoint)
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Missing request body"


def test_review_code_validation_error(app_context, monkeypatch):
    """Test /review returns 422 with validation error details"""
    client = app_context["client"]
    app_module = app_context["app_module"]
    rv_mod = app_context["modules"]["request_validator"]

    def fake_validate(_data):
        return [rv_mod.ValidationError(field="content", message="missing")]
    monkeypatch.setattr(app_module, "validate_review_request", fake_validate)

    res = client.post("/review", json={"content": "print('x')", "language": "python"})
    assert res.status_code == 422
    data = res.get_json()
    assert data["error"] == "Validation failed"
    assert isinstance(data["details"], list)
    assert data["details"][0]["field"] == "content"
    assert data["details"][0]["message"] == "missing"


def test_review_code_success(app_context):
    """Test /review returns successful review payload"""
    client = app_context["client"]
    res = client.post("/review", json={"content": "print('hello')", "language": "python"})
    assert res.status_code == 200
    data = res.get_json()
    assert "score" in data
    assert "issues" in data and isinstance(data["issues"], list)
    assert "suggestions" in data
    assert "complexity_score" in data
    assert "correlation_id" in data


def test_review_function_missing_field(app_context):
    """Test /review/function returns 400 when 'function_code' is missing"""
    client = app_context["client"]
    res = client.post("/review/function", json={})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Missing 'function_code' field"


def test_review_function_success(app_context):
    """Test /review/function returns analysis result"""
    client = app_context["client"]
    res = client.post("/review/function", json={"function_code": "def foo():\n    return 1"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["valid"] is True
    assert data["length"] > 0


def test_statistics_validation_error(app_context, monkeypatch):
    """Test /statistics returns 422 on validation errors"""
    client = app_context["client"]
    app_module = app_context["app_module"]
    rv_mod = app_context["modules"]["request_validator"]

    def fake_validate(_data):
        return [rv_mod.ValidationError(field="files", message="invalid format")]
    monkeypatch.setattr(app_module, "validate_statistics_request", fake_validate)

    res = client.post("/statistics", json={"files": []})
    assert res.status_code == 422
    data = res.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"][0]["field"] == "files"
    assert data["details"][0]["message"] == "invalid format"


def test_statistics_success(app_context):
    """Test /statistics returns aggregated statistics"""
    client = app_context["client"]
    res = client.post("/statistics", json={"files": [{"path": "a.py", "content": "x"}]})
    assert res.status_code == 200
    data = res.get_json()
    assert data["total_files"] == 2
    assert isinstance(data["issues_by_severity"], dict)
    assert "average_complexity" in data
    assert "correlation_id" in data


def test_list_traces_returns_all(app_context):
    """Test /traces returns all traces with total count"""
    client = app_context["client"]
    cm_mod = app_context["modules"]["correlation_middleware"]
    cm_mod.GLOBAL_TRACES = ["t1", "t2", "t3"]

    res = client.get("/traces")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total_traces"] == 3
    assert data["traces"] == ["t1", "t2", "t3"]


def test_get_trace_found(app_context):
    """Test /traces/<correlation_id> returns trace details when found"""
    client = app_context["client"]
    cm_mod = app_context["modules"]["correlation_middleware"]
    cm_mod.TRACE_MAP["abc-123"] = [{"event": "start"}, {"event": "end"}]

    res = client.get("/traces/abc-123")
    assert res.status_code == 200
    data = res.get_json()
    assert data["correlation_id"] == "abc-123"
    assert data["trace_count"] == 2
    assert isinstance(data["traces"], list)
    assert data["traces"][0]["event"] == "start"


def test_get_trace_not_found(app_context):
    """Test /traces/<correlation_id> returns 404 when no traces exist"""
    client = app_context["client"]

    res = client.get("/traces/does-not-exist")
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"] == "No traces found for correlation ID"


def test_validation_errors_list_and_clear(app_context):
    """Test listing and clearing validation errors"""
    client = app_context["client"]
    rv_mod = app_context["modules"]["request_validator"]
    rv_mod._validation_errors[:] = [
        {"id": 1, "code": "E001", "message": "Error 1"},
        {"id": 2, "code": "E002", "message": "Error 2"},
    ]

    res = client.get("/validation/errors")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total_errors"] == 2
    assert len(data["errors"]) == 2

    res = client.delete("/validation/errors")
    assert res.status_code == 200
    data = res.get_json()
    assert data["message"] == "Validation errors cleared"

    res = client.get("/validation/errors")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total_errors"] == 0
    assert data["errors"] == []


def test_analyze_coverage_missing_source_code(app_context):
    """Test /coverage/analyze returns 400 when 'source_code' is missing"""
    client = app_context["client"]
    res = client.post("/coverage/analyze", json={"test_code": "test"})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Missing 'source_code' field"


def test_analyze_coverage_success(app_context):
    """Test /coverage/analyze returns coverage report summary"""
    client = app_context["client"]
    payload = {
        "source_code": "def a():\n    return 1\n",
        "test_code": "def test_a():\n    assert a() == 1\n",
        "executed_lines": [1, 2, 3],
        "executed_functions": ["a"],
        "executed_classes": [],
    }
    res = client.post("/coverage/analyze", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert "coverage_report" in data
    report = data["coverage_report"]
    assert "summary" in report
    assert "metrics" in report and "coverage_percent" in report["metrics"]
    assert "branch_coverage" in report
    assert isinstance(report["uncovered_items"], list)
    assert isinstance(report["high_complexity_items"], list)
    assert "suggestions" in report
    assert "function_coverage_map" in report
    assert "correlation_id" in data


def test_analyze_coverage_syntax_error(app_context, monkeypatch):
    """Test /coverage/analyze returns 400 on SyntaxError"""
    client = app_context["client"]
    analyzer = app_context["coverage_analyzer"]

    def raise_syntax_error(**kwargs):
        raise SyntaxError("bad syntax")
    monkeypatch.setattr(analyzer, "analyze_coverage", raise_syntax_error)

    res = client.post("/coverage/analyze", json={"source_code": "def bad(:\n pass\n"})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Invalid Python syntax in source code"
    assert "bad syntax" in data["details"]


def test_analyze_coverage_unexpected_error(app_context, monkeypatch):
    """Test /coverage/analyze returns 500 on unexpected exception"""
    client = app_context["client"]
    analyzer = app_context["coverage_analyzer"]

    def raise_error(**kwargs):
        raise Exception("boom")
    monkeypatch.setattr(analyzer, "analyze_coverage", raise_error)

    res = client.post("/coverage/analyze", json={"source_code": "def a():\n  pass\n"})
    assert res.status_code == 500
    data = res.get_json()
    assert data["error"] == "Failed to analyze coverage"
    assert "boom" in data["details"]


def test_generate_coverage_report_missing_source_code(app_context):
    """Test /coverage/report returns 400 when 'source_code' is missing"""
    client = app_context["client"]
    res = client.post("/coverage/report", json={"test_code": "x"})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Missing 'source_code' field"


def test_generate_coverage_report_success(app_context):
    """Test /coverage/report returns detailed coverage report"""
    client = app_context["client"]
    payload = {
        "source_code": "class A:\n    def m(self):\n        return 1\n",
        "executed_lines": [1, 2],
        "executed_functions": [],
        "executed_classes": [],
    }
    res = client.post("/coverage/report", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert "detailed_report" in data
    dr = data["detailed_report"]
    assert "overall_coverage_percentage" in dr
    assert "function_coverage" in dr
    assert "class_coverage" in dr
    assert "method_coverage" in dr
    assert "line_coverage" in dr
    assert "branch_coverage" in dr
    assert isinstance(dr["all_uncovered_items"], list)
    assert isinstance(dr["all_high_complexity_items"], list)
    assert "function_coverage_map" in dr
    assert "correlation_id" in data


def test_generate_coverage_report_syntax_error(app_context, monkeypatch):
    """Test /coverage/report returns 400 on SyntaxError"""
    client = app_context["client"]
    analyzer = app_context["coverage_analyzer"]

    def raise_syntax_error(**kwargs):
        raise SyntaxError("bad coverage")
    monkeypatch.setattr(analyzer, "analyze_coverage", raise_syntax_error)

    res = client.post("/coverage/report", json={"source_code": "def bad(:\n pass\n"})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Invalid Python syntax in source code"
    assert "bad coverage" in data["details"]


def test_generate_coverage_report_unexpected_error(app_context, monkeypatch):
    """Test /coverage/report returns 500 on unexpected exception"""
    client = app_context["client"]
    analyzer = app_context["coverage_analyzer"]

    def raise_error(**kwargs):
        raise Exception("gen error")
    monkeypatch.setattr(analyzer, "analyze_coverage", raise_error)

    res = client.post("/coverage/report", json={"source_code": "def a():\n  pass\n"})
    assert res.status_code == 500
    data = res.get_json()
    assert data["error"] == "Failed to generate coverage report"
    assert "gen error" in data["details"]