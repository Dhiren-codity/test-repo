from flask import Flask, request, jsonify, g

try:
    from src.code_reviewer import CodeReviewer
except Exception:  # pragma: no cover
    CodeReviewer = None

try:
    from src.statistics import StatisticsAggregator
except Exception:  # pragma: no cover
    StatisticsAggregator = None

try:
    from src.correlation_middleware import (
        CorrelationIDMiddleware,
        get_traces,
        get_all_traces,
    )
except Exception:  # pragma: no cover
    CorrelationIDMiddleware = None

    def get_traces(_cid):
        return []

    def get_all_traces():
        return []

try:
    from src.request_validator import (
        validate_review_request,
        validate_statistics_request,
        sanitize_request_data,
        get_validation_errors,
        clear_validation_errors,
    )
except Exception:  # pragma: no cover
    def validate_review_request(_data):
        return []

    def validate_statistics_request(_data):
        return []

    def sanitize_request_data(data):
        return data

    def get_validation_errors():
        return []

    def clear_validation_errors():
        return None


app = Flask(__name__)

# Attach middleware if available
try:  # pragma: no cover
    if CorrelationIDMiddleware is not None:
        app.wsgi_app = CorrelationIDMiddleware(app.wsgi_app)
except Exception:
    # Middleware is optional; app should still function
    pass

# Instantiate services if classes are available
reviewer = CodeReviewer() if CodeReviewer is not None else None
statistics_aggregator = (
    StatisticsAggregator() if StatisticsAggregator is not None else None
)


def _issues_to_dicts(issues):
    result = []
    for i in issues or []:
        if isinstance(i, dict):
            result.append(i)
            continue
        result.append(
            {
                "severity": getattr(i, "severity", None),
                "line": getattr(i, "line", None),
                "message": getattr(i, "message", None),
                "suggestion": getattr(i, "suggestion", None),
            }
        )
    return result


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "service": "python-reviewer"}), 200


@app.route("/review", methods=["POST"])
def review_code():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Missing request body"}), 400

    errors = validate_review_request(data)
    if errors:
        details = [e.to_dict() if hasattr(e, "to_dict") else dict(e) for e in errors]
        return jsonify({"error": "Validation failed", "details": details}), 422

    data = sanitize_request_data(data)

    if reviewer is None:
        return jsonify({"error": "Service unavailable"}), 503

    result = reviewer.review_code(data.get("content"), data.get("language"))

    response = {
        "score": getattr(result, "score", None),
        "issues": _issues_to_dicts(getattr(result, "issues", [])),
        "suggestions": getattr(result, "suggestions", []),
        "complexity_score": getattr(result, "complexity_score", None),
        "correlation_id": getattr(g, "correlation_id", None),
    }
    return jsonify(response), 200


@app.route("/review/function", methods=["POST"])
def review_function():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Missing request body"}), 400

    function_code = data.get("function_code")
    if not function_code:
        return jsonify({"error": "Missing 'function_code' field"}), 400

    if reviewer is None:
        return jsonify({"error": "Service unavailable"}), 503

    result = reviewer.review_function(function_code)
    return jsonify(result), 200


@app.route("/statistics", methods=["POST"])
def get_statistics():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Missing request body"}), 400

    errors = validate_statistics_request(data)
    if errors:
        details = [e.to_dict() if hasattr(e, "to_dict") else dict(e) for e in errors]
        return jsonify({"error": "Validation failed", "details": details}), 422

    data = sanitize_request_data(data)

    if statistics_aggregator is None:
        return jsonify({"error": "Service unavailable"}), 503

    stats = statistics_aggregator.aggregate_reviews(data.get("files"))

    response = {
        "total_files": getattr(stats, "total_files", 0),
        "average_score": getattr(stats, "average_score", 0.0),
        "total_issues": getattr(stats, "total_issues", 0),
        "issues_by_severity": getattr(stats, "issues_by_severity", {}),
        "average_complexity": getattr(stats, "average_complexity", 0.0),
        "files_with_high_complexity": getattr(
            stats, "files_with_high_complexity", []
        ),
        "total_suggestions": getattr(stats, "total_suggestions", 0),
        "correlation_id": getattr(g, "correlation_id", None),
    }
    return jsonify(response), 200


@app.route("/traces", methods=["GET"])
def list_traces():
    traces = get_all_traces()
    return jsonify({"total_traces": len(traces), "traces": traces}), 200


@app.route("/traces/<correlation_id>", methods=["GET"])
def get_trace(correlation_id):
    items = get_traces(correlation_id)
    if not items:
        return jsonify({"error": "No traces found for correlation ID"}), 404
    return (
        jsonify(
            {
                "correlation_id": correlation_id,
                "trace_count": len(items),
                "traces": items,
            }
        ),
        200,
    )


@app.route("/validation/errors", methods=["GET"])
def list_validation_errors():
    errors = get_validation_errors()
    return jsonify({"total_errors": len(errors), "errors": errors}), 200


@app.route("/validation/errors", methods=["DELETE"])
def delete_validation_errors():
    clear_validation_errors()
    return jsonify({"message": "Validation errors cleared"}), 200


__all__ = [
    "app",
    "reviewer",
    "statistics_aggregator",
    "validate_review_request",
    "validate_statistics_request",
    "sanitize_request_data",
    "get_validation_errors",
    "clear_validation_errors",
    "get_traces",
    "get_all_traces",
]