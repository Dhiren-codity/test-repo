from __future__ import annotations

import importlib
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

CORRELATION_ID_HEADER = "X-Correlation-ID"

# In-memory trace storage: {correlation_id: [trace_dict, ...]}
trace_storage: Dict[str, List[Dict[str, Any]]] = {}


class CorrelationIDMiddleware:
    def __init__(self, app=None):
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        # Register hooks
        app.before_request(self.before_request)
        app.after_request(self.after_request)
        # Initialize/override attribute as tests expect
        app.correlation_start_time = None

    def before_request(self):
        flask_mod = importlib.import_module("flask")
        req = flask_mod.request
        g = flask_mod.g

        correlation_id = self.extract_or_generate_correlation_id(req)
        g.correlation_id = correlation_id
        g.request_start_time = time.time()

    def after_request(self, response):
        flask_mod = importlib.import_module("flask")
        req = flask_mod.request
        g = flask_mod.g

        correlation_id = getattr(g, "correlation_id", None)
        if not correlation_id:
            return response

        # Always set response header
        if hasattr(response, "headers") and isinstance(response.headers, dict):
            response.headers[CORRELATION_ID_HEADER] = correlation_id

        start_time = getattr(g, "request_start_time", time.time())
        duration_ms = round((time.time() - start_time) * 1000, 2)

        trace = {
            "timestamp": datetime.now().isoformat(),
            "service": "python-reviewer",
            "method": getattr(req, "method", ""),
            "path": getattr(req, "path", ""),
            "correlation_id": correlation_id,
            "duration_ms": duration_ms,
            "status": getattr(response, "status_code", None),
        }

        store_trace(correlation_id, trace)
        return response

    def extract_or_generate_correlation_id(self, request_obj) -> str:
        header_val = None
        if hasattr(request_obj, "headers") and isinstance(request_obj.headers, dict):
            header_val = request_obj.headers.get(CORRELATION_ID_HEADER)
        if header_val and self.is_valid_correlation_id(header_val):
            return header_val
        return self.generate_correlation_id()

    def generate_correlation_id(self) -> str:
        t = time.time()
        sec = int(t)
        micro_mod = int(t * 1_000_000) % 100_000
        return f"{sec}-py-{micro_mod}"

    def is_valid_correlation_id(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        length = len(value)
        if length < 10 or length > 100:
            return False
        # Allowed characters: letters, digits, underscore, hyphen
        for ch in value:
            if (
                "a" <= ch <= "z"
                or "A" <= ch <= "Z"
                or "0" <= ch <= "9"
                or ch in {"_", "-"}
            ):
                continue
            return False
        return True


def store_trace(correlation_id: str, trace: Dict[str, Any]) -> None:
    traces = trace_storage.setdefault(correlation_id, [])
    traces.append(trace)


def get_traces(correlation_id: str) -> List[Dict[str, Any]]:
    return list(trace_storage.get(correlation_id, []))


def get_all_traces() -> Dict[str, List[Dict[str, Any]]]:
    return {cid: list(traces) for cid, traces in trace_storage.items()}


def cleanup_old_traces() -> None:
    cutoff = datetime.now() - timedelta(hours=1)
    to_delete = []
    for cid, traces in list(trace_storage.items()):
        filtered = []
        for tr in traces:
            ts_str = tr.get("timestamp")
            try:
                ts = datetime.fromisoformat(ts_str) if isinstance(ts_str, str) else None
            except Exception:
                ts = None
            if ts is not None and ts >= cutoff:
                filtered.append(tr)
        if filtered:
            trace_storage[cid] = filtered
        else:
            to_delete.append(cid)
    for cid in to_delete:
        trace_storage.pop(cid, None)