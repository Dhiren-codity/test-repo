import time
import re
from datetime import datetime, timedelta
from threading import Lock
from typing import Dict, List, Optional

CORRELATION_ID_HEADER = 'X-Correlation-ID'

trace_storage: Dict[str, List[Dict]] = {}
trace_lock = Lock()
valid_id_regex = re.compile(r'^[\w\-]+$')


class CorrelationIDMiddleware:
    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        app.before_request(self.before_request)
        app.after_request(self.after_request)
        app.correlation_start_time = None

    def before_request(self):
        from flask import request, g

        correlation_id = self.extract_or_generate_correlation_id(request)
        g.correlation_id = correlation_id
        g.request_start_time = time.time()

    def after_request(self, response):
        from flask import request, g

        correlation_id = getattr(g, 'correlation_id', None)
        if correlation_id:
            response.headers[CORRELATION_ID_HEADER] = correlation_id

            start_time = getattr(g, 'request_start_time', time.time())
            duration_ms = (time.time() - start_time) * 1000

            trace_data = {
                'service': 'python-reviewer',
                'method': request.method,
                'path': request.path,
                'timestamp': datetime.now().isoformat(),
                'correlation_id': correlation_id,
                'duration_ms': round(duration_ms, 2),
                'status': response.status_code
            }

            store_trace(correlation_id, trace_data)

        return response

    def extract_or_generate_correlation_id(self, request) -> str:
        existing_id = request.headers.get(CORRELATION_ID_HEADER)
        if existing_id and self.is_valid_correlation_id(existing_id):
            return existing_id
        return self.generate_correlation_id()

    @staticmethod
    def generate_correlation_id() -> str:
        return f"{int(time.time())}-py-{int(time.time() * 1000000) % 100000}"

    @staticmethod
    def is_valid_correlation_id(id_str: str) -> bool:
        if not isinstance(id_str, str):
            return False
        if len(id_str) < 10 or len(id_str) > 100:
            return False
        return bool(valid_id_regex.match(id_str))


def store_trace(correlation_id: str, trace_data: Dict):
    with trace_lock:
        if correlation_id not in trace_storage:
            trace_storage[correlation_id] = []
        trace_storage[correlation_id].append(trace_data)
        cleanup_old_traces()


def cleanup_old_traces():
    cutoff_time = datetime.now() - timedelta(hours=1)
    to_delete = []

    for correlation_id, traces in trace_storage.items():
        if traces:
            oldest_trace_time = datetime.fromisoformat(traces[0]['timestamp'])
            if oldest_trace_time < cutoff_time:
                to_delete.append(correlation_id)

    for correlation_id in to_delete:
        del trace_storage[correlation_id]


def get_traces(correlation_id: str) -> List[Dict]:
    with trace_lock:
        return trace_storage.get(correlation_id, []).copy()


def get_all_traces() -> Dict[str, List[Dict]]:
    with trace_lock:
        return {k: v.copy() for k, v in trace_storage.items()}
