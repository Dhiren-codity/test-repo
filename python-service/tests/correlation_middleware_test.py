from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

try:
    # Optional import; actual Flask objects are accessed lazily inside methods
    import flask  # noqa: F401
except Exception:
    # Tests monkeypatch a fake 'flask' module; absence at import time is fine.
    pass

# Public constants and storage
CORRELATION_ID_HEADER = "X-Correlation-ID"
trace_storage: Dict[str, List[Dict[str, Any]]] = {}
trace_lock = threading.Lock()


class CorrelationIDMiddleware:
    def __init__(self, app: Any | None = None) -> None:
        self.app = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Any) -> None:
        # Register hooks with the app
        self.app = app
        if hasattr(app, "before_request"):
            app.before_request(self.before_request)
        if hasattr(app, "after_request"):
            app.after_request(self.after_request)
        # Initialize attribute as per tests
        setattr(app, "correlation_start_time", None)

    def is_valid_correlation_id(self, cid: Any) -> bool:
        if not isinstance(cid, str):
            return False
        if not (10 <= len(cid) <= 100):
            return False
        # Allowed: letters, digits, underscore, hyphen
        return re.fullmatch(r"[A-Za-z0-9_-]{10,100}", cid) is not None

    def generate_correlation_id(self) -> str:
        # Digits - py - digits
        now_ms = int(time.time() * 1000)
        # Use time-based component for the suffix as well to keep it deterministic-ish
        # but still numeric. Add a rolling counter based on monotonic to diversify.
        suffix = int(time.monotonic() * 1_000_000)
        return f"{now_ms}-py-{suffix}"

    def extract_or_generate_correlation_id(self, request: Any) -> str:
        inbound = None
        try:
            inbound = request.headers.get(CORRELATION_ID_HEADER)
        except Exception:
            inbound = None

        if inbound and self.is_valid_correlation_id(inbound):
            return inbound
        return self.generate_correlation_id()

    def before_request(self) -> None:
        # Import here to cooperate with monkeypatch in tests
        from flask import g, request

        cid = self.extract_or_generate_correlation_id(request)
        setattr(g, "correlation_id", cid)
        setattr(g, "request_start_time", time.time())

    def after_request(self, response: Any) -> Any:
        # Import here to cooperate with monkeypatch in tests
        from flask import g, request

        cid = getattr(g, "correlation_id", None)
        if not cid:
            return response

        # Set outbound header
        try:
            response.headers[CORRELATION_ID_HEADER] = cid
        except Exception:
            # If response doesn't support headers mapping, just return
            return response

        start = getattr(g, "request_start_time", None)
        now = time.time()
        duration_ms = None
        if isinstance(start, (int, float)):
            # Round to 1 decimal place to avoid FP artifacts; tests expect exact 100.0 in sample
            duration_ms = round((now - start) * 1000.0, 1)

        trace_data = {
            "service": "python-reviewer",
            "method": getattr(request, "method", None),
            "path": getattr(request, "path", None),
            "timestamp": datetime.now().isoformat(),
            "correlation_id": cid,
            "duration_ms": duration_ms,
            "status": getattr(response, "status_code", None),
        }
        store_trace(cid, trace_data)
        return response


def store_trace(correlation_id: str, data: Dict[str, Any]) -> None:
    with trace_lock:
        trace_storage.setdefault(correlation_id, []).append(dict(data))


def get_traces(correlation_id: str) -> List[Dict[str, Any]]:
    with trace_lock:
        # Return a shallow copy of the list (items themselves needn't be deep-copied for tests)
        return list(trace_storage.get(correlation_id, []))


def get_all_traces() -> Dict[str, List[Dict[str, Any]]]:
    with trace_lock:
        # Return a copy of the mapping with copied lists
        return {cid: list(traces) for cid, traces in trace_storage.items()}


def cleanup_old_traces() -> None:
    cutoff = datetime.now() - timedelta(hours=1)
    to_delete: List[str] = []
    with trace_lock:
        for cid, traces in list(trace_storage.items()):
            if not traces:
                continue
            # Parse timestamps; raise ValueError if invalid to satisfy tests
            try:
                oldest = min(datetime.fromisoformat(t.get("timestamp", "")) for t in traces)
            except Exception as e:
                # Re-raise as ValueError as expected by tests
                raise ValueError("Invalid timestamp format in traces") from e

            if oldest < cutoff:
                to_delete.append(cid)

        for cid in to_delete:
            trace_storage.pop(cid, None)