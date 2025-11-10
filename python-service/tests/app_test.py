import sys
import types
import pytest
from flask.testing import FlaskClient


def _install_dummy_modules():
    """Install dummy src.* modules and flask_cors into sys.modules for testing."""
    # Dummy flask_cors
    m_cors = types.ModuleType("flask_cors")

    def CORS(app):
        return None

    m_cors.CORS = CORS
    sys.modules["flask_cors"] = m_cors

    # src.request_validator
    m_validator = types.ModuleType("src.request_validator")

    class ValidationError:
        def __init__(self, field, message, code="invalid"):
            self.field = field
            self.message = message
            self.code = code

        def to_dict(self):
            return {"field": self.field, "message": self.message, "code": self.code}

    _errors_store = []

    def validate_review_request(data):
        errs = []
        if data.get("invalid") is True:
            errs.append(ValidationError("content", "invalid content"))
        return errs

    def validate_statistics_request(data):
        errs = []
        if data.get("invalid") is True:
            errs.append(ValidationError("files", "invalid files"))
        return errs

    def sanitize_request_data(data):
        return data

    def get_validation_errors():
        return _errors_store

    def clear_validation_errors():
        _errors_store.clear()

    m_validator.ValidationError = ValidationError
    m_validator.validate_review_request = validate_review_request
    m_validator.validate_statistics_request = validate_statistics_request
    m_validator.sanitize_request_data = sanitize_request_data
    m_validator.get_validation_errors = get_validation_errors
    m_validator.clear_validation_errors = clear_validation_errors
    m_validator._errors_store = _errors_store
    sys.modules["src.request_validator"] = m_validator

    # src.correlation_middleware
    m_corr = types.ModuleType("src.correlation_middleware")
    _traces_by_id = {}

    def get_traces(cid):
        return _traces_by_id.get(cid, [])

    def get_all_traces():
        all_items = []
        for cid, items in _traces_by_id.items():
            for it in items:
                all_items.append({"correlation_id": cid, **it})
        return all_items

    class CorrelationIDMiddleware:
        def __init__(self, app):
            @app.before_request
            def _before():
                from flask import g, request
                cid = request.headers.get("X-Correlation-ID", "test-corr-id")
                g.correlation_id = cid
                _traces_by_id.setdefault(cid, []).append({"path": request.path, "method": request.method})

    m_corr.CorrelationIDMiddleware = CorrelationIDMiddleware
    m_corr.get_traces = get_traces
    m_corr.get_all_traces = get_all_traces
    m_corr._traces_by_id = _traces_by_id
    sys.modules["src.correlation_middleware"] = m_corr

    # src.code_reviewer
    m_reviewer = types.ModuleType("src.code_reviewer")

    class Issue:
        def __init__(self, severity="low", line=1, message="msg", suggestion="sug"):
            self.severity = severity
            self.line = line
            self.message = message
            self.suggestion = suggestion

    class ReviewResult:
        def __init__(self):
            self.score = 85
            self.issues = [Issue("low", 1, "use better name", "rename var")]
            self.suggestions = ["add docstring"]
            self.complexity_score = 3.2

    class CodeReviewer:
        def review_code(self, content, language):
            return ReviewResult()

        def review_function(self, function_code):
            return {"status": "ok", "chars": len(function_code)}

    m_reviewer.CodeReviewer = CodeReviewer
    m_reviewer.Issue = Issue
    m_reviewer.ReviewResult = ReviewResult
    sys.modules["src.code_reviewer"] = m_reviewer

    # src.statistics
    m_stats = types.ModuleType("src.statistics")

    class Stats:
        def __init__(self):
            self.total_files = 2
            self.average_score = 90.5
            self.total_issues = 7
            self.issues_by_severity = {"low": 5, "high": 2}
            self.average_complexity = 2.8
            self.files_with_high_complexity = ["a.py"]
            self.total_suggestions = 3

    class StatisticsAggregator:
        def aggregate_reviews(self, files):
            return Stats()

    m_stats.StatisticsAggregator = StatisticsAggregator
    m_stats.Stats = Stats
    sys.modules["src.statistics"] = m_stats

    # src.test_coverage_analyzer
    import enum

    m_cov = types.ModuleType("src.test_coverage_analyzer")

    class ItemType(enum.Enum):
        FUNCTION = "function"
        CLASS = "class"
        METHOD = "method"

    class ReportItem:
        def __init__(self, name, type_, line_start, line_end, complexity, test_count=0):
            self.name = name
            self.type = type_
            self.line_start = line_start
            self.line_end = line_end
            self.complexity = complexity
            self.test_count = test_count

    class Report:
        def __init__(self):
            self.coverage_percentage = 83.3333
            self.total_functions = 10
            self.covered_functions = 8
            self.total_classes = 3
            self.covered_classes = 2
            self.total_methods = 5
            self.covered_methods = 4
            self.total_lines = 100
            self.covered_lines = 80
            self.branch_coverage = {"total": 10, "covered": 8}
            self.uncovered_items = [
                ReportItem("f1", ItemType.FUNCTION, 1, 5, 4, 0),
                ReportItem("C1", ItemType.CLASS, 10, 50, 7, 1),
            ]
            self.high_complexity_items = [
                ReportItem("f2", ItemType.FUNCTION, 60, 90, 12, 2),
            ]
            self.suggestions = ["add more tests"]
            self.function_coverage_map = {"f1": 0.0, "f2": 50.0}

    class TestCoverageAnalyzer:
        def analyze_coverage(
            self,
            source_code,
            test_code=None,
            executed_lines=None,
            executed_functions=None,
            executed_classes=None,
        ):
            if "syntaxerror" in source_code:
                raise SyntaxError("bad syntax")
            if "explode" in source_code:
                raise Exception("boom")
            return Report()

        def generate_coverage_report_summary(self, report):
            return {
                "summary": {"lines": "ok"},
                "metrics": {"overall": 80.0},
                "branch_coverage": {"total": 10, "covered": 8},
                "suggestions": ["write tests for uncovered functions"],
            }

    m_cov.TestCoverageAnalyzer = TestCoverageAnalyzer
    m_cov.ItemType = ItemType
    m_cov.ReportItem = ReportItem
    m_cov.Report = Report
    sys.modules["src.test_coverage_analyzer"] = m_cov

    return {
        "request_validator": m_validator,
        "correlation_middleware": m_corr,
        "code_reviewer": m_reviewer,
        "statistics": m_stats,
        "test_coverage_analyzer": m_cov,
    }


@pytest.fixture
def setup_app():
    """Create a fresh Flask app and test client with dummy modules installed."""
    # Remove any prior imports of src.app to ensure a clean import
    sys.modules.pop("src.app", None)

    modules = _install_dummy_modules()

    from src.app import app as flask_app  # exact import path required

    client: FlaskClient = flask_app.test_client()

    return {"app": flask_app, "client": client, "modules": modules}


@pytest.fixture
def client(setup_app):
    """Provide Flask test client."""
    return setup_app["client"]


@pytest.fixture
def req_validator(setup_app):
    """Provide access to the dummy request_validator module for manipulating stored errors."""
    return setup_app["modules"]["request_validator"]


@pytest.fixture
def corr_module(setup_app):
    """Provide access to the dummy correlation middleware module for traces inspection."""
    return setup_app["modules"]["correlation_middleware"]


def test_health_check_ok(client):
    """GET /health returns healthy status."""
    r = client.get("/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "python-reviewer"


@pytest.mark.parametrize(
    "endpoint,expected_error",
    [
        ("/review", "Missing request body"),
        ("/statistics", "Missing request body"),
        ("/coverage/analyze", "Missing request body"),
        ("/coverage/report", "Missing request body"),
    ],
)
def test_endpoints_missing_body(client, endpoint, expected_error):
    """POST endpoints return 400 on missing body."""
    resp = client.post(endpoint)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == expected_error


def test_review_code_validation_error(client):
    """POST /review returns 422 with validation errors when validator fails."""
    payload = {"content": "print('x')", "language": "python", "invalid": True}
    r = client.post("/review", json=payload)
    assert r.status_code == 422
    data = r.get_json()
    assert data["error"] == "Validation failed"
    assert isinstance(data["details"], list)
    assert data["details"][0]["field"] == "content"


def test_review_code_success_default_and_correlation_id(client):
    """POST /review returns analysis result and correlation id."""
    payload = {"content": "def x():\n    pass", "language": "python"}
    r = client.post("/review", json=payload, headers={"X-Correlation-ID": "abc123"})
    assert r.status_code == 200
    data = r.get_json()
    assert "score" in data and isinstance(data["score"], (int, float))
    assert "issues" in data and isinstance(data["issues"], list)
    assert "suggestions" in data and isinstance(data["suggestions"], list)
    assert "complexity_score" in data
    assert data["correlation_id"] == "abc123"
    assert {"severity", "line", "message", "suggestion"}.issubset(data["issues"][0].keys())


def test_review_function_missing_field(client):
    """POST /review/function returns 400 when function_code missing."""
    r = client.post("/review/function", json={})
    assert r.status_code == 400
    assert r.get_json()["error"] == "Missing 'function_code' field"


def test_review_function_success(client):
    """POST /review/function returns reviewer output."""
    r = client.post("/review/function", json={"function_code": "def x():\n    return 1"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "ok"
    assert data["chars"] > 0


def test_statistics_validation_error(client):
    """POST /statistics returns 422 with validation errors."""
    r = client.post("/statistics", json={"invalid": True})
    assert r.status_code == 422
    data = r.get_json()
    assert data["error"] == "Validation failed"
    assert data["details"][0]["field"] == "files"


def test_statistics_success(client):
    """POST /statistics returns aggregated stats and correlation id."""
    r = client.post("/statistics", json={"files": ["a.py", "b.py"]}, headers={"X-Correlation-ID": "stat-1"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["total_files"] == 2
    assert data["average_score"] == 90.5
    assert data["total_issues"] == 7
    assert data["issues_by_severity"]["low"] == 5
    assert data["average_complexity"] == 2.8
    assert data["files_with_high_complexity"] == ["a.py"]
    assert data["total_suggestions"] == 3
    assert data["correlation_id"] == "stat-1"


def test_traces_list_and_get_trace_found(client):
    """GET /traces and /traces/<cid> return recorded traces."""
    # Make a couple of requests with a specific correlation id
    headers = {"X-Correlation-ID": "trace-xyz"}
    client.get("/health", headers=headers)
    client.post("/review", json={"content": "print(1)", "language": "python"}, headers=headers)

    # List all traces
    r = client.get("/traces")
    assert r.status_code == 200
    data = r.get_json()
    assert "total_traces" in data and data["total_traces"] >= 2
    assert isinstance(data["traces"], list)
    assert any(t["correlation_id"] == "trace-xyz" for t in data["traces"])

    # Get specific correlation id traces
    r2 = client.get("/traces/trace-xyz")
    assert r2.status_code == 200
    d2 = r2.get_json()
    assert d2["correlation_id"] == "trace-xyz"
    assert d2["trace_count"] >= 2
    assert any(tr["path"] == "/health" for tr in d2["traces"])


def test_get_trace_not_found(client):
    """GET /traces/<cid> returns 404 for unknown id."""
    r = client.get("/traces/unknown-id-123")
    assert r.status_code == 404
    assert r.get_json()["error"] == "No traces found for correlation ID"


def test_validation_errors_list_and_delete(client, req_validator):
    """GET and DELETE /validation/errors reflect internal store changes."""
    # Initially empty
    r0 = client.get("/validation/errors")
    assert r0.status_code == 200
    assert r0.get_json()["total_errors"] == 0

    # Add errors via module store
    req_validator.get_validation_errors().extend(
        [{"field": "name", "message": "required"}, {"field": "age", "message": "too low"}]
    )
    r = client.get("/validation/errors")
    assert r.status_code == 200
    data = r.get_json()
    assert data["total_errors"] == 2
    assert isinstance(data["errors"], list)

    # Clear errors
    d = client.delete("/validation/errors")
    assert d.status_code == 200
    assert d.get_json()["message"] == "Validation errors cleared"

    r2 = client.get("/validation/errors")
    assert r2.get_json()["total_errors"] == 0


@pytest.mark.parametrize(
    "endpoint",
    ["/coverage/analyze", "/coverage/report"],
)
def test_coverage_missing_source_code(client, endpoint):
    """POST coverage endpoints return 400 when source_code missing."""
    r = client.post(endpoint, json={"test_code": "pass"})
    assert r.status_code == 400
    assert r.get_json()["error"] == "Missing 'source_code' field"


def test_coverage_analyze_success(client):
    """POST /coverage/analyze returns summarized coverage report."""
    payload = {
        "source_code": "def x():\n    return 1",
        "test_code": "def test_x(): assert x()==1",
        "executed_lines": [1, 2],
        "executed_functions": ["x"],
        "executed_classes": [],
    }
    r = client.post("/coverage/analyze", json=payload, headers={"X-Correlation-ID": "cov-123"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["correlation_id"] == "cov-123"
    cov = data["coverage_report"]
    assert "summary" in cov and "metrics" in cov and "branch_coverage" in cov
    assert "uncovered_items" in cov and "high_complexity_items" in cov
    assert isinstance(cov["uncovered_items"], list) and len(cov["uncovered_items"]) >= 1
    assert cov["uncovered_items"][0]["type"] in ("function", "class", "method")
    assert "function_coverage_map" in cov


def test_coverage_analyze_syntax_error(client):
    """POST /coverage/analyze returns 400 on SyntaxError."""
    payload = {"source_code": "syntaxerror", "executed_lines": [], "executed_functions": [], "executed_classes": []}
    r = client.post("/coverage/analyze", json=payload)
    assert r.status_code == 400
    assert r.get_json()["error"] == "Invalid Python syntax in source code"


def test_coverage_analyze_exception(client):
    """POST /coverage/analyze returns 500 on generic exception."""
    payload = {"source_code": "explode", "executed_lines": [], "executed_functions": [], "executed_classes": []}
    r = client.post("/coverage/analyze", json=payload)
    assert r.status_code == 500
    assert r.get_json()["error"] == "Failed to analyze coverage"


def test_coverage_report_success(client):
    """POST /coverage/report returns detailed report with computed percentages."""
    payload = {
        "source_code": "def y():\n    return 2",
        "test_code": "def test_y(): assert y()==2",
        "executed_lines": [1, 2, 3],
        "executed_functions": ["y"],
        "executed_classes": [],
    }
    r = client.post("/coverage/report", json=payload, headers={"X-Correlation-ID": "covrep-1"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["correlation_id"] == "covrep-1"
    rep = data["detailed_report"]
    assert rep["overall_coverage_percentage"] == 83.33
    assert rep["function_coverage"]["total"] == 10
    assert rep["function_coverage"]["covered"] == 8
    assert rep["function_coverage"]["percentage"] == 80.0
    assert rep["class_coverage"]["total"] == 3
    assert rep["class_coverage"]["covered"] == 2
    assert rep["class_coverage"]["percentage"] == 66.67
    assert rep["method_coverage"]["percentage"] == 80.0
    assert rep["line_coverage"]["percentage"] == 80.0
    assert isinstance(rep["all_uncovered_items"], list) and len(rep["all_uncovered_items"]) >= 1
    assert isinstance(rep["all_high_complexity_items"], list) and len(rep["all_high_complexity_items"]) >= 1
    assert "suggestions" in rep and "function_coverage_map" in rep


def test_coverage_report_syntax_error(client):
    """POST /coverage/report returns 400 on SyntaxError."""
    payload = {"source_code": "syntaxerror"}
    r = client.post("/coverage/report", json=payload)
    assert r.status_code == 400
    assert r.get_json()["error"] == "Invalid Python syntax in source code"


def test_coverage_report_exception(client):
    """POST /coverage/report returns 500 on generic exception."""
    payload = {"source_code": "explode"}
    r = client.post("/coverage/report", json=payload)
    assert r.status_code == 500
    assert r.get_json()["error"] == "Failed to generate coverage report"