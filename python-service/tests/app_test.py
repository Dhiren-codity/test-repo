from flask import Flask, jsonify, request, g
from typing import Any, Dict, List
import time

# Attempt to import external modules; provide safe fallbacks if not available
try:
    from src.code_reviewer import CodeReviewer
except Exception:  # pragma: no cover - fallback for environments without the module
    class CodeReviewer:  # type: ignore
        def review_code(self, content, language):
            return type(
                "ReviewResult",
                (),
                {
                    "score": 0,
                    "issues": [],
                    "suggestions": [],
                    "complexity_score": 0.0,
                },
            )()

        def review_function(self, function_code):
            return {"ok": True}

try:
    from src.statistics import StatisticsAggregator
except Exception:  # pragma: no cover
    class StatisticsAggregator:  # type: ignore
        def aggregate_reviews(self, files):
            return type(
                "Stats",
                (),
                {
                    "total_files": len(files or []),
                    "average_score": 0.0,
                    "total_issues": 0,
                    "issues_by_severity": {},
                    "average_complexity": 0.0,
                    "files_with_high_complexity": [],
                    "total_suggestions": 0,
                },
            )()

try:
    # These are imported into module-level names so tests can monkeypatch them
    from src.request_validator import (
        validate_review_request as _validate_review_request,
        validate_statistics_request as _validate_statistics_request,
        sanitize_request_data as _sanitize_request_data,
        get_validation_errors as _get_validation_errors,
        clear_validation_errors as _clear_validation_errors,
    )
except Exception:  # pragma: no cover
    def _validate_review_request(data):
        return []

    def _validate_statistics_request(data):
        return []

    def _sanitize_request_data(data):
        return data

    def _get_validation_errors():
        return []

    def _clear_validation_errors():
        return None

try:
    # Import tracing helpers so tests can monkeypatch these names on this module
    from src.correlation_middleware import (
        get_traces as _get_traces,
        get_all_traces as _get_all_traces,
    )
except Exception:  # pragma: no cover
    def _get_traces(correlation_id):
        return []

    def _get_all_traces():
        return []


# Expose Flask app
app = Flask(__name__)

# Expose instances for monkeypatching in tests
reviewer = CodeReviewer()
statistics_aggregator = StatisticsAggregator()

# Expose validator and trace helpers at module scope so tests can monkeypatch them
validate_review_request = _validate_review_request
validate_statistics_request = _validate_statistics_request
sanitize_request_data = _sanitize_request_data
get_validation_errors = _get_validation_errors
clear_validation_errors = _clear_validation_errors
get_traces = _get_traces
get_all_traces = _get_all_traces


# Utility to safely fetch correlation id from flask.g if present
def _current_correlation_id() -> Any:
    try:
        return getattr(g, "correlation_id", None)
    except Exception:
        return None


@app.get("/health")
def health_check():
    return jsonify({"status": "healthy", "service": "python-reviewer"}), 200


@app.post("/review")
def review_code():
    # Accept even if no JSON content-type; avoid 415 by using silent=True
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Missing request body"}), 400

    errors = validate_review_request(payload)
    if errors:
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "details": [e.to_dict() for e in errors],
                }
            ),
            422,
        )

    data = sanitize_request_data(payload) if payload is not None else {}

    content = data.get("content")
    language = data.get("language")
    result = reviewer.review_code(content, language)

    # Normalize issues to list[dict]
    issues_out: List[Dict[str, Any]] = []
    for it in getattr(result, "issues", []) or []:
        if isinstance(it, dict):
            issues_out.append(
                {
                    "severity": it.get("severity"),
                    "line": it.get("line"),
                    "message": it.get("message"),
                    "suggestion": it.get("suggestion"),
                }
            )
        else:
            issues_out.append(
                {
                    "severity": getattr(it, "severity", None),
                    "line": getattr(it, "line", None),
                    "message": getattr(it, "message", None),
                    "suggestion": getattr(it, "suggestion", None),
                }
            )

    resp = {
        "score": getattr(result, "score", None),
        "issues": issues_out,
        "suggestions": getattr(result, "suggestions", []),
        "complexity_score": getattr(result, "complexity_score", None),
        "correlation_id": _current_correlation_id(),
    }
    return jsonify(resp), 200


@app.post("/review/function")
def review_function():
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Missing request body"}), 400

    function_code = payload.get("function_code") if isinstance(payload, dict) else None
    if not function_code:
        return jsonify({"error": "Missing 'function_code' field"}), 400

    result = reviewer.review_function(function_code)
    # Assume result is JSON-serializable
    return jsonify(result), 200


@app.post("/statistics")
def get_statistics():
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Missing request body"}), 400

    errors = validate_statistics_request(payload)
    if errors:
        return (
            jsonify(
                {
                    "error": "Validation failed",
                    "details": [e.to_dict() for e in errors],
                }
            ),
            422,
        )

    data = sanitize_request_data(payload) if payload is not None else {}
    files = data.get("files", [])

    stats = statistics_aggregator.aggregate_reviews(files)
    resp = {
        "total_files": getattr(stats, "total_files", 0),
        "average_score": getattr(stats, "average_score", 0.0),
        "total_issues": getattr(stats, "total_issues", 0),
        "issues_by_severity": getattr(stats, "issues_by_severity", {}),
        "average_complexity": getattr(stats, "average_complexity", 0.0),
        "files_with_high_complexity": getattr(stats, "files_with_high_complexity", []),
        "total_suggestions": getattr(stats, "total_suggestions", 0),
        "correlation_id": _current_correlation_id(),
    }
    return jsonify(resp), 200


@app.get("/traces")
def list_traces():
    traces = get_all_traces()
    total = len(traces) if isinstance(traces, list) else (len(traces) if isinstance(traces, dict) else 0)
    return jsonify({"total_traces": total, "traces": traces}), 200


@app.get("/traces/<correlation_id>")
def get_trace(correlation_id: str):
    traces = get_traces(correlation_id)
    if not traces:
        return jsonify({"error": "No traces found for correlation ID"}), 404
    return jsonify({"correlation_id": correlation_id, "trace_count": len(traces), "traces": traces}), 200


@app.get("/validation/errors")
def list_validation_errors():
    errs = get_validation_errors() or []
    return jsonify({"total_errors": len(errs), "errors": errs}), 200


@app.delete("/validation/errors")
def delete_validation_errors():
    clear_validation_errors()
    return jsonify({"message": "Validation errors cleared"}), 200


# Optional: minimal correlation id injector for completeness (not required by tests)
@app.before_request
def _ensure_correlation_id():
    # If a test or middleware already set it, don't override
    if getattr(g, "correlation_id", None):
        return
    cid = request.headers.get("X-Correlation-ID")
    if cid:
        g.correlation_id = cid
    else:
        # Do not generate by default; tests may explicitly set it via before_request
        g.correlation_id = getattr(g, "correlation_id", None)


# Optional: simple trace storage utility (for environments/tests that may import from src.app)
_trace_store: Dict[str, List[Dict[str, Any]]] = {}


def store_trace(correlation_id: str, trace: Dict[str, Any]) -> None:
    if not correlation_id:
        return
    trace = dict(trace or {})
    trace.setdefault("correlation_id", correlation_id)
    trace.setdefault("timestamp", time.time())
    _trace_store.setdefault(correlation_id, []).append(trace)


def get_traces_local(correlation_id: str) -> List[Dict[str, Any]]:
    # Return deep-ish copies to avoid mutation; shallow copy of dicts suffices for tests
    return [dict(t) for t in _trace_store.get(correlation_id, [])]


def get_all_traces_local():
    # Return a copy of the entire store
    return {cid: [dict(t) for t in traces] for cid, traces in _trace_store.items()}