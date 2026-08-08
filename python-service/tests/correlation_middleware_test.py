from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Dict, List, Mapping, Optional

from flask import Flask, g, request

# Public header name for correlation ID
CORRELATION_ID_HEADER = "X-Correlation-ID"

# Simple in-memory storage for traces, keyed by correlation_id
trace_storage: Dict[str, List[Dict[str, Any]]] = {}

# Constant service name used in traces
SERVICE_NAME = "python-reviewer"


def store_trace(correlation_id: str, trace: Mapping[str, Any]) -> None:
    """
    Store a trace entry for a given correlation ID.
    Appends to the list of traces under that correlation ID.
    """
    traces = trace_storage.setdefault(correlation_id, [])
    traces.append(dict(trace))  # store a copy to avoid external mutation


def get_traces(correlation_id: str) -> List[Dict[str, Any]]:
    """
    Return a shallow copy of trace list for given correlation_id to avoid external mutation.
    """
    return list(trace_storage.get(correlation_id, []))


def get_all_traces() -> Dict[str, List[Dict[str, Any]]]:
    """
    Return a shallow copy of the entire trace storage, with copies of lists to prevent external mutation.
    """
    return {cid: list(traces) for cid, traces in trace_storage.items()}


def cleanup_old_traces(hours: int = 1) -> None:
    """
    Remove traces older than the specified number of hours.
    If all traces for a correlation ID are old, remove the key entirely.
    """
    cutoff = datetime.now() - timedelta(hours=hours)
    to_delete: List[str] = []
    for cid, traces in list(trace_storage.items()):
        new_traces: List[Dict[str, Any]] = []
        for t in traces:
            ts_str = t.get("timestamp")
            try:
                ts = datetime.fromisoformat(ts_str) if isinstance(ts_str, str) else None
            except Exception:
                ts = None
            # If timestamp is missing or invalid, keep it to avoid accidental data loss
            if ts is None or ts >= cutoff:
                new_traces.append(t)
        if new_traces:
            trace_storage[cid] = new_traces
        else:
            to_delete.append(cid)
    for cid in to_delete:
        trace_storage.pop(cid, None)


def inject_correlation_id(func):
    """
    Decorator that injects the current request correlation id (from flask.g) into the wrapped function
    as a keyword argument named 'cid' if not already provided.
    """
    @wraps(func)
    def _inject(*args, **kwargs):
        if "cid" not in kwargs:
            kwargs["cid"] = getattr(g, "correlation_id", None)
        return func(*args, **kwargs)

    return _inject


class CorrelationIDMiddleware:
    def __init__(self, app: Optional[Flask] = None) -> None:
        self.app: Optional[Flask] = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Flask) -> None:
        """
        Register before and after request handlers and initialize app-level attributes.
        """
        self.app = app
        # Register hooks
        app.before_request(self.before_request)
        app.after_request(self.after_request)
        # For tests: ensure attribute exists
        setattr(app, "correlation_start_time", None)

    def before_request(self) -> None:
        """
        Extract or generate correlation ID and record request start time.
        """
        g.request_start_time = time.time()
        g.correlation_id = self.extract_or_generate_correlation_id(request)

    def after_request(self, response):
        """
        Add correlation header to response and store a trace entry.
        """
        correlation_id = getattr(g, "correlation_id", None)
        if not correlation_id:
            return response

        # Echo correlation id in response header
        response.headers[CORRELATION_ID_HEADER] = correlation_id

        # Compute duration
        start = getattr(g, "request_start_time", None)
        now = time.time()
        duration_ms = 0.0
        if isinstance(start, (int, float)):
            duration_ms = max(0.0, (now - float(start)) * 1000.0)

        # Build trace entry
        trace = {
            "timestamp": datetime.now().isoformat(),
            "path": request.path,
            "method": request.method,
            "service": SERVICE_NAME,
            "correlation_id": correlation_id,
            "duration_ms": duration_ms,
            "status": getattr(response, "status_code", None),
        }

        # Store trace
        store_trace(correlation_id, trace)

        return response

    def extract_or_generate_correlation_id(self, req) -> str:
        """
        Extract correlation id from request headers if valid; otherwise generate a new one.
        """
        incoming = None
        try:
            incoming = req.headers.get(CORRELATION_ID_HEADER)
        except Exception:
            incoming = None

        if isinstance(incoming, str) and self.is_valid_correlation_id(incoming):
            return incoming
        return self.generate_correlation_id()

    def generate_correlation_id(self) -> str:
        """
        Generate a correlation id with a predictable format that includes 'py' and hyphens.
        """
        # Use current time and a short monotonic fragment to ensure variability
        epoch = int(time.time())
        # Keep it simple and deterministic enough for tests
        rnd = int((time.perf_counter_ns() // 1000) % 100000)
        return f"{epoch}-py-{rnd:05d}"

    def is_valid_correlation_id(self, cid: Any) -> bool:
        """
        Validate correlation id:
        - Must be a string
        - Length between 10 and 100 characters
        - Only letters, numbers, hyphens, and underscores
        - No spaces or other special characters
        """
        if not isinstance(cid, str):
            return False
        if not (10 <= len(cid) <= 100):
            return False
        if not re.fullmatch(r"[A-Za-z0-9_-]+", cid):
            return False
        return True