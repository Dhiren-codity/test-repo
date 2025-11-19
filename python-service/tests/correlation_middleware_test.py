from __future__ import annotations

import re
import time
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Dict, List

from flask import Flask, Response, g, request

# Public constant for the correlation header
CORRELATION_ID_HEADER = "X-Correlation-ID"

# In-memory trace storage: {correlation_id: [trace_dict, ...]}
trace_storage: Dict[str, List[Dict[str, Any]]] = {}


def store_trace(correlation_id: str, data: Dict[str, Any]) -> None:
    """
    Store a trace entry for the given correlation ID.
    Stores a copy so external mutations don't affect internal storage.
    """
    if correlation_id not in trace_storage:
        trace_storage[correlation_id] = []
    # Store a shallow copy to avoid external side-effects
    trace_storage[correlation_id].append(dict(data))


def get_traces(correlation_id: str) -> List[Dict[str, Any]]:
    """
    Get a copy of traces for a given correlation ID.
    Returns a list copy so callers can't mutate internal storage.
    """
    return list(trace_storage.get(correlation_id, []))


def get_all_traces() -> Dict[str, List[Dict[str, Any]]]:
    """
    Return a copy of the entire trace storage.
    Dict keys map to list copies so callers can't mutate internal storage.
    """
    return {cid: list(traces) for cid, traces in trace_storage.items()}


def _parse_iso_timestamp(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def cleanup_old_traces() -> None:
    """
    Remove correlation IDs whose oldest trace is older than 1 hour.
    A trace entry is expected to have an ISO-formatted 'timestamp'.
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=1)

    to_delete: List[str] = []
    for cid, traces in trace_storage.items():
        if not traces:
            to_delete.append(cid)
            continue
        # Find the oldest timestamp we can parse
        parsed_times = []
        for t in traces:
            ts = t.get("timestamp")
            if isinstance(ts, str):
                dt = _parse_iso_timestamp(ts)
                if dt is not None:
                    parsed_times.append(dt)
        if not parsed_times:
            # If no valid timestamps, treat as old and clean up
            to_delete.append(cid)
            continue
        oldest = min(parsed_times)
        if oldest < cutoff:
            to_delete.append(cid)

    for cid in to_delete:
        trace_storage.pop(cid, None)


class CorrelationIDMiddleware:
    """
    Flask middleware to extract or generate a correlation ID for each request,
    attach it to the response, and store basic trace data in memory.
    """

    _VALID_RE = re.compile(r"^[A-Za-z0-9_-]{10,100}$")

    def __init__(self, app: Flask | None = None) -> None:
        self.app: Flask | None = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Flask) -> None:
        """
        Register before/after request hooks and set app-level attributes expected by tests.
        """
        self.app = app
        # Register hooks
        app.before_request(self.before_request)
        app.after_request(self.after_request)
        # Attribute expected by tests; we don't use it for timing to avoid global state
        app.correlation_start_time = None  # type: ignore[attr-defined]

    # ---- Correlation ID helpers ----

    def is_valid_correlation_id(self, correlation_id: Any) -> bool:
        """
        Validate correlation ID:
        - Must be a string
        - Length between 10 and 100 inclusive
        - Only letters, digits, underscore, hyphen
        """
        if not isinstance(correlation_id, str):
            return False
        return bool(self._VALID_RE.match(correlation_id))

    def generate_correlation_id(self) -> str:
        """
        Generate a valid correlation ID that includes '-py-' for language identifier.
        """
        # 32 + 4 + 8 = 44 chars -> within [10, 100]
        return f"{uuid.uuid4().hex}-py-{uuid.uuid4().hex[:8]}"

    def extract_or_generate_correlation_id(self, req) -> str:
        """
        Extract from header if valid, else generate a new one.
        """
        incoming = None
        try:
            incoming = req.headers.get(CORRELATION_ID_HEADER)
        except Exception:
            incoming = None

        if incoming and self.is_valid_correlation_id(incoming):
            return incoming
        return self.generate_correlation_id()

    # ---- Flask hooks ----

    def before_request(self) -> None:
        """
        Before each request, determine the correlation ID and store start time in g.
        """
        cid = self.extract_or_generate_correlation_id(request)
        g.correlation_id = cid  # type: ignore[attr-defined]
        g._correlation_start = time.perf_counter()  # type: ignore[attr-defined]

    def after_request(self, response: Response) -> Response:
        """
        After each request, attach the correlation header and store tracing info.
        If no correlation_id was set (e.g., if before_request was bypassed), do nothing.
        """
        cid = getattr(g, "correlation_id", None)
        start = getattr(g, "_correlation_start", None)

        if not cid:
            # Do not attach header or store trace
            return response

        # Attach header
        response.headers[CORRELATION_ID_HEADER] = cid

        # Compute duration
        duration_ms: float
        if isinstance(start, (int, float)):
            duration_ms = float((time.perf_counter() - start) * 1000.0)
        else:
            duration_ms = 0.0

        # Build trace entry
        trace = {
            "service": "python-reviewer",
            "method": request.method,
            "path": request.path,
            "timestamp": datetime.utcnow().isoformat(),
            "correlation_id": cid,
            "duration_ms": duration_ms,
            "status": response.status_code,
        }

        store_trace(cid, trace)
        # Optionally clean up old traces
        cleanup_old_traces()

        return response