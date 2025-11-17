from flask import Flask, jsonify, request

try:
    from src.code_reviewer import CodeReviewer
except Exception:  # pragma: no cover - defensive import
    CodeReviewer = None  # type: ignore

try:
    from src.statistics import StatisticsAggregator
except Exception:  # pragma: no cover - defensive import
    StatisticsAggregator = None  # type: ignore

try:
    from src.correlation_middleware import (
        CorrelationIDMiddleware,
        get_traces,
        get_all_traces,
    )
except Exception:  # pragma: no cover - defensive import
    CorrelationIDMiddleware = None  # type: ignore
    def get_traces(_):  # type: ignore
        return []
    def get_all_traces():  # type: ignore
        return []

try:
    from src.request_validator import (
        validate_review_request,
        validate_statistics_request,
        sanitize_request_data,
        get_validation_errors,
        clear_validation_errors,
    )
except Exception:  # pragma: no cover - defensive import
    def validate_review_request(_):  # type: ignore
        return []
    def validate_statistics_request(_):  # type: ignore
        return []
    def sanitize_request_data(d):  # type: ignore
        return d
    def get_validation_errors():  # type: ignore
        return []
    def clear_validation_errors():  # type: ignore
        return None

app = Flask(__name__)

# Initialize shared components and expose as module-level variables for patching in tests
reviewer = CodeReviewer() if CodeReviewer else None
statistics_aggregator = StatisticsAggregator() if StatisticsAggregator else None

# Attach middleware if available
if CorrelationIDMiddleware:
    try:
        CorrelationIDMiddleware(app)  # type: ignore
    except Exception:
        pass


def _get_json_or_none() -> dict | None:
    # silent=True prevents Flask from returning 400/415 automatically
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return None


def _get_correlation_id() -> str | None:
    return request.headers.get("X-Correlation-ID")


def _serialize_issue(issue) -> dict:
    if isinstance(issue, dict):
        return issue
    # Fallback: extract common attributes if present
    result = {}
    for key in ("severity", "line", "message", "suggestion"):
        if hasattr(issue, key):
            value = getattr(issue, key)
            result[key] = value
    return result


@app.get("/health")
def health():
    return jsonify({"status": "healthy", "service": "python-reviewer"}), 200


@app.post("/review")
def review_code_endpoint():
    data = _get_json_or_none()
    if data is None:
        return jsonify({"error": "Missing request body"}), 400

    errors = validate_review_request(data)
    if errors:
        # Each error object should provide to_dict()
        details = [e.to_dict() if hasattr(e, "to_dict") else dict(e) for e in errors]
        return jsonify({"error": "Validation failed", "details": details}), 422

    clean = sanitize_request_data(data) if sanitize_request_data else data
    content = clean.get("content")
    language = clean.get("language")

    result = reviewer.review_code(content, language) if reviewer else None

    # Support both attribute and dict-style access for result
    score = getattr(result, "score", None) if result is not None else None
    complexity_score = getattr(result, "complexity_score", None) if result is not None else None
    suggestions = getattr(result, "suggestions", None) if result is not None else None
    issues = getattr(result, "issues", None) if result is not None else None

    issues_list = []
    if isinstance(issues, list):
        issues_list = [_serialize_issue(i) for i in issues]

    response = {
        "score": score,
        "complexity_score": complexity_score,
        "suggestions": suggestions if suggestions is not None else [],
        "issues": issues_list,
        "correlation_id": _get_correlation_id(),
    }
    return jsonify(response), 200


@app.post("/review/function")
def review_function_endpoint():
    # This endpoint should return a consistent error for missing function_code
    data = _get_json_or_none() or {}
    function_code = data.get("function_code")
    if not function_code:
        return jsonify({"error": "Missing 'function_code' field"}), 400

    result = reviewer.review_function(function_code) if reviewer else {}
    # Assume result is JSON-serializable (dict-like)
    return jsonify(result), 200


@app.post("/statistics")
def statistics_endpoint():
    data = _get_json_or_none()
    if data is None:
        return jsonify({"error": "Missing request body"}), 400

    errors = validate_statistics_request(data)
    if errors:
        details = [e.to_dict() if hasattr(e, "to_dict") else dict(e) for e in errors]
        return jsonify({"error": "Validation failed", "details": details}), 422

    clean = sanitize_request_data(data) if sanitize_request_data else data
    files = clean.get("files", [])

    stats = statistics_aggregator.aggregate_reviews(files) if statistics_aggregator else None

    response = {
        "total_files": getattr(stats, "total_files", 0) if stats is not None else 0,
        "average_score": getattr(stats, "average_score", 0.0) if stats is not None else 0.0,
        "total_issues": getattr(stats, "total_issues", 0) if stats is not None else 0,
        "issues_by_severity": getattr(stats, "issues_by_severity", {}) if stats is not None else {},
        "average_complexity": getattr(stats, "average_complexity", 0.0) if stats is not None else 0.0,
        "files_with_high_complexity": getattr(stats, "files_with_high_complexity", []) if stats is not None else [],
        "total_suggestions": getattr(stats, "total_suggestions", 0) if stats is not None else 0,
        "correlation_id": _get_correlation_id(),
    }
    return jsonify(response), 200


@app.get("/traces")
def list_traces():
    traces = get_all_traces()
    return jsonify({"total_traces": len(traces), "traces": traces}), 200


@app.get("/traces/<correlation_id>")
def get_trace(correlation_id: str):
    traces = get_traces(correlation_id)
    if not traces:
        return jsonify({"error": "No traces found for correlation ID"}), 404
    return jsonify(
        {
            "correlation_id": correlation_id,
            "trace_count": len(traces),
            "traces": traces,
        }
    ), 200


@app.get("/validation/errors")
def list_validation_errors():
    errors = get_validation_errors()
    return jsonify({"total_errors": len(errors), "errors": errors}), 200


@app.delete("/validation/errors")
def delete_validation_errors():
    clear_validation_errors()
    return jsonify({"message": "Validation errors cleared"}), 200


if __name__ == "__main__":  # pragma: no cover
    app.run(host="0.0.0.0", port=8000, debug=True)