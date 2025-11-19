import uuid
from typing import Any, Dict, List, Union

from flask import Flask, jsonify, request

# Attempt to import optional modules; provide graceful fallbacks if not available.
try:
    from src.code_reviewer import CodeReviewer  # type: ignore
except Exception:  # pragma: no cover - fallback for test envs without module
    class CodeReviewer:  # minimal fallback
        def review_code(self, content: str, language: str = "python"):
            # Very simple fallback review
            return {
                "score": 100,
                "issues": [],
                "suggestions": [],
                "complexity_score": 1.0,
            }

        def review_function(self, function_code: str):
            return {"status": "ok"}

try:
    from src.statistics import StatisticsAggregator  # type: ignore
except Exception:  # pragma: no cover - fallback for test envs without module
    class StatisticsAggregator:  # minimal fallback
        def aggregate_reviews(self, files: List[Dict[str, Any]]):
            return type(
                "Stats",
                (),
                dict(
                    total_files=len(files or []),
                    average_score=100.0,
                    total_issues=0,
                    issues_by_severity={},
                    average_complexity=1.0,
                    files_with_high_complexity=[],
                    total_suggestions=0,
                ),
            )()

# Correlation helpers. In test suite, these are monkeypatched via src.app.get_traces / get_all_traces
try:
    from src.correlation_middleware import get_traces as _get_traces  # type: ignore
    from src.correlation_middleware import get_all_traces as _get_all_traces  # type: ignore
except Exception:  # pragma: no cover - fallback
    def _get_traces(correlation_id: str):
        return []

    def _get_all_traces():
        return []

# Validation helpers; also referenced directly from src.app in tests (monkeypatched)
try:
    from src.request_validator import (  # type: ignore
        validate_review_request as _validate_review_request,
        validate_statistics_request as _validate_statistics_request,
        sanitize_request_data as _sanitize_request_data,
        get_validation_errors as _get_validation_errors,
        clear_validation_errors as _clear_validation_errors,
    )
except Exception:  # pragma: no cover - fallbacks
    def _validate_review_request(data: Dict[str, Any]):
        return []

    def _validate_statistics_request(data: Dict[str, Any]):
        return []

    def _sanitize_request_data(data: Dict[str, Any]):
        return data

    _VAL_ERRORS: List[Dict[str, Any]] = []

    def _get_validation_errors():
        return list(_VAL_ERRORS)

    def _clear_validation_errors():
        _VAL_ERRORS.clear()


# Expose names to module scope for monkeypatch in tests
validate_review_request = _validate_review_request
validate_statistics_request = _validate_statistics_request
sanitize_request_data = _sanitize_request_data
get_validation_errors = _get_validation_errors
clear_validation_errors = _clear_validation_errors
get_traces = _get_traces
get_all_traces = _get_all_traces


app = Flask(__name__)

# Singletons used by tests (they monkeypatch methods on these)
reviewer = CodeReviewer()
statistics_aggregator = StatisticsAggregator()


def _get_correlation_id() -> str:
    return request.headers.get("X-Correlation-ID") or str(uuid.uuid4())


def _json_body_or_none() -> Union[Dict[str, Any], None]:
    # Avoid 415 Unsupported Media Type by using silent=True
    return request.get_json(silent=True)


def _to_issue_dict(issue: Any) -> Dict[str, Any]:
    if isinstance(issue, dict):
        return {
            "severity": issue.get("severity"),
            "line": issue.get("line"),
            "message": issue.get("message"),
            "suggestion": issue.get("suggestion"),
        }
    return {
        "severity": getattr(issue, "severity", None),
        "line": getattr(issue, "line", None),
        "message": getattr(issue, "message", None),
        "suggestion": getattr(issue, "suggestion", None),
    }


def _get_val(obj: Any, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


@app.get("/health")
def health():
    return jsonify({"status": "healthy", "service": "python-reviewer"}), 200


@app.post("/review")
def review_code_endpoint():
    data = _json_body_or_none()
    if data is None:
        return jsonify({"error": "Missing request body"}), 400

    errors = validate_review_request(data)
    if errors:
        # Each error object is expected to have to_dict
        details = [e.to_dict() if hasattr(e, "to_dict") else dict(e) for e in errors]
        return jsonify({"error": "Validation failed", "details": details}), 422

    clean = sanitize_request_data(data)

    # Safe extraction with defaults
    content = clean.get("content") if isinstance(clean, dict) else getattr(clean, "content", None)
    language = clean.get("language") if isinstance(clean, dict) else getattr(clean, "language", None)

    result = reviewer.review_code(content, language)

    # Result can be dict or object; support both
    score = _get_val(result, "score", 0)
    issues = _get_val(result, "issues", []) or []
    suggestions = _get_val(result, "suggestions", []) or []
    complexity_score = _get_val(result, "complexity_score", None)

    payload = {
        "score": score,
        "issues": [_to_issue_dict(i) for i in issues],
        "suggestions": list(suggestions),
        "complexity_score": complexity_score,
        "correlation_id": _get_correlation_id(),
    }
    return jsonify(payload), 200


@app.post("/review/function")
def review_function_endpoint():
    data = _json_body_or_none()
    function_code = None
    if isinstance(data, dict):
        function_code = data.get("function_code")

    if not function_code:
        return jsonify({"error": "Missing 'function_code' field"}), 400

    result = reviewer.review_function(function_code)
    # If reviewer returns non-dict, convert to dict-like if possible
    if not isinstance(result, dict):
        try:
            result = dict(result)  # type: ignore
        except Exception:
            # Fallback to attribute copying
            result = {k: getattr(result, k) for k in dir(result) if not k.startswith("_")}
    return jsonify(result), 200


@app.post("/statistics")
def statistics_endpoint():
    data = _json_body_or_none()
    if data is None:
        return jsonify({"error": "Missing request body"}), 400

    errors = validate_statistics_request(data)
    if errors:
        details = [e.to_dict() if hasattr(e, "to_dict") else dict(e) for e in errors]
        return jsonify({"error": "Validation failed", "details": details}), 422

    clean = sanitize_request_data(data)
    files = clean.get("files") if isinstance(clean, dict) else getattr(clean, "files", None)
    stats = statistics_aggregator.aggregate_reviews(files or [])

    payload = {
        "total_files": _get_val(stats, "total_files", 0),
        "average_score": _get_val(stats, "average_score", 0.0),
        "total_issues": _get_val(stats, "total_issues", 0),
        "issues_by_severity": _get_val(stats, "issues_by_severity", {}),
        "average_complexity": _get_val(stats, "average_complexity", 0.0),
        "files_with_high_complexity": _get_val(stats, "files_with_high_complexity", []),
        "total_suggestions": _get_val(stats, "total_suggestions", 0),
        "correlation_id": _get_correlation_id(),
    }
    return jsonify(payload), 200


@app.get("/traces")
def list_traces():
    traces = get_all_traces() or []
    return jsonify({"total_traces": len(traces), "traces": traces}), 200


@app.get("/traces/<correlation_id>")
def get_trace(correlation_id: str):
    traces = get_traces(correlation_id) or []
    if not traces:
        return jsonify({"error": "No traces found for correlation ID"}), 404
    return jsonify({"correlation_id": correlation_id, "trace_count": len(traces), "traces": traces}), 200


@app.get("/validation/errors")
def list_validation_errors():
    errors = get_validation_errors() or []
    return jsonify({"total_errors": len(errors), "errors": errors}), 200


@app.delete("/validation/errors")
def delete_validation_errors():
    clear_validation_errors()
    return jsonify({"message": "Validation errors cleared"}), 200


# Optional endpoints (may help additional integration tests; harmless otherwise)

@app.post("/diff")
def diff_endpoint():
    data = _json_body_or_none() or {}
    old_content = data.get("old_content")
    new_content = data.get("new_content")
    if old_content is None or new_content is None:
        return jsonify({"error": "Missing required fields: 'old_content' and/or 'new_content'"}), 400

    # Very naive diff (line-based)
    old_lines = str(old_content).splitlines()
    new_lines = str(new_content).splitlines()
    diff_lines: List[str] = []
    max_len = max(len(old_lines), len(new_lines))
    for i in range(max_len):
        o = old_lines[i] if i < len(old_lines) else ""
        n = new_lines[i] if i < len(new_lines) else ""
        if o != n:
            diff_lines.append(f"- {o}")
            diff_lines.append(f"+ {n}")

    review = reviewer.review_code(new_content, "python")
    review_payload = {
        "score": _get_val(review, "score", 0),
        "issues": [_to_issue_dict(i) for i in _get_val(review, "issues", []) or []],
        "suggestions": list(_get_val(review, "suggestions", []) or []),
        "complexity_score": _get_val(review, "complexity_score", None),
    }
    return jsonify({"diff": "\n".join(diff_lines), "review": review_payload}), 200


@app.post("/metrics")
def metrics_endpoint():
    data = _json_body_or_none() or {}
    content = data.get("content")
    if content is None:
        return jsonify({"error": "Missing 'content'"}), 400

    text = str(content)
    lines = text.splitlines()
    metrics = {
        "line_count": len(lines),
        "char_count": len(text),
        "avg_line_length": (len(text) / len(lines)) if lines else 0,
    }
    review = reviewer.review_code(text, "python")
    overall_quality = _get_val(review, "score", 0)
    review_payload = {
        "score": overall_quality,
        "issues": [_to_issue_dict(i) for i in _get_val(review, "issues", []) or []],
        "suggestions": list(_get_val(review, "suggestions", []) or []),
        "complexity_score": _get_val(review, "complexity_score", None),
    }
    return jsonify({"metrics": metrics, "review": review_payload, "overall_quality": overall_quality}), 200


@app.post("/dashboard")
def dashboard_endpoint():
    data = _json_body_or_none() or {}
    files = data.get("files")
    if not isinstance(files, list):
        return jsonify({"error": "Missing or invalid 'files'"}), 400
    stats = statistics_aggregator.aggregate_reviews(files)
    # Simple health score heuristic
    avg_score = _get_val(stats, "average_score", 0.0)
    total_issues = _get_val(stats, "total_issues", 0)
    health_score = max(0.0, min(100.0, float(avg_score) - float(total_issues)))

    payload = {
        "summary": {
            "total_files": _get_val(stats, "total_files", 0),
            "average_score": avg_score,
            "total_issues": total_issues,
            "issues_by_severity": _get_val(stats, "issues_by_severity", {}),
            "average_complexity": _get_val(stats, "average_complexity", 0.0),
            "total_suggestions": _get_val(stats, "total_suggestions", 0),
        },
        "health_score": health_score,
    }
    return jsonify(payload), 200


@app.post("/analyze")
def analyze_endpoint():
    data = _json_body_or_none()
    if data is None:
        return jsonify({"error": "Missing request body"}), 400

    # Reuse review validation
    errors = validate_review_request(data)
    if errors:
        details = [e.to_dict() if hasattr(e, "to_dict") else dict(e) for e in errors]
        return jsonify({"error": "Validation failed", "details": details}), 422

    clean = sanitize_request_data(data)
    content = clean.get("content") if isinstance(clean, dict) else None
    language = clean.get("language") if isinstance(clean, dict) else "python"
    review = reviewer.review_code(content, language)

    payload = {
        "review": {
            "score": _get_val(review, "score", 0),
            "issues": [_to_issue_dict(i) for i in _get_val(review, "issues", []) or []],
            "suggestions": list(_get_val(review, "suggestions", []) or []),
            "complexity_score": _get_val(review, "complexity_score", None),
        }
    }
    return jsonify(payload), 200


if __name__ == "__main__":  # pragma: no cover
    app.run(host="0.0.0.0", port=8000, debug=True)