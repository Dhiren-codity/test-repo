from flask import Flask, jsonify, request, g
from typing import Any, Dict, List, Optional, Iterable
import itertools
import time
import threading


# A Flask subclass that allows late before_request registration for testing purposes
class TestingFlask(Flask):
    def before_request(self, f):
        self.before_request_funcs.setdefault(None, []).append(f)
        return f


app = TestingFlask(__name__)


# -------------------------
# Utilities and placeholders
# -------------------------

def sanitize_input(value: Optional[str]) -> str:
    if value is None:
        return ""
    allowed_whitespace = {"\n", "\t", " "}
    result_chars = []
    for ch in value:
        if ch in allowed_whitespace:
            result_chars.append(ch)
        elif ch == "\r":
            # strip carriage returns
            continue
        elif ch.isprintable():
            result_chars.append(ch)
        # other control chars are dropped
    return "".join(result_chars)


def sanitize_request_data(data: Any) -> Any:
    # Recursively sanitize string values in common structures
    if isinstance(data, dict):
        return {k: sanitize_request_data(v) for k, v in data.items()}
    if isinstance(data, list):
        return [sanitize_request_data(x) for x in data]
    if isinstance(data, str):
        return sanitize_input(data)
    return data


# Correlation ID middleware-like generator
_global_counter = itertools.count()
_global_counter_lock = threading.Lock()


class CorrelationIDMiddleware:
    def generate_correlation_id(self, language_code: str = "py", now: Optional[int] = None) -> str:
        ts = int(now if now is not None else time.time())
        with _global_counter_lock:
            seq = next(_global_counter)
        return f"{ts}-{language_code}-{seq}"


# Placeholders for dependency points which tests may monkeypatch
def validate_review_request(data: Dict[str, Any]) -> List[Any]:
    errors = []
    if not isinstance(data, dict):
        return [SimpleValidationError("body", "must be an object")]
    if "content" not in data:
        errors.append(SimpleValidationError("content", "required"))
    if "language" not in data:
        errors.append(SimpleValidationError("language", "required"))
    return errors


def validate_statistics_request(data: Dict[str, Any]) -> List[Any]:
    errors = []
    if not isinstance(data, dict):
        return [SimpleValidationError("body", "must be an object")]
    files = data.get("files")
    if not isinstance(files, list):
        errors.append(SimpleValidationError("files", "must be a list"))
    return errors


class SimpleValidationError:
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message

    def to_dict(self) -> Dict[str, str]:
        return {"field": self.field, "message": self.message}


class Reviewer:
    def review_code(self, content: str, language: str) -> Any:
        # Simple default response
        return type(
            "ReviewResult",
            (),
            {
                "score": 100,
                "issues": [],
                "suggestions": [],
                "complexity_score": 1.0,
            },
        )()

    def review_function(self, function_code: str) -> Dict[str, Any]:
        return {"issues": [], "score": 100}


reviewer = Reviewer()


class StatisticsAggregator:
    def aggregate_reviews(self, files: Iterable[Dict[str, Any]]) -> Any:
        files_list = list(files or [])
        total_files = len(files_list)
        return type(
            "Stats",
            (),
            {
                "total_files": total_files,
                "average_score": 100.0 if total_files else 0.0,
                "total_issues": 0,
                "issues_by_severity": {},
                "average_complexity": 0.0,
                "files_with_high_complexity": [],
                "total_suggestions": 0,
            },
        )()


statistics_aggregator = StatisticsAggregator()


# In-memory stores for traces and validation errors for default behavior
_TRACES: Dict[str, List[Dict[str, Any]]] = {}
_VALIDATION_ERRORS: List[Dict[str, Any]] = []


def get_all_traces() -> List[Dict[str, Any]]:
    traces = []
    for cid, events in _TRACES.items():
        for e in events:
            record = {"correlation_id": cid}
            record.update(e)
            traces.append(record)
    return traces


def get_traces(correlation_id: str) -> List[Dict[str, Any]]:
    return list(_TRACES.get(correlation_id, []))


def get_validation_errors() -> List[Dict[str, Any]]:
    return list(_VALIDATION_ERRORS)


def clear_validation_errors() -> None:
    _VALIDATION_ERRORS.clear()


# -------------------------
# Routes
# -------------------------

@app.get("/health")
def health():
    return jsonify({"status": "healthy", "service": "python-reviewer"}), 200


@app.post("/review")
def review_code():
    if not request.is_json:
        return jsonify({"error": "Request body must be JSON"}), 400
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be an object"}), 400

    errors = validate_review_request(data)
    if errors:
        details = [e.to_dict() for e in errors]
        # capture validation errors for visibility
        _VALIDATION_ERRORS.extend(details)
        return jsonify({"error": "Validation failed", "details": details}), 422

    clean = sanitize_request_data(data)
    content = clean.get("content")
    language = clean.get("language")
    result = reviewer.review_code(content, language)

    issues_out = []
    for it in getattr(result, "issues", []):
        issues_out.append(
            {
                "severity": getattr(it, "severity", None),
                "line": getattr(it, "line", None),
                "message": getattr(it, "message", None),
                "suggestion": getattr(it, "suggestion", None),
            }
        )

    response = {
        "score": getattr(result, "score", None),
        "issues": issues_out,
        "suggestions": list(getattr(result, "suggestions", [])),
        "complexity_score": getattr(result, "complexity_score", None),
        "correlation_id": getattr(g, "correlation_id", None),
    }
    return jsonify(response), 200


@app.post("/review/function")
def review_function():
    if not request.is_json:
        return jsonify({"error": "Request body must be JSON"}), 400
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "function_code" not in data:
        return jsonify({"error": "Missing 'function_code'"}), 400
    code = data.get("function_code")
    result = reviewer.review_function(code)
    return jsonify(result), 200


@app.post("/statistics")
def statistics():
    if not request.is_json:
        return jsonify({"error": "Request body must be JSON"}), 400
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be an object"}), 400

    errors = validate_statistics_request(data)
    if errors:
        details = [e.to_dict() for e in errors]
        _VALIDATION_ERRORS.extend(details)
        return jsonify({"error": "Validation failed", "details": details}), 422

    clean = sanitize_request_data(data)
    files = clean.get("files", [])
    stats = statistics_aggregator.aggregate_reviews(files)

    response = {
        "total_files": getattr(stats, "total_files", 0),
        "average_score": getattr(stats, "average_score", 0.0),
        "total_issues": getattr(stats, "total_issues", 0),
        "issues_by_severity": getattr(stats, "issues_by_severity", {}),
        "average_complexity": getattr(stats, "average_complexity", 0.0),
        "files_with_high_complexity": getattr(stats, "files_with_high_complexity", []),
        "total_suggestions": getattr(stats, "total_suggestions", 0),
        "correlation_id": getattr(g, "correlation_id", None),
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
    return jsonify({"correlation_id": correlation_id, "trace_count": len(traces), "traces": traces}), 200


@app.get("/validation/errors")
def list_validation_errors():
    errors = get_validation_errors()
    return jsonify({"total_errors": len(errors), "errors": errors}), 200


@app.delete("/validation/errors")
def delete_validation_errors():
    clear_validation_errors()
    return jsonify({"message": "Validation errors cleared"}), 200


# Export names for tests
__all__ = [
    "app",
    "sanitize_input",
    "sanitize_request_data",
    "CorrelationIDMiddleware",
    "validate_review_request",
    "validate_statistics_request",
    "reviewer",
    "statistics_aggregator",
    "get_all_traces",
    "get_traces",
    "get_validation_errors",
    "clear_validation_errors",
]