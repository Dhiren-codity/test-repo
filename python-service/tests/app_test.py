import sys
import types
from typing import List, Dict, Any
import pytest
from unittest.mock import Mock
import importlib

# ---- Build fake dependency modules before importing src.app ----

# Fake src.code_reviewer
code_reviewer_mod = types.ModuleType("src.code_reviewer")


class _FakeIssue:
    def __init__(self, severity="low", line=1, message="msg", suggestion="sug"):
        self.severity = severity
        self.line = line
        self.message = message
        self.suggestion = suggestion


class _FakeReviewResult:
    def __init__(self, score=85, issues=None, suggestions=None, complexity_score=1.0):
        self.score = score
        self.issues = issues if issues is not None else []
        self.suggestions = suggestions if suggestions is not None else []
        self.complexity_score = complexity_score


class CodeReviewer:
    def review_code(self, content: str, language: str) -> _FakeReviewResult:
        return _FakeReviewResult()

    def review_function(self, function_code: str) -> Dict[str, Any]:
        return {"ok": True}


code_reviewer_mod.CodeReviewer = CodeReviewer
code_reviewer_mod._FakeIssue = _FakeIssue
code_reviewer_mod._FakeReviewResult = _FakeReviewResult
sys.modules["src.code_reviewer"] = code_reviewer_mod

# Fake src.statistics
statistics_mod = types.ModuleType("src.statistics")


class _FakeStats:
    def __init__(
        self,
        total_files=1,
        average_score=90.0,
        total_issues=0,
        issues_by_severity=None,
        average_complexity=1.0,
        files_with_high_complexity=None,
        total_suggestions=0,
    ):
        self.total_files = total_files
        self.average_score = average_score
        self.total_issues = total_issues
        self.issues_by_severity = issues_by_severity or {"low": 0}
        self.average_complexity = average_complexity
        self.files_with_high_complexity = files_with_high_complexity or []
        self.total_suggestions = total_suggestions


class StatisticsAggregator:
    def aggregate_reviews(self, files: List[Dict[str, Any]]) -> _FakeStats:
        return _FakeStats()


statistics_mod._FakeStats = _FakeStats
statistics_mod.StatisticsAggregator = StatisticsAggregator
sys.modules["src.statistics"] = statistics_mod

# Fake src.test_coverage_analyzer
coverage_mod = types.ModuleType("src.test_coverage_analyzer")


class _EnumType:
    def __init__(self, value: str):
        self.value = value


class _Item:
    def __init__(self, name="f", type_value="function", line_start=1, line_end=2, complexity=1, test_count=0):
        self.name = name
        self.type = _EnumType(type_value)
        self.line_start = line_start
        self.line_end = line_end
        self.complexity = complexity
        self.test_count = test_count


class _FakeCoverageReport:
    def __init__(self):
        self.uncovered_items = []
        self.high_complexity_items = []
        self.coverage_percentage = 0.0
        self.total_functions = 0
        self.covered_functions = 0
        self.total_classes = 0
        self.covered_classes = 0
        self.total_methods = 0
        self.covered_methods = 0
        self.total_lines = 0
        self.covered_lines = 0
        self.branch_coverage = {"taken": 0, "total": 0, "percentage": 0.0}
        self.suggestions = []
        self.function_coverage_map = {}


class TestCoverageAnalyzer:
    def analyze_coverage(self, **kwargs) -> _FakeCoverageReport:
        return _FakeCoverageReport()

    def generate_coverage_report_summary(self, report: _FakeCoverageReport) -> Dict[str, Any]:
        return {
            "summary": {},
            "metrics": {},
            "branch_coverage": {},
            "suggestions": [],
        }


coverage_mod._Item = _Item
coverage_mod._FakeCoverageReport = _FakeCoverageReport
coverage_mod.TestCoverageAnalyzer = TestCoverageAnalyzer
sys.modules["src.test_coverage_analyzer"] = coverage_mod

# Fake src.correlation_middleware
corr_mod = types.ModuleType("src.correlation_middleware")


class CorrelationIDMiddleware:
    def __init__(self, app):
        self.app = app


def get_traces(correlation_id: str):
    return []


def get_all_traces():
    return []


corr_mod.CorrelationIDMiddleware = CorrelationIDMiddleware
corr_mod.get_traces = get_traces
corr_mod.get_all_traces = get_all_traces
sys.modules["src.correlation_middleware"] = corr_mod

# Fake src.request_validator
reqval_mod = types.ModuleType("src.request_validator")
_req_errors: List[Dict[str, Any]] = []


def validate_review_request(data: Dict[str, Any]):
    return []


def validate_statistics_request(data: Dict[str, Any]):
    return []


def sanitize_request_data(data: Dict[str, Any]):
    return data


class _ValidationError:
    def __init__(self, msg: str, field: str = "field"):
        self.msg = msg
        self.field = field

    def to_dict(self):
        return {"message": self.msg, "field": self.field}


def get_validation_errors():
    return list(_req_errors)


def clear_validation_errors():
    _req_errors.clear()


reqval_mod.validate_review_request = validate_review_request
reqval_mod.validate_statistics_request = validate_statistics_request
reqval_mod.sanitize_request_data = sanitize_request_data
reqval_mod.get_validation_errors = get_validation_errors
reqval_mod.clear_validation_errors = clear_validation_errors
reqval_mod._ValidationError = _ValidationError
reqval_mod._req_errors = _req_errors
sys.modules["src.request_validator"] = reqval_mod

# ---- Now import the Flask app ----
from src.app import app as _flask_app  # noqa: E402


@pytest.fixture(scope="session")
def app_module():
    """Return the imported src.app module for patching."""
    return importlib.import_module("src.app")


@pytest.fixture
def client(app_module):
    """Return a Flask test client."""
    with app_module.app.test_client() as c:
        yield c


# Ensure requirement's exact import statement is used at least once in tests.
from src.app import app as _app_imported  # noqa: F401


def test_health_check_ok(client):
    """GET /health should return service health."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "healthy"
    assert body["service"] == "python-reviewer"


def test_review_code_missing_body(client):
    """POST /review without body returns 400."""
    resp = client.post("/review")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_review_code_validation_failed(client, app_module):
    """POST /review with validation errors returns 422 and details."""
    class Err:
        def to_dict(self):
            return {"field": "content", "message": "required"}

    # Patch validator to return one error
    app_module.validate_review_request = lambda data: [Err()]

    resp = client.post("/review", json={"content": "", "language": "python"})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "Validation failed"
    assert isinstance(body["details"], list)
    assert body["details"][0]["field"] == "content"


def test_review_code_happy_path(client, app_module):
    """POST /review returns structured review data with correlation id field."""
    fake_issue = code_reviewer_mod._FakeIssue(severity="high", line=10, message="msg", suggestion="fix")
    fake_result = code_reviewer_mod._FakeReviewResult(
        score=95,
        issues=[fake_issue],
        suggestions=["use xyz"],
        complexity_score=2.5,
    )
    app_module.sanitize_request_data = lambda data: data
    app_module.reviewer = Mock()
    app_module.reviewer.review_code.return_value = fake_result

    payload = {"content": "print(1)", "language": "python"}
    resp = client.post("/review", json=payload)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["score"] == 95
    assert body["issues"][0]["severity"] == "high"
    assert body["suggestions"] == ["use xyz"]
    assert body["complexity_score"] == 2.5
    assert "correlation_id" in body


def test_review_function_missing_field(client):
    """POST /review/function without required 'function_code' field returns 400."""
    resp = client.post("/review/function", json={"not_function_code": "def f(): pass"})
    assert resp.status_code == 400
    assert "Missing 'function_code' field" in resp.get_json()["error"]


def test_review_function_happy_path(client, app_module):
    """POST /review/function returns reviewer result."""
    app_module.reviewer = Mock()
    app_module.reviewer.review_function.return_value = {"ok": True, "name": "f"}
    resp = client.post("/review/function", json={"function_code": "def f(): pass"})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_statistics_missing_body(client):
    """POST /statistics without body returns 400."""
    resp = client.post("/statistics")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_statistics_validation_failed(client, app_module):
    """POST /statistics with validation errors returns 422."""
    class Err:
        def to_dict(self):
            return {"field": "files", "message": "invalid"}

    app_module.validate_statistics_request = lambda data: [Err()]
    resp = client.post("/statistics", json={"files": "not a list"})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "Validation failed"
    assert body["details"][0]["field"] == "files"


def test_statistics_happy_path(client, app_module):
    """POST /statistics returns aggregated review stats and correlation id."""
    app_module.validate_statistics_request = lambda data: []
    app_module.sanitize_request_data = lambda data: data
    fake_stats = statistics_mod._FakeStats(
        total_files=3,
        average_score=88.5,
        total_issues=7,
        issues_by_severity={"low": 3, "high": 4},
        average_complexity=2.1,
        files_with_high_complexity=["a.py"],
        total_suggestions=5,
    )
    app_module.statistics_aggregator = Mock()
    app_module.statistics_aggregator.aggregate_reviews.return_value = fake_stats

    resp = client.post("/statistics", json={"files": [{"name": "a.py"}]})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_files"] == 3
    assert body["average_score"] == 88.5
    assert body["total_issues"] == 7
    assert body["issues_by_severity"]["high"] == 4
    assert body["average_complexity"] == 2.1
    assert body["files_with_high_complexity"] == ["a.py"]
    assert body["total_suggestions"] == 5
    assert "correlation_id" in body


def test_traces_list(client, app_module):
    """GET /traces returns all traces and count."""
    traces = [{"id": "t1", "name": "op"}, {"id": "t2", "name": "op2"}]
    app_module.get_all_traces = lambda: traces

    resp = client.get("/traces")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_traces"] == 2
    assert body["traces"] == traces


def test_get_trace_not_found(client, app_module):
    """GET /traces/<id> returns 404 when not found."""
    app_module.get_traces = lambda cid: []
    resp = client.get("/traces/unknown")
    assert resp.status_code == 404
    assert "No traces found" in resp.get_json()["error"]


def test_get_trace_happy_path(client, app_module):
    """GET /traces/<id> returns trace list and count."""
    trcs = [{"step": 1}, {"step": 2}]
    app_module.get_traces = lambda cid: trcs
    resp = client.get("/traces/abc123")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["correlation_id"] == "abc123"
    assert body["trace_count"] == 2
    assert body["traces"] == trcs


def test_validation_errors_list_and_delete(client, app_module):
    """GET then DELETE /validation/errors behaves as expected."""
    # Patch get_validation_errors to return preset list, then empty after delete
    errors_store = [{"field": "x", "message": "bad"}]

    def _get():
        return list(errors_store)

    def _clear():
        errors_store.clear()

    app_module.get_validation_errors = _get
    app_module.clear_validation_errors = _clear

    resp = client.get("/validation/errors")
    assert resp.status_code == 200
    assert resp.get_json()["total_errors"] == 1

    resp = client.delete("/validation/errors")
    assert resp.status_code == 200
    assert resp.get_json()["message"] == "Validation errors cleared"

    resp = client.get("/validation/errors")
    assert resp.status_code == 200
    assert resp.get_json()["total_errors"] == 0
    assert resp.get_json()["errors"] == []


def test_analyze_coverage_missing_body(client):
    """POST /coverage/analyze without body returns 400."""
    resp = client.post("/coverage/analyze")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_analyze_coverage_missing_source_code(client):
    """POST /coverage/analyze without source_code returns 400."""
    resp = client.post("/coverage/analyze", json={"test_code": "..."})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing 'source_code' field"


def test_analyze_coverage_happy_path(client, app_module):
    """POST /coverage/analyze returns summarized coverage report."""
    # Build fake report and summary
    item1 = coverage_mod._Item(name="f1", type_value="function", line_start=1, line_end=5, complexity=3, test_count=1)
    item2 = coverage_mod._Item(name="C.m", type_value="method", line_start=10, line_end=15, complexity=5, test_count=0)
    fake_report = coverage_mod._FakeCoverageReport()
    fake_report.uncovered_items = [item1, item2]
    fake_report.high_complexity_items = [item2]
    fake_report.function_coverage_map = {"f1": {"covered": False}}

    fake_summary = {
        "summary": {"overall": 80.0},
        "metrics": {"lines": {"covered": 8, "total": 10}},
        "branch_coverage": {"percentage": 50.0},
        "suggestions": ["add tests"],
    }

    app_module.coverage_analyzer = Mock()
    app_module.coverage_analyzer.analyze_coverage.return_value = fake_report
    app_module.coverage_analyzer.generate_coverage_report_summary.return_value = fake_summary

    payload = {
        "source_code": "def f():\n  pass",
        "test_code": "def test_f(): pass",
        "executed_lines": [1, 2],
        "executed_functions": ["f"],
        "executed_classes": [],
    }
    resp = client.post("/coverage/analyze", json=payload)
    assert resp.status_code == 200
    body = resp.get_json()
    cov = body["coverage_report"]
    assert cov["summary"] == fake_summary["summary"]
    assert cov["metrics"] == fake_summary["metrics"]
    assert cov["branch_coverage"] == fake_summary["branch_coverage"]
    assert cov["suggestions"] == ["add tests"]
    assert cov["function_coverage_map"] == {"f1": {"covered": False}}
    assert cov["uncovered_items"][0]["name"] == "f1"
    assert cov["high_complexity_items"][0]["name"] == "C.m"
    assert "correlation_id" in body

    # Check that sets were passed to analyze_coverage
    args, kwargs = app_module.coverage_analyzer.analyze_coverage.call_args
    assert isinstance(kwargs["executed_lines"], set)
    assert isinstance(kwargs["executed_functions"], set)
    assert isinstance(kwargs["executed_classes"], set)


def test_analyze_coverage_syntax_error(client, app_module):
    """POST /coverage/analyze returns 400 on SyntaxError."""
    app_module.coverage_analyzer = Mock()
    app_module.coverage_analyzer.analyze_coverage.side_effect = SyntaxError("bad syntax")
    resp = client.post("/coverage/analyze", json={"source_code": "def :"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "Invalid Python syntax in source code"
    assert "bad syntax" in body["details"]


def test_analyze_coverage_server_error(client, app_module):
    """POST /coverage/analyze returns 500 on unhandled exception."""
    app_module.coverage_analyzer = Mock()
    app_module.coverage_analyzer.analyze_coverage.side_effect = Exception("boom")
    resp = client.post("/coverage/analyze", json={"source_code": "print(1)"})
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["error"] == "Failed to analyze coverage"
    assert "boom" in body["details"]


def test_generate_coverage_report_missing_body(client):
    """POST /coverage/report without body returns 400."""
    resp = client.post("/coverage/report")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_generate_coverage_report_missing_source_code(client):
    """POST /coverage/report without source_code returns 400."""
    resp = client.post("/coverage/report", json={"test_code": "..."})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing 'source_code' field"


@pytest.mark.parametrize(
    "totals,expected_percents",
    [
        ({"func": (10, 7), "class": (4, 2), "method": (8, 6), "line": (100, 80)},
         {"func": 70.0, "class": 50.0, "method": 75.0, "line": 80.0}),
        ({"func": (0, 0), "class": (0, 0), "method": (0, 0), "line": (0, 0)},
         {"func": 0.0, "class": 0.0, "method": 0.0, "line": 0.0}),
    ],
)
def test_generate_coverage_report_happy_path(client, app_module, totals, expected_percents):
    """POST /coverage/report returns detailed coverage report with computed percentages."""
    report = coverage_mod._FakeCoverageReport()
    report.total_functions, report.covered_functions = totals["func"]
    report.total_classes, report.covered_classes = totals["class"]
    report.total_methods, report.covered_methods = totals["method"]
    report.total_lines, report.covered_lines = totals["line"]
    report.branch_coverage = {"percentage": 42.0}
    report.coverage_percentage = 66.666
    item = coverage_mod._Item(name="f", type_value="function", line_start=1, line_end=2, complexity=3, test_count=0)
    report.uncovered_items = [item]
    report.high_complexity_items = [item]
    report.suggestions = ["cover more"]
    report.function_coverage_map = {"f": {"covered": False}}

    app_module.coverage_analyzer = Mock()
    app_module.coverage_analyzer.analyze_coverage.return_value = report

    payload = {
        "source_code": "def f(): pass",
        "test_code": "def test_f(): pass",
        "executed_lines": [],
        "executed_functions": [],
        "executed_classes": [],
    }
    resp = client.post("/coverage/report", json=payload)
    assert resp.status_code == 200
    body = resp.get_json()
    det = body["detailed_report"]
    assert det["overall_coverage_percentage"] == round(report.coverage_percentage, 2)
    assert det["function_coverage"]["total"] == report.total_functions
    assert det["function_coverage"]["covered"] == report.covered_functions
    assert det["function_coverage"]["percentage"] == expected_percents["func"]
    assert det["class_coverage"]["percentage"] == expected_percents["class"]
    assert det["method_coverage"]["percentage"] == expected_percents["method"]
    assert det["line_coverage"]["percentage"] == expected_percents["line"]
    assert det["branch_coverage"] == {"percentage": 42.0}
    assert det["all_uncovered_items"][0]["name"] == "f"
    assert det["all_high_complexity_items"][0]["name"] == "f"
    assert det["suggestions"] == ["cover more"]
    assert det["function_coverage_map"] == {"f": {"covered": False}}
    assert "correlation_id" in body


def test_generate_coverage_report_syntax_error(client, app_module):
    """POST /coverage/report returns 400 on SyntaxError."""
    app_module.coverage_analyzer = Mock()
    app_module.coverage_analyzer.analyze_coverage.side_effect = SyntaxError("bad")
    resp = client.post("/coverage/report", json={"source_code": "def :"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "Invalid Python syntax in source code"
    assert "bad" in body["details"]


def test_generate_coverage_report_server_error(client, app_module):
    """POST /coverage/report returns 500 on unhandled exception."""
    app_module.coverage_analyzer = Mock()
    app_module.coverage_analyzer.analyze_coverage.side_effect = Exception("oops")
    resp = client.post("/coverage/report", json={"source_code": "print(1)"})
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["error"] == "Failed to generate coverage report"
    assert "oops" in body["details"]