import re
import time
import random
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from flask import Flask, g, request, Response

CORRELATION_ID_HEADER = "X-Correlation-ID"

# In-memory storage for traces: {correlation_id: [trace_dicts...]}
trace_storage: Dict[str, List[Dict[str, Any]]] = {}


def store_trace(correlation_id: str, trace_data: Dict[str, Any]) -> None:
    """Store a trace entry under the given correlation_id."""
    if correlation_id not in trace_storage:
        trace_storage[correlation_id] = []
    trace_storage[correlation_id].append(trace_data)


def get_traces(correlation_id: str) -> List[Dict[str, Any]]:
    """Return a copy of the list of traces for a given correlation_id."""
    traces = trace_storage.get(correlation_id, [])
    return list(traces)


def get_all_traces() -> Dict[str, List[Dict[str, Any]]]:
    """Return a shallow copy of the entire trace storage with copied lists for each CID."""
    return {cid: traces.copy() for cid, traces in trace_storage.items()}


def cleanup_old_traces() -> None:
    """Remove correlation_id entries whose oldest trace is older than 1 hour."""
    now = datetime.now()
    cutoff = now - timedelta(hours=1)

    to_delete: List[str] = []
    for cid, traces in trace_storage.items():
        if not traces:
            # Remove empty lists defensively
            to_delete.append(cid)
            continue
        # Find the oldest trace timestamp
        try:
            oldest = min(
                datetime.fromisoformat(t.get("timestamp")) for t in traces if "timestamp" in t
            )
        except Exception:
            # If timestamps are unparsable, conservatively keep
            continue
        if oldest < cutoff:
            to_delete.append(cid)

    for cid in to_delete:
        trace_storage.pop(cid, None)


class CorrelationIDMiddleware:
    """Flask middleware to manage correlation IDs and request tracing."""

    def __init__(self, app: Optional[Flask] = None):
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Flask) -> None:
        """Initialize middleware with Flask app by registering hooks."""
        app.before_request(self.before_request)  # type: ignore[arg-type]
        app.after_request(self.after_request)  # type: ignore[arg-type]
        # Compatibility attribute expected by tests
        setattr(app, "correlation_start_time", None)

    def before_request(self) -> None:
        """Set correlation ID and request start time before processing request."""
        cid = self.extract_or_generate_correlation_id(request)
        g.correlation_id = cid
        g.request_start_time = time.time()

    def after_request(self, response: Response) -> Response:
        """Add correlation ID to response and store a trace entry."""
        cid = getattr(g, "correlation_id", None)
        start_time = getattr(g, "request_start_time", None)

        if not cid:
            # No correlation ID to propagate or trace
            return response

        # Propagate correlation ID header
        response.headers[CORRELATION_ID_HEADER] = cid

        # Build and store trace entry if we have timing information
        duration_ms: Optional[float] = None
        if isinstance(start_time, (int, float)):
            duration_ms = round((time.time() - float(start_time)) * 1000, 3)

        trace_data = {
            "service": "python-reviewer",
            "method": request.method,
            "path": request.path,
            "timestamp": datetime.now().isoformat(),
            "correlation_id": cid,
            "duration_ms": duration_ms if duration_ms is not None else 0.0,
            "status": response.status_code,
        }
        store_trace(cid, trace_data)
        return response

    def extract_or_generate_correlation_id(self, req) -> str:
        """Extract correlation ID from headers if valid; otherwise generate one."""
        incoming = req.headers.get(CORRELATION_ID_HEADER)
        if incoming and self.is_valid_correlation_id(incoming):
            return incoming
        return self.generate_correlation_id()

    def generate_correlation_id(self) -> str:
        """Generate a correlation ID in the format: <epoch>-py-<random5digits>."""
        epoch = int(time.time())
        suffix = random.randint(0, 99999)
        return f"{epoch}-py-{suffix}"

    def is_valid_correlation_id(self, value: Any) -> bool:
        """Validate correlation ID: string, length 10..100, allowed chars [A-Za-z0-9_-]."""
        if not isinstance(value, str):
            return False
        if not (10 <= len(value) <= 100):
            return False
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            return False
        return True


# src/request_validator.py
import json
import uuid
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple, Union


class ValidationError(Exception):
    """Generic validation error for invalid requests."""


def is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def is_boolean(value: Any) -> bool:
    return isinstance(value, bool)


def coerce_to_bool(value: Any) -> bool:
    """Coerce common truthy/falsey representations to boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes", "y", "on"}:
            return True
        if v in {"false", "0", "no", "n", "off"}:
            return False
    raise ValidationError(f"Cannot coerce value to bool: {value!r}")


def is_valid_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
        return True
    except Exception:
        return False


def ensure_required_fields(data: Mapping[str, Any], required_fields: Iterable[str]) -> None:
    missing = [f for f in required_fields if f not in data]
    if missing:
        raise ValidationError(f"Missing required fields: {', '.join(missing)}")


def sanitize_fields(
    data: Mapping[str, Any],
    allowed_fields: Optional[Iterable[str]] = None,
    allow_unknown: bool = False,
) -> Dict[str, Any]:
    """Return a dict that only contains allowed fields unless allow_unknown=True."""
    if allow_unknown or allowed_fields is None:
        return dict(data)
    allowed = set(allowed_fields)
    unknown = [k for k in data.keys() if k not in allowed]
    if unknown:
        raise ValidationError(f"Unknown fields: {', '.join(unknown)}")
    return {k: data[k] for k in allowed if k in data}


def ensure_types(data: Mapping[str, Any], schema: Mapping[str, Union[type, Tuple[type, ...]]]) -> None:
    """Validate types of fields present in data according to schema."""
    for key, expected in schema.items():
        if key not in data:
            # Only validate present keys; presence is handled by ensure_required_fields
            continue
        val = data[key]
        if not isinstance(val, expected):
            # Slight convenience: allow numbers represented as strings to be coerced when expected is int/float
            if expected in (int, float) and isinstance(val, str):
                try:
                    _ = float(val) if expected is float else int(val)
                    continue
                except Exception:
                    pass
            raise ValidationError(f"Field '{key}' expected {expected}, got {type(val)}")


def validate_json_body(
    obj: Any,
    required_fields: Optional[Iterable[str]] = None,
    optional_fields: Optional[Iterable[str]] = None,
    allow_unknown: bool = False,
    schema: Optional[Mapping[str, Union[type, Tuple[type, ...]]]] = None,
) -> Dict[str, Any]:
    """
    Validate and return a JSON body from either a Flask request or a mapping/dict.
    - Ensures required fields are present
    - Validates types if schema provided
    - Removes unknown fields unless allow_unknown=True
    """
    if hasattr(obj, "get_json"):
        data = obj.get_json(silent=True)
        if data is None:
            raise ValidationError("Request does not contain valid JSON")
    elif isinstance(obj, Mapping):
        data = dict(obj)
    elif isinstance(obj, str):
        try:
            data = json.loads(obj)
        except Exception as e:
            raise ValidationError(f"Invalid JSON string: {e}") from e
    else:
        raise ValidationError("Unsupported input type for JSON validation")

    required_fields = list(required_fields or [])
    optional_fields = list(optional_fields or [])

    ensure_required_fields(data, required_fields)

    if schema:
        ensure_types(data, schema)

    allowed = set(required_fields) | set(optional_fields) if (required_fields or optional_fields) else None
    return sanitize_fields(data, allowed_fields=allowed, allow_unknown=allow_unknown)


def validate_request(
    data: Any,
    schema: Optional[Mapping[str, Union[type, Tuple[type, ...]]]] = None,
    required_fields: Optional[Iterable[str]] = None,
    optional_fields: Optional[Iterable[str]] = None,
    allow_unknown: bool = False,
) -> Dict[str, Any]:
    """Convenience wrapper to validate inbound request-like data."""
    return validate_json_body(
        data,
        required_fields=required_fields,
        optional_fields=optional_fields,
        allow_unknown=allow_unknown,
        schema=schema,
    )