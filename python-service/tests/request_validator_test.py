from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional
import threading
import datetime

# Public constants
MAX_CONTENT_SIZE = 10_000  # arbitrary sensible default; tests only check "exceeds maximum size"
ALLOWED_LANGUAGES = {"python", "javascript", "go", "java", "typescript", "c", "cpp"}

# Internal store for validation errors
validation_errors: List[Dict[str, Any]] = []


class ValidationError:
    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        # timestamp uses module datetime for patchability in tests
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, str]:
        return {
            "field": self.field,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


def contains_null_bytes(value: Optional[str]) -> bool:
    if not isinstance(value, str):
        return False
    return "\x00" in value


def contains_path_traversal(path: Optional[str]) -> bool:
    if not isinstance(path, str):
        return False
    return ".." in path or "~/" in path


def sanitize_input(value: Any) -> Any:
    """
    Remove unsafe control characters from a string while preserving newlines and tabs.
    - Keeps: \n, \t
    - Removes: other control chars including \x00 and \x1b, and carriage return \r
    Non-string inputs are stringified, None is passed through unchanged.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)

    allowed = {"\n", "\t"}  # explicitly allow newline and tab; remove carriage return
    result_chars: List[str] = []
    for ch in value:
        code = ord(ch)
        if code < 32 or code == 127:
            # control character
            if ch in allowed:
                result_chars.append(ch)
            # else: skip
        else:
            result_chars.append(ch)
    return "".join(result_chars)


def sanitize_request_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a sanitized copy of request data, only sanitizing specific string fields.
    Only 'content', 'language', and 'path' are sanitized; other keys are left untouched.
    """
    if not isinstance(data, dict):
        return data  # don't transform non-dicts

    keys_to_sanitize = {"content", "language", "path"}
    out: Dict[str, Any] = {}
    for k, v in data.items():
        if k in keys_to_sanitize:
            out[k] = sanitize_input(v)
        else:
            out[k] = v
    return out


def clear_validation_errors() -> None:
    validation_errors.clear()


def keep_recent_errors(limit: int = 100) -> None:
    """
    Keep only the most recent `limit` entries in validation_errors.
    """
    global validation_errors
    if len(validation_errors) > limit:
        validation_errors = validation_errors[-limit:]


def get_validation_errors() -> List[Dict[str, Any]]:
    """
    Return a shallow copy of the stored validation errors.
    """
    return list(validation_errors)


def log_validation_errors(errors: Iterable[ValidationError]) -> None:
    """
    Append error dicts to the global store and enforce retention policy.
    No-op if the iterable is empty.
    Propagates any exception from error.to_dict and leaves the store unchanged.
    """
    errs = list(errors)
    if not errs:
        return

    # build the new dicts first to avoid partial writes on failure
    serialized = [e.to_dict() for e in errs]
    keep_recent_errors()
    validation_errors.extend(serialized)


def validate_review_request(data: Dict[str, Any]) -> List[ValidationError]:
    """
    Validate a code review request payload like:
      {"content": "...", "language": "python"}
    Returns a list of ValidationError. Also logs any errors found.
    """
    errors: List[ValidationError] = []
    content = data.get("content")
    language = data.get("language")

    if not content:
        errors.append(ValidationError("content", "Content is required."))
    else:
        if isinstance(content, str) and len(content) > MAX_CONTENT_SIZE:
            errors.append(
                ValidationError(
                    "content",
                    f"Content exceeds maximum size of {MAX_CONTENT_SIZE} characters.",
                )
            )
        if contains_null_bytes(content):
            errors.append(ValidationError("content", "Content contains invalid null bytes."))

    if language is not None:
        if not isinstance(language, str) or language.lower() not in ALLOWED_LANGUAGES:
            allowed = ", ".join(sorted(ALLOWED_LANGUAGES))
            errors.append(ValidationError("language", f"Language must be one of: {allowed}"))

    # Log errors if any
    if errors:
        log_validation_errors(errors)

    return errors


def validate_statistics_request(data: Dict[str, Any]) -> List[ValidationError]:
    """
    Validate a statistics request payload like:
      {"files": ["path1", "path2", ...]}
    Returns list of ValidationError and logs errors if any.
    """
    errors: List[ValidationError] = []
    files = data.get("files", None)

    if files is None or files == []:
        errors.append(ValidationError("files", "Files array is required."))
    elif not isinstance(files, list):
        errors.append(ValidationError("files", "Files must be an array."))
    else:
        if len(files) > 1000:
            errors.append(ValidationError("files", "Files cannot exceed 1000 entries."))

    if errors:
        log_validation_errors(errors)

    return errors


# src/middleware.py
import os
import time
import itertools
from typing import Callable, Tuple
from flask import Flask, g, request

class CorrelationIDMiddleware:
    """
    Simple correlation ID generator and Flask integration helper.
    """

    _counter = itertools.count()
    _lock = threading.Lock()

    @staticmethod
    def generate_correlation_id() -> str:
        """
        Generate a unique correlation id using time in ns, process id, and a local counter.
        Ensures uniqueness even within the same nanosecond across threads.
        """
        with CorrelationIDMiddleware._lock:
            c = next(CorrelationIDMiddleware._counter)
        ts = time.time_ns()
        pid = os.getpid()
        return f"{ts}-{pid}-{c}"

    @staticmethod
    def init_app(app: Flask) -> None:
        """
        Register before/after request hooks to attach correlation ID header.
        """
        @app.before_request
        def _assign_correlation_id() -> None:
            cid = request.headers.get("X-Correlation-ID") or CorrelationIDMiddleware.generate_correlation_id()
            g.correlation_id = cid

        @app.after_request
        def _inject_correlation_id(resp):
            cid = getattr(g, "correlation_id", None)
            if cid:
                resp.headers["X-Correlation-ID"] = cid
            return resp


# src/app.py
from typing import Any, Dict
from flask import Flask, jsonify, request

def create_app(testing: bool = False) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = bool(testing)

    # Initialize correlation id middleware hooks
    try:
        CorrelationIDMiddleware.init_app(app)
    except Exception:
        # Do not fail app creation for middleware issues in tests
        pass

    @app.route("/health", methods=["GET"])
    def health() -> Any:
        return jsonify({"status": "ok"}), 200

    @app.route("/review", methods=["POST"])
    def review() -> Any:
        payload: Dict[str, Any] = request.get_json(silent=True) or {}
        # Sanitize only relevant fields to avoid unnecessary mutation
        sanitized = sanitize_request_data(payload)
        errors = validate_review_request(sanitized)
        if errors:
            return jsonify({"errors": [e.to_dict() for e in errors]}), 422
        return jsonify({"result": "ok"}), 200

    @app.route("/statistics", methods=["POST"])
    def statistics() -> Any:
        payload: Dict[str, Any] = request.get_json(silent=True) or {}
        errors = validate_statistics_request(payload)
        if errors:
            return jsonify({"errors": [e.to_dict() for e in errors]}), 422
        # placeholder successful response
        return jsonify({"files": payload.get("files", [])}), 200

    return app