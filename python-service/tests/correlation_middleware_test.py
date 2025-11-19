from datetime import datetime, timedelta
import os
import re
import time
from typing import Dict, List, Any

from flask import Flask, g, request, Response

# Public constants and storage
CORRELATION_ID_HEADER = "X-Correlation-ID"
trace_storage: Dict[str, List[Dict[str, Any]]] = {}


def store_trace(correlation_id: str, trace_data: Dict[str, Any]) -> None:
    """Store a copy of the trace data for a given correlation ID."""
    if correlation_id not in trace_storage:
        trace_storage[correlation_id] = []
    # Store a shallow copy to avoid external mutation affecting storage
    trace_storage[correlation_id].append(dict(trace_data))


def get_traces(correlation_id: str) -> List[Dict[str, Any]]:
    """Return a copy of the traces for a given correlation ID."""
    traces = trace_storage.get(correlation_id, [])
    return [dict(item) for item in traces]


def get_all_traces() -> Dict[str, List[Dict[str, Any]]]:
    """Return a shallow copy of the entire trace storage."""
    return {cid: [dict(item) for item in traces] for cid, traces in trace_storage.items()}


def cleanup_old_traces(hours: int = 1) -> None:
    """Remove trace entries older than the specified number of hours (default 1 hour)."""
    cutoff = datetime.now() - timedelta(hours=hours)
    to_delete = []
    for cid, traces in list(trace_storage.items()):
        new_traces = []
        for t in traces:
            try:
                ts = datetime.fromisoformat(t.get("timestamp"))
            except Exception:
                # If malformed timestamp, treat as old and skip keeping it
                continue
            if ts >= cutoff:
                new_traces.append(t)
        if new_traces:
            trace_storage[cid] = new_traces
        else:
            to_delete.append(cid)
    for cid in to_delete:
        trace_storage.pop(cid, None)


class CorrelationIDMiddleware:
    def __init__(self, app: Flask | None = None) -> None:
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Flask) -> None:
        # Set an attribute on app as required by tests
        setattr(app, "correlation_start_time", None)
        app.before_request(self.before_request)
        app.after_request(self.after_request)

    # Validation rules: 10-100 chars, alphanumeric, hyphen, underscore
    _cid_pattern = re.compile(r"^[A-Za-z0-9_-]{10,100}$")

    def is_valid_correlation_id(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        if not (10 <= len(value) <= 100):
            return False
        return self._cid_pattern.match(value) is not None

    def generate_correlation_id(self) -> str:
        # Format: "<unix_timestamp>-py-<pid>" where pid is 1-5 digits
        ts = int(time.time())
        pid = os.getpid() % 100000  # ensure up to 5 digits
        return f"{ts}-py-{pid}"

    def extract_or_generate_correlation_id(self, req) -> str:
        incoming = None
        try:
            incoming = req.headers.get(CORRELATION_ID_HEADER)
        except Exception:
            incoming = None
        if incoming and self.is_valid_correlation_id(incoming):
            return incoming
        return self.generate_correlation_id()

    def before_request(self) -> None:
        # Set correlation ID and start time for the request
        g.correlation_id = self.extract_or_generate_correlation_id(request)
        g.request_start_time = time.time()

    def after_request(self, response: Response) -> Response:
        # If correlation_id missing from g, do nothing
        cid = getattr(g, "correlation_id", None)
        if not cid:
            return response

        # Set header on the response
        response.headers[CORRELATION_ID_HEADER] = cid

        # Calculate duration and store the trace (no internal exception handling as per test)
        start_time = getattr(g, "request_start_time", None)
        if start_time is not None:
            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000.0
        else:
            duration_ms = 0.0

        trace_data = {
            "service": "python-reviewer",
            "method": request.method,
            "path": request.path,
            "timestamp": datetime.now().isoformat(),
            "correlation_id": cid,
            "duration_ms": duration_ms,
            "status": getattr(response, "status_code", None),
        }
        store_trace(cid, trace_data)
        return response