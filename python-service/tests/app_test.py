import os
import sys
import types
import pathlib
import importlib.util
import pytest
from unittest.mock import Mock

# ----------------------------
# Stub external modules before importing the Flask app
# ----------------------------

def _install_stub_modules():
    # Create base 'src' package
    src_pkg = types.ModuleType("src")
    sys.modules["src"] = src_pkg

    # flask_cors CORS stub
    flask_cors_mod = types.ModuleType("flask_cors")
    class _CORS:
        def __init__(self, app, *args, **kwargs):
            # no-op
            self.app = app
    flask_cors_mod.CORS = _CORS
    sys.modules["flask_cors"] = flask_cors_mod

    # src.code_reviewer stub
    code_reviewer_mod = types.ModuleType("src.code_reviewer")
    class _Issue:
        def __init__(self, severity, line, message, suggestion):
            self.severity = severity
            self.line = line
            self.message = message
            self.suggestion = suggestion

    class _ReviewResult:
        def __init__(self, score=85.5, issues=None, suggestions=None, complexity_score=3.2):
            self.score = score
            self.issues = issues or []
            self.suggestions = suggestions or ["Use better naming"]
            self.complexity_score = complexity_score

    class CodeReviewer:
        def review_code(self, content, language):
            issues = []
            if content and "bad" in content:
                issues.append(_Issue("warning", 1, "Found 'bad' pattern", "Avoid using 'bad'"))
            return _ReviewResult(score=88.0, issues=issues, suggestions=["Consider refactoring"], complexity_score=2.7)

        def review_function(self, function_code):
            # For simplicity, just return a dict
            return {"ok": True, "length": len(function_code or "")}

    code_reviewer_mod.CodeReviewer = CodeReviewer
    sys.modules["src.code_reviewer"] = code_reviewer_mod

    # src.statistics stub
    statistics_mod = types.ModuleType("src.statistics")
    class _Stats:
        def __init__(self, total_files, average_score, total_issues, issues_by_severity,
                     average_complexity, files_with_high_complexity, total_suggestions):
            self.total_files = total_files
            self.average_score = average_score
            self.total_issues = total_issues
            self.issues_by_severity = issues_by_severity
            self.average_complexity = average_complexity
            self.files_with_high_complexity = files_with_high_complexity
            self.total_suggestions = total_suggestions

    class StatisticsAggregator:
        def aggregate_reviews(self, files):
            total_files = len(files or [])
            return _Stats(
                total_files=total_files,
                average_score=90.0,
                total_issues=5 * total_files if total_files else 0,
                issues_by_severity={"warning": 3, "error": 2} if total_files else {},
                average_complexity=2.5,
                files_with_high_complexity=["file1.py"] if total_files else [],
                total_suggestions=4 * total_files if total_files else 0,
            )

    statistics_mod.StatisticsAggregator = StatisticsAggregator
    sys.modules["src.statistics"] = statistics_mod

    # src.test_coverage_analyzer stub
    tca_mod = types.ModuleType("src.test_coverage_analyzer")
    class _DummyType:
        def __init__(self, value):
            self.value = value

    class _Item:
        def __init__(self, name, type_value, line_start, line_end, complexity, test_count=0):
            self.name = name
            self.type = _DummyType(type_value)
            self.line_start = line_start
            self.line_end = line_end
            self.complexity = complexity
            self.test_count = test_count

    class _Report:
        def __init__(self):
            self.uncovered_items = []
            self.high_complexity_items = []
            self.function_coverage_map = {"foo": {"covered": False}}
            self.coverage_percentage = 76.54321
            self.total_functions = 10
            self.covered_functions = 7
            self.total_methods = 20
            self.covered_methods = 10
            self.total_classes = 2
            self.covered_classes = 1
            self.total_lines = 100
            self.covered_lines = 80
            self.branch_coverage = {"total": 10, "covered": 5, "percentage": 50.0}
            self.suggestions = ["Add tests for edge cases"]

    class TestCoverageAnalyzer:
        def analyze_coverage(self, source_code, test_code=None,
                             executed_lines=None, executed_functions=None, executed_classes=None):
            if not source_code:
                raise ValueError("source_code required")
            if "SYNTAX_ERROR" in source_code:
                raise SyntaxError("invalid syntax")

            report = _Report()
            # Create 25 uncovered items to test truncation
            report.uncovered_items = [
                _Item(f"func{i}", "function", i, i+2, complexity=1.0 + i/10.0, test_count=0)
                for i in range(1, 26)
            ]
            # Create 12 high complexity items
            report.high_complexity_items = [
                _Item(f"high{i}", "function", i*3, i*3+5, complexity=5.0 + i)
                for i in range(1, 13)
            ]
            return report

        def generate_coverage_report_summary(self, report):
            return {
                "summary": "Overall coverage report",
                "metrics": {
                    "coverage_percentage": round(report.coverage_percentage, 2),
                    "functions_total": report.total_functions,
                },
                "branch_coverage": report.branch_coverage,
                "suggestions": report.suggestions,
            }

    tca_mod.TestCoverageAnalyzer = TestCoverageAnalyzer
    sys.modules["src.test_coverage_analyzer"] = tca_mod

    # src.correlation_middleware stub
    corr_mod = types.ModuleType("src.correlation_middleware")
    from flask import g, request
    class CorrelationIDMiddleware:
        def __init__(self, app):
            @app.before_request
            def _attach_correlation_id():
                cid = request.headers.get("X-Correlation-ID", "test-correlation-id")
                setattr(g, "correlation_id", cid)
    _TRACES_STORE = {}

    def get_traces(correlation_id):
        return _TRACES_STORE.get(correlation_id, [])

    def get_all_traces():
        # return a summary list for all traces
        return [{"correlation_id": cid, "trace_count": len(events)}
                for cid, events in _TRACES_STORE.items()]

    corr_mod.CorrelationIDMiddleware = CorrelationIDMiddleware
    corr_mod.get_traces = get_traces
    corr_mod.get_all_traces = get_all_traces
    corr_mod._TRACES_STORE = _TRACES_STORE
    sys.modules["src.correlation_middleware"] = corr_mod

    # src.request_validator stub
    reqval_mod = types.ModuleType("src.request_validator")

    class _ValidationError:
        def __init__(self, field=None, message="invalid"):
            self.field = field
            self.message = message
        def to_dict(self):
            return {"field": self.field, "message": self.message}

    _VALIDATION_ERRORS_STORE = []

    def validate_review_request(data):
        return []

    def validate_statistics_request(data):
        return []

    def sanitize_request_data(data):
        return data

    def get_validation_errors():
        return list(_VALIDATION_ERRORS_STORE)

    def clear_validation_errors():
        _VALIDATION_ERRORS_STORE.clear()

    reqval_mod.validate_review_request = validate_review_request
    reqval_mod.validate_statistics_request = validate_statistics_request
    reqval_mod.sanitize_request_data = sanitize_request_data
    reqval_mod.get_validation_errors = get_validation_errors
    reqval_mod.clear_validation_errors = clear_validation_errors
    reqval_mod._ValidationError = _ValidationError
    reqval_mod._VALIDATION_ERRORS_STORE = _VALIDATION_ERRORS_STORE
    sys.modules["src.request_validator"] = reqval_mod

    # Attach submodules to src package
    setattr(src_pkg, "code_reviewer", code_reviewer_mod)
    setattr(src_pkg, "statistics", statistics_mod)
    setattr(src_pkg, "test_coverage_analyzer", tca_mod)
    setattr(src_pkg, "correlation_middleware", corr_mod)
    setattr(src_pkg, "request_validator", reqval_mod)


def _load_app_module():
    base_dir = pathlib.Path(__file__).resolve().parent
    candidates = [
        base_dir / "python-service" / "src" / "app.py",
        base_dir / "src" / "app.py",
    ]
    for path in candidates:
        if path.exists():
            spec = importlib.util.spec_from_file_location("app_under_test", str(path))
            mod = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError("Could not locate app.py. Checked 'python-service/src/app.py' and 'src/app.py' relative to test file.")


# ----------------------------
# Pytest fixtures
# ----------------------------

@pytest.fixture(scope="session")
def app_module():
    """Load the Flask app module with stubbed external dependencies."""
    _install_stub_modules()
    return _load_app_module()

@pytest.fixture()
def client(app_module):
    """Flask test client for the app."""
    return app_module.app.test_client()

@pytest.fixture()
def stubs():
    """Provide access to stub modules for manipulation within tests."""
    return {
        "corr": sys.modules["src.correlation_middleware"],
        "reqval": sys.modules["src.request_validator"],
    }


# ----------------------------
# Tests
# ----------------------------

def test_health_check_ok(client):
    """GET /health should return service status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "healthy"
    assert body["service"] == "python-reviewer"


def test_review_code_missing_request_body(client):
    """POST /review without JSON should return 400."""
    resp = client.post("/review")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_review_code_validation_error_returns_422(client, app_module):
    """POST /review should return 422 with details when validation fails."""
    def fake_validate(data):
        class E:
            def to_dict(self):
                return {"field": "content", "message": "required"}
        return [E()]
    # Patch the imported function in app module
    app_module.validate_review_request = fake_validate

    resp = client.post("/review", json={"content": "", "language": "python"})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "Validation failed"
    assert isinstance(body["details"], list)
    assert body["details"][0]["field"] == "content"
    assert "required" in body["details"][0]["message"]


def test_review_code_success_includes_correlation_id_and_result_shape(client):
    """POST /review should return review result and include correlation_id."""
    payload = {"content": "def ok(): pass", "language": "python"}
    headers = {"X-Correlation-ID": "abc-123"}
    resp = client.post("/review", json=payload, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert "score" in body
    assert "issues" in body and isinstance(body["issues"], list)
    assert "suggestions" in body
    assert "complexity_score" in body
    assert body["correlation_id"] == "abc-123"


def test_review_function_missing_field_returns_400(client):
    """POST /review/function without 'function_code' should return 400."""
    resp = client.post("/review/function", json={"foo": "bar"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing 'function_code' field"


def test_review_function_success_returns_reviewer_output(client):
    """POST /review/function returns underlying reviewer payload."""
    code = "def a():\n  return 1\n"
    resp = client.post("/review/function", json={"function_code": code})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["length"] == len(code)


@pytest.mark.parametrize("endpoint", [
    "/statistics",
    "/coverage/analyze",
    "/coverage/report",
])
def test_post_endpoints_missing_body_returns_400(client, endpoint):
    """POST endpoints should return 400 when body is missing."""
    resp = client.post(endpoint)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing request body"


def test_statistics_validation_error_returns_422(client, app_module):
    """POST /statistics should return 422 on validation errors."""
    def fake_validate(data):
        class E:
            def to_dict(self):
                return {"field": "files", "message": "must be a list"}
        return [E()]
    app_module.validate_statistics_request = fake_validate

    resp = client.post("/statistics", json={"files": "not a list"})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "Validation failed"
    assert body["details"][0]["field"] == "files"


def test_statistics_success_includes_correlation_id(client):
    """POST /statistics returns aggregated stats and correlation_id."""
    headers = {"X-Correlation-ID": "cid-789"}
    payload = {"files": [{"path": "a.py"}, {"path": "b.py"}]}
    resp = client.post("/statistics", json=payload, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_files"] == 2
    assert "average_score" in body
    assert "issues_by_severity" in body
    assert body["correlation_id"] == "cid-789"


def test_traces_list_and_get_behaviors(client, stubs):
    """GET /traces and /traces/<id> should reflect stubbed trace store."""
    # Populate stub traces
    stubs["corr"]._TRACES_STORE.clear()
    stubs["corr"]._TRACES_STORE["trace-1"] = [{"e": 1}, {"e": 2}]
    stubs["corr"]._TRACES_STORE["trace-2"] = [{"e": "a"}]

    # List all traces
    list_resp = client.get("/traces")
    assert list_resp.status_code == 200
    list_body = list_resp.get_json()
    assert list_body["total_traces"] == 2
    assert isinstance(list_body["traces"], list)

    # Get a specific trace
    get_resp = client.get("/traces/trace-1")
    assert get_resp.status_code == 200
    get_body = get_resp.get_json()
    assert get_body["correlation_id"] == "trace-1"
    assert get_body["trace_count"] == 2
    assert isinstance(get_body["traces"], list)


def test_get_trace_not_found_returns_404(client, stubs):
    """GET /traces/<id> should return 404 when no traces found."""
    stubs["corr"]._TRACES_STORE.clear()
    resp = client.get("/traces/missing-id")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "No traces found for correlation ID"


def test_validation_errors_list_and_clear(client, stubs, app_module):
    """GET and DELETE /validation/errors should list and clear errors."""
    # Pre-populate the store directly
    stubs["reqval"]._VALIDATION_ERRORS_STORE[:] = [
        {"id": "1", "message": "bad input", "field": "content"},
        {"id": "2", "message": "too short", "field": "title"},
    ]

    list_resp = client.get("/validation/errors")
    assert list_resp.status_code == 200
    list_body = list_resp.get_json()
    assert list_body["total_errors"] == 2
    assert isinstance(list_body["errors"], list)

    # Track calls to clear function
    called = {"cnt": 0}
    def fake_clear():
        called["cnt"] += 1
        stubs["reqval"]._VALIDATION_ERRORS_STORE.clear()

    app_module.clear_validation_errors = fake_clear

    del_resp = client.delete("/validation/errors")
    assert del_resp.status_code == 200
    assert del_resp.get_json()["message"] == "Validation errors cleared"
    assert called["cnt"] == 1

    # Ensure it's empty now
    list_resp2 = client.get("/validation/errors")
    assert list_resp2.status_code == 200
    assert list_resp2.get_json()["total_errors"] == 0


def test_analyze_coverage_missing_source_code_returns_400(client):
    """POST /coverage/analyze without source_code should return 400."""
    resp = client.post("/coverage/analyze", json={"test_code": ""})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing 'source_code' field"


def test_analyze_coverage_syntax_error_returns_400(client):
    """POST /coverage/analyze with syntax errors should return 400 and details."""
    payload = {"source_code": "SYNTAX_ERROR", "test_code": ""}
    resp = client.post("/coverage/analyze", json=payload)
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "Invalid Python syntax in source code"
    assert "invalid syntax" in body["details"]


def test_analyze_coverage_success_limits_items_and_includes_correlation_id(client):
    """POST /coverage/analyze should return truncated lists and correlation_id."""
    headers = {"X-Correlation-ID": "cov-1"}
    payload = {"source_code": "def ok():\n  return 1\n"}
    resp = client.post("/coverage/analyze", json=payload, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["correlation_id"] == "cov-1"
    report = body["coverage_report"]
    assert "summary" in report
    assert "metrics" in report
    assert "branch_coverage" in report
    assert len(report["uncovered_items"]) == 20  # truncated to 20
    assert len(report["high_complexity_items"]) == 10  # truncated to 10
    assert "function_coverage_map" in report


def test_generate_coverage_report_missing_source_code_returns_400(client):
    """POST /coverage/report without source_code should return 400."""
    resp = client.post("/coverage/report", json={"test_code": ""})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing 'source_code' field"


def test_generate_coverage_report_syntax_error_returns_400(client):
    """POST /coverage/report with syntax errors should return 400 and details."""
    payload = {"source_code": "SYNTAX_ERROR"}
    resp = client.post("/coverage/report", json=payload)
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "Invalid Python syntax in source code"
    assert "invalid syntax" in body["details"]


def test_generate_coverage_report_generic_exception_returns_500(client, app_module, monkeypatch):
    """POST /coverage/report should return 500 when analyzer raises generic Exception."""
    def boom(**kwargs):
        raise Exception("boom")
    monkeypatch.setattr(app_module.coverage_analyzer, "analyze_coverage", boom)
    resp = client.post("/coverage/report", json={"source_code": "def ok(): pass"})
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["error"] == "Failed to generate coverage report"
    assert "boom" in body["details"]


def test_generate_coverage_report_success_computes_percentages(client):
    """POST /coverage/report should return detailed report with computed percentages."""
    payload = {"source_code": "def ok():\n  return 1\n"}
    headers = {"X-Correlation-ID": "cov-2"}
    resp = client.post("/coverage/report", json=payload, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["correlation_id"] == "cov-2"
    report = body["detailed_report"]
    assert report["overall_coverage_percentage"] == 76.54
    assert report["function_coverage"]["total"] == 10
    assert report["function_coverage"]["covered"] == 7
    assert report["function_coverage"]["percentage"] == 70.0
    assert report["class_coverage"]["percentage"] == 50.0
    assert report["method_coverage"]["percentage"] == 50.0
    assert report["line_coverage"]["percentage"] == 80.0
    assert isinstance(report["all_uncovered_items"], list)
    assert isinstance(report["all_high_complexity_items"], list)
    assert isinstance(report["suggestions"], list)
    assert isinstance(report["function_coverage_map"], dict)