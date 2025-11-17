from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

# Public constants
MAX_CONTENT_SIZE = 10000

# Internal store for validation errors (list of dicts)
_validation_errors_store: List[Dict[str, str]] = []


@dataclass
class ValidationError:
    field: str
    reason: str
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            # timestamp is patched in tests via src.request_validator.datetime
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, str]:
        return {
            "field": self.field,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


def contains_null_bytes(value: Optional[str]) -> bool:
    if value is None:
        return False
    return "\x00" in value


def contains_path_traversal(path: Optional[str]) -> bool:
    if not path:
        return False
    s = str(path).strip()
    # Detect common traversal indicators
    if ".." in s:
        return True
    if s.startswith("~") or s.startswith("~/") or s.startswith("~\\"):
        return True
    return False


def sanitize_input(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        # Remove ASCII control chars except LF (10), CR (13), TAB (9)
        keep = {9, 10, 13}
        return "".join(ch for ch in value if (32 <= ord(ch) <= 126) or (ord(ch) in keep))
    # Let __str__ errors propagate as per tests
    return str(value)


def sanitize_request_data(data: Dict[str, Any]) -> Dict[str, Any]:
    sanitized: Dict[str, Any] = dict(data)
    # Sanitize 'content'
    if "content" in sanitized and isinstance(sanitized["content"], str):
        sanitized["content"] = sanitize_input(sanitized["content"])
    # Sanitize 'language'
    if "language" in sanitized and isinstance(sanitized["language"], str):
        sanitized["language"] = sanitize_input(sanitized["language"])
    # Sanitize 'path' - remove control chars and also strip path separators
    if "path" in sanitized and isinstance(sanitized["path"], str):
        cleaned = sanitize_input(sanitized["path"]) or ""
        # Remove common path separators entirely
        cleaned = cleaned.replace("/", "").replace("\\", "")
        sanitized["path"] = cleaned
    return sanitized


def log_validation_errors(errors: List[ValidationError]) -> None:
    # Only log when there are errors
    if not errors:
        return
    # Append to internal store as dicts
    for err in errors:
        _validation_errors_store.append(err.to_dict())
    keep_recent_errors()


def keep_recent_errors(limit: int = 100) -> None:
    """Keep only the most recent 'limit' errors in the global store."""
    global _validation_errors_store
    excess = len(_validation_errors_store) - limit
    if excess > 0:
        _validation_errors_store = _validation_errors_store[excess:]


def get_validation_errors() -> List[Dict[str, str]]:
    # Return a shallow copy to avoid external mutation of internal list
    return list(_validation_errors_store)


def clear_validation_errors() -> None:
    _validation_errors_store.clear()


def validate_review_request(data: Dict[str, Any]) -> List[ValidationError]:
    errors: List[ValidationError] = []

    content = data.get("content")
    language = data.get("language")

    # content is required
    if content is None or (isinstance(content, str) and content.strip() == ""):
        errors.append(ValidationError(field="content", reason="Content is required"))
    else:
        # Content size check
        try:
            length = len(content)
        except Exception:
            length = MAX_CONTENT_SIZE + 1  # Force error if not measurable
        if length > MAX_CONTENT_SIZE:
            errors.append(
                ValidationError(
                    field="content",
                    reason=f"Content size cannot exceed {MAX_CONTENT_SIZE} characters",
                )
            )
        # Null byte check
        if isinstance(content, str) and contains_null_bytes(content):
            errors.append(
                ValidationError(field="content", reason="Content contains null bytes")
            )

    # Language validation (optional but if provided must be valid)
    allowed_languages = {
        "python",
        "javascript",
        "typescript",
        "java",
        "go",
        "ruby",
        "c",
        "cpp",
        "rust",
        "bash",
        "shell",
        "csharp",
        "php",
        "scala",
        "swift",
    }
    if language is not None:
        if not isinstance(language, str):
            errors.append(
                ValidationError(field="language", reason="Language must be a string")
            )
        else:
            lang = language.strip().lower()
            if lang not in allowed_languages:
                allowed_list = ", ".join(sorted(allowed_languages))
                errors.append(
                    ValidationError(
                        field="language",
                        reason=f"Language must be one of: {allowed_list}",
                    )
                )

    # Always call logger as per tests, even with empty list
    log_validation_errors(errors)
    return errors


def validate_statistics_request(data: Dict[str, Any]) -> List[ValidationError]:
    errors: List[ValidationError] = []

    if "files" not in data:
        errors.append(ValidationError(field="files", reason="Files is required"))
        log_validation_errors(errors)
        return errors

    files = data.get("files")

    if not isinstance(files, list):
        errors.append(ValidationError(field="files", reason="Files must be an array"))
        log_validation_errors(errors)
        return errors

    if len(files) == 0:
        errors.append(
            ValidationError(field="files", reason="Files array cannot be empty")
        )
        log_validation_errors(errors)
        return errors

    if len(files) > 1000:
        errors.append(
            ValidationError(field="files", reason="Files array cannot exceed 1000")
        )
    # Additional optional validations could be added here (null bytes, traversal, etc.)

    log_validation_errors(errors)
    return errors


# src/correlation_middleware.py
# Minimal correlation middleware and helpers to satisfy import/collection in tests.
# Designed to be framework-agnostic and safe to import without optional dependencies.
import uuid
import contextvars
from typing import Callable, Iterable, Tuple, Awaitable

# Public header constant
CORRELATION_ID_HEADER = "X-Correlation-ID"

# Context variable to store current correlation id
_correlation_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "correlation_id", default=None
)

# In-memory traces store keyed by correlation id
_traces_store: Dict[str, List[Dict[str, Any]]] = {}


def generate_correlation_id() -> str:
    return str(uuid.uuid4())


def get_correlation_id() -> Optional[str]:
    return _correlation_id_var.get()


def set_correlation_id(value: Optional[str]) -> None:
    _correlation_id_var.set(value)


def clear_correlation_id() -> None:
    _correlation_id_var.set(None)


def add_trace(event: Dict[str, Any], correlation_id: Optional[str] = None) -> str:
    cid = correlation_id or get_correlation_id() or generate_correlation_id()
    _traces_store.setdefault(cid, []).append(dict(event))
    # Ensure context has it for callers
    set_correlation_id(cid)
    return cid


def get_traces(correlation_id: str) -> List[Dict[str, Any]]:
    return list(_traces_store.get(correlation_id, []))


def clear_traces() -> None:
    _traces_store.clear()


class WSGICorrelationIdMiddleware:
    def __init__(self, app: Callable):
        self.app = app

    def __call__(self, environ: Dict[str, Any], start_response: Callable):
        # Read correlation id from headers if present
        header_key = "HTTP_" + CORRELATION_ID_HEADER.upper().replace("-", "_")
        cid = environ.get(header_key)
        if not cid or not isinstance(cid, str):
            cid = generate_correlation_id()
            environ[header_key] = cid

        token = _correlation_id_var.set(cid)

        def srw(status: str, headers: List[Tuple[str, str]], exc_info=None):
            # Inject header in response
            headers = headers or []
            # Ensure header not duplicated
            filtered = [(k, v) for (k, v) in headers if k.lower() != CORRELATION_ID_HEADER.lower()]
            filtered.append((CORRELATION_ID_HEADER, cid))
            return start_response(status, filtered, exc_info)

        try:
            result = self.app(environ, srw)
            return result
        finally:
            _correlation_id_var.reset(token)


class ASGICorrelationIdMiddleware:
    def __init__(self, app: Callable):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # Extract incoming headers
        headers = scope.get("headers") or []
        cid = None
        for k, v in headers:
            try:
                if k.decode("latin1").lower() == CORRELATION_ID_HEADER.lower():
                    cid = v.decode("latin1")
                    break
            except Exception:
                continue

        if not cid:
            cid = generate_correlation_id()

        token = _correlation_id_var.set(cid)

        async def send_wrapper(message):
            if message.get("type") == "http.response.start":
                hdrs = message.setdefault("headers", [])
                # Remove existing header with same name
                hdrs = [
                    (k, v)
                    for (k, v) in hdrs
                    if k.decode("latin1").lower() != CORRELATION_ID_HEADER.lower()
                ]
                hdrs.append(
                    (
                        CORRELATION_ID_HEADER.encode("latin1"),
                        cid.encode("latin1"),
                    )
                )
                message["headers"] = hdrs
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _correlation_id_var.reset(token)


class CorrelationIdMiddleware:
    """
    Middleware that can act as WSGI or ASGI based on how it's invoked.
    For WSGI, __call__ receives (environ, start_response).
    For ASGI, __call__ is awaited with (scope, receive, send).
    """

    def __init__(self, app: Callable):
        self.wsgi = WSGICorrelationIdMiddleware(app)
        self.asgi = ASGICorrelationIdMiddleware(app)

    def __call__(self, *args, **kwargs):
        # WSGI usage: (environ, start_response)
        if len(args) >= 2 and callable(args[1]):
            return self.wsgi(*args, **kwargs)

        # Assume ASGI usage, return awaitable
        return self.asgi(*args, **kwargs)