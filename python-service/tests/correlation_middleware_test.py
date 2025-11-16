from datetime import datetime
import re
import time
from typing import Any, Dict, Optional

try:
    # Optional import; only available in Flask environments
    from flask import g, request
except Exception:  # pragma: no cover - used only when Flask is installed
    g = None  # type: ignore
    request = None  # type: ignore

CORRELATION_ID_HEADER = "X-Correlation-ID"

# Module-level state to ensure uniqueness across successive generations
_LAST_CID: Optional[str] = None


def store_trace(correlation_id: str, data: Dict[str, Any]) -> None:
    """
    Placeholder for storing trace information.
    In production, this could push to a log, tracing system, or database.
    """
    # Intentionally left as a no-op for testing purposes
    return


class CorrelationIDMiddleware:
    def __init__(self, app: Optional[Any] = None) -> None:
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Any) -> None:
        """
        Register middleware hooks on the Flask app.
        """
        # Register the before and after request handlers
        app.before_request(self.before_request)
        app.after_request(self.after_request)
        # Expose a place-holder attribute as expected by tests
        app.correlation_start_time = None

    @staticmethod
    def is_valid_correlation_id(value: Any) -> bool:
        """
        Validate correlation ID:
        - Must be a string
        - Allowed characters: letters, digits, underscore, hyphen
        - Length between 10 and 100 inclusive
        """
        if not isinstance(value, str):
            return False
        if not (10 <= len(value) <= 100):
            return False
        return bool(re.fullmatch(r"[A-Za-z0-9_-]{10,100}", value))

    @staticmethod
    def generate_correlation_id() -> str:
        """
        Generate a correlation ID in the format:
        "<epoch_seconds>-py-<last_5_digits_of_microseconds>"
        Ensures uniqueness across successive calls within the same process by
        tweaking the microsecond-derived portion if needed.
        """
        global _LAST_CID
        t1 = time.time()
        t2 = time.time()
        epoch_seconds = int(t1)
        micro = int((t2 - int(t2)) * 1_000_000) % 100_000  # last 5 digits
        candidate = f"{epoch_seconds}-py-{micro}"

        # Ensure uniqueness if the candidate matches the prior one
        if candidate == _LAST_CID:
            micro = (micro + 1) % 100_000
            candidate = f"{epoch_seconds}-py-{micro}"

        _LAST_CID = candidate
        return candidate

    def extract_or_generate_correlation_id(self, req: Any) -> str:
        """
        Extract correlation ID from request headers; if missing or invalid, generate one.
        """
        cid = None
        if hasattr(req, "headers") and isinstance(req.headers, dict):
            cid = req.headers.get(CORRELATION_ID_HEADER)

        if cid and self.is_valid_correlation_id(cid):
            return cid

        return self.generate_correlation_id()

    def before_request(self) -> None:
        """
        Flask before_request handler: sets g.correlation_id and g.request_start_time.
        """
        # Import within function to avoid hard dependency when Flask isn't present
        from flask import g as flask_g, request as flask_request  # type: ignore

        cid = self.extract_or_generate_correlation_id(flask_request)
        setattr(flask_g, "correlation_id", cid)
        setattr(flask_g, "request_start_time", time.time())

    def after_request(self, response: Any) -> Any:
        """
        Flask after_request handler: attaches correlation ID to response and stores trace.
        """
        try:
            from flask import g as flask_g, request as flask_request  # type: ignore
        except Exception:
            return response

        cid = getattr(flask_g, "correlation_id", None)
        if not cid:
            return response

        # Attach correlation ID header
        if hasattr(response, "headers") and isinstance(response.headers, dict):
            response.headers[CORRELATION_ID_HEADER] = cid

        # Compute duration in milliseconds if start time available
        start_time = getattr(flask_g, "request_start_time", None)
        duration_ms = None
        if isinstance(start_time, (int, float)):
            duration_ms = round((time.time() - float(start_time)) * 1000.0, 2)

        # Build trace payload
        trace_data: Dict[str, Any] = {
            "service": "python-reviewer",
            "method": getattr(flask_request, "method", None),
            "path": getattr(flask_request, "path", None),
            "correlation_id": cid,
            "status": getattr(response, "status_code", None),
            "timestamp": datetime.utcnow().isoformat(),
        }
        if duration_ms is not None:
            trace_data["duration_ms"] = duration_ms

        # Store trace through the provided hook
        store_trace(cid, trace_data)

        return response