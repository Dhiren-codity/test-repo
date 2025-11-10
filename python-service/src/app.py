import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify, g  # noqa: E402
from flask_cors import CORS  # noqa: E402
from src.code_reviewer import CodeReviewer  # noqa: E402
from src.statistics import StatisticsAggregator  # noqa: E402
from src.correlation_middleware import CorrelationIDMiddleware, get_traces, get_all_traces  # noqa: E402
from src.request_validator import (  # noqa: E402
    validate_review_request,
    validate_statistics_request,
    sanitize_request_data,
    get_validation_errors,
    clear_validation_errors
)

app = Flask(__name__)
CORS(app)

correlation_middleware = CorrelationIDMiddleware(app)

reviewer = CodeReviewer()
statistics_aggregator = StatisticsAggregator()


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "python-reviewer"})


@app.route("/review", methods=["POST"])
def review_code():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Missing request body"}), 400

    validation_errors = validate_review_request(data)
    if validation_errors:
        return jsonify({
            "error": "Validation failed",
            "details": [error.to_dict() for error in validation_errors]
        }), 422

    sanitized_data = sanitize_request_data(data)
    content = sanitized_data.get("content", "")
    language = sanitized_data.get("language", "python")

    result = reviewer.review_code(content, language)

    correlation_id = getattr(g, 'correlation_id', None)

    return jsonify(
        {
            "score": result.score,
            "issues": [
                {
                    "severity": issue.severity,
                    "line": issue.line,
                    "message": issue.message,
                    "suggestion": issue.suggestion,
                }
                for issue in result.issues
            ],
            "suggestions": result.suggestions,
            "complexity_score": result.complexity_score,
            "correlation_id": correlation_id
        }
    )


@app.route("/review/function", methods=["POST"])
def review_function():
    data = request.get_json()

    if not data or "function_code" not in data:
        return jsonify({"error": "Missing 'function_code' field"}), 400

    function_code = data.get("function_code", "")
    result = reviewer.review_function(function_code)

    return jsonify(result)


@app.route("/statistics", methods=["POST"])
def get_statistics():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Missing request body"}), 400

    validation_errors = validate_statistics_request(data)
    if validation_errors:
        return jsonify({
            "error": "Validation failed",
            "details": [error.to_dict() for error in validation_errors]
        }), 422

    sanitized_data = sanitize_request_data(data)
    files = sanitized_data.get("files", [])
    stats = statistics_aggregator.aggregate_reviews(files)

    correlation_id = getattr(g, 'correlation_id', None)

    return jsonify(
        {
            "total_files": stats.total_files,
            "average_score": stats.average_score,
            "total_issues": stats.total_issues,
            "issues_by_severity": stats.issues_by_severity,
            "average_complexity": stats.average_complexity,
            "files_with_high_complexity": stats.files_with_high_complexity,
            "total_suggestions": stats.total_suggestions,
            "correlation_id": correlation_id
        }
    )


@app.route("/traces", methods=["GET"])
def list_traces():
    all_traces = get_all_traces()
    return jsonify({
        "total_traces": len(all_traces),
        "traces": all_traces
    })


@app.route("/traces/<correlation_id>", methods=["GET"])
def get_trace(correlation_id):
    traces = get_traces(correlation_id)

    if not traces:
        return jsonify({"error": "No traces found for correlation ID"}), 404

    return jsonify({
        "correlation_id": correlation_id,
        "trace_count": len(traces),
        "traces": traces
    })


@app.route("/validation/errors", methods=["GET"])
def list_validation_errors():
    errors = get_validation_errors()
    return jsonify({
        "total_errors": len(errors),
        "errors": errors
    })


@app.route("/validation/errors", methods=["DELETE"])
def delete_validation_errors():
    clear_validation_errors()
    return jsonify({"message": "Validation errors cleared"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081, debug=False)
