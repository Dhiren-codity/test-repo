import re
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from flask import Flask, jsonify, g, Response

from src.correlation_middleware import (
    CorrelationIDMiddleware,
    CORRELATION_ID_HEADER,
    get_traces,
    get_all_traces,
    store_trace,
    cleanup_old_traces,
    trace_storage,
)


@pytest.fixture(autouse=True)
def clear_trace_storage():
    """Clear the global trace storage before and after each test to avoid cross-test contamination."""
    from src.correlation_middleware import trace_lock

    with trace_lock:
        trace_storage.clear()
    yield
    with trace_lock:
        trace_storage.clear()


@pytest.fixture()
def app():
    """Create a Flask app with a simple route for testing."""
    app = Flask(__name__)

    @app.get("/check")
    def check():
        return jsonify({"cid": getattr(g, "correlation_id", None)})

    return app


@pytest.fixture()
def client(app):
    """Provide a Flask test client."""
    return app.test_client()


def test_CorrelationIDMiddleware___init___auto_init_with_app(app, client):
    """CorrelationIDMiddleware initialized with app should auto-register handlers and set response header."""
    CorrelationIDMiddleware(app)
    resp = client.get("/check")
    assert resp.status_code == 200
    assert resp.json["cid"]  # correlation id exists
    assert CORRELATION_ID_HEADER in resp.headers


def test_CorrelationIDMiddleware_init_app_registers_multiple_times(app):
    """init_app should register before/after handlers each time it is called."""
    mw = CorrelationIDMiddleware()
    before_funcs_before = app.before_request_funcs.get(None, [])[:]
    after_funcs_before = app.after_request_funcs.get(None, [])[:]

    mw.init_app(app)
    mw.init_app(app)

    before_funcs_after = app.before_request_funcs.get(None, [])[:]
    after_funcs_after = app.after_request_funcs.get(None, [])[:]

    assert len(before_funcs_after) == len(before_funcs_before) + 2
    assert len(after_funcs_after) == len(after_funcs_before) + 2
    # Attribute set by init_app
    assert hasattr(app, "correlation_start_time")
    assert app.correlation_start_time is None


def test_CorrelationIDMiddleware_before_and_after_request_with_valid_header(app, client):
    """Valid incoming correlation ID should be preserved, echoed in response, and traced."""
    mw = CorrelationIDMiddleware()
    mw.init_app(app)

    valid_cid = "valid-ABC_def-12345"
    resp = client.get("/check", headers={CORRELATION_ID_HEADER: valid_cid})
    assert resp.status_code == 200
    assert resp.json["cid"] == valid_cid
    assert resp.headers[CORRELATION_ID_HEADER] == valid_cid

    traces = get_traces(valid_cid)
    assert len(traces) >= 1
    trace = traces[-1]
    assert trace["service"] == "python-reviewer"
    assert trace["method"] == "GET"
    assert trace["path"] == "/check"
    assert trace["correlation_id"] == valid_cid
    assert isinstance(trace["duration_ms"], (int, float))
    assert trace["duration_ms"] >= 0
    assert trace["status"] == 200
    # Timestamp is ISO formatted
    datetime.fromisoformat(trace["timestamp"])


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_uses_existing_valid():
    """extract_or_generate_correlation_id should return the existing valid header value."""
    mw = CorrelationIDMiddleware()
    mock_request = Mock()
    valid_cid = "abc_DEF-12345678"
    mock_request.headers = {CORRELATION_ID_HEADER: valid_cid}
    result = mw.extract_or_generate_correlation_id(mock_request)
    assert result == valid_cid


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_generates_when_invalid(monkeypatch):
    """extract_or_generate_correlation_id should generate a new ID when header is invalid."""
    mw = CorrelationIDMiddleware()
    mock_request = Mock()
    invalid_cid = "bad"
    mock_request.headers = {CORRELATION_ID_HEADER: invalid_cid}
    result = mw.extract_or_generate_correlation_id(mock_request)
    assert result != invalid_cid
    assert mw.is_valid_correlation_id(result)


def test_CorrelationIDMiddleware_generate_correlation_id_format_and_validity():
    """generate_correlation_id should produce a string that is valid and matches expected format."""
    mw = CorrelationIDMiddleware()
    cid = mw.generate_correlation_id()
    assert isinstance(cid, str)
    assert "-py-" in cid
    assert mw.is_valid_correlation_id(cid)
    assert 10 <= len(cid) <= 100


def test_CorrelationIDMiddleware_is_valid_correlation_id_various():
    """is_valid_correlation_id should enforce type, length, and character constraints."""
    mw = CorrelationIDMiddleware()

    # Valid
    assert mw.is_valid_correlation_id("abc_DEF-1234567890") is True

    # Invalid type
    assert mw.is_valid_correlation_id(None) is False
    assert mw.is_valid_correlation_id(123) is False

    # Too short
    assert mw.is_valid_correlation_id("abc-123") is False

    # Too long
    assert mw.is_valid_correlation_id("a" * 101) is False

    # Invalid characters (space and exclamation)
    assert mw.is_valid_correlation_id("invalid id 12345") is False
    assert mw.is_valid_correlation_id("invalid!id-12345") is False


def test_CorrelationIDMiddleware_after_request_without_correlation_id_no_header(app):
    """after_request should not set header or store trace if correlation_id is missing."""
    mw = CorrelationIDMiddleware()
    # Do not register hooks; call after_request directly within context
    with app.test_request_context("/check", method="GET"):
        response = Response("OK", status=200)
        updated = mw.after_request(response)
        assert CORRELATION_ID_HEADER not in updated.headers
        assert get_all_traces() == {}


def test_CorrelationIDMiddleware_before_request_sets_g_attributes(app):
    """before_request should set g.correlation_id and g.request_start_time."""
    mw = CorrelationIDMiddleware()
    with app.test_request_context("/manual"):
        mw.before_request()
        assert isinstance(getattr(g, "correlation_id", None), str)
        assert isinstance(getattr(g, "request_start_time", None), float)


def test_CorrelationIDMiddleware_after_request_calls_store_trace(app, client):
    """after_request should call store_trace with expected data."""
    mw = CorrelationIDMiddleware()
    mw.init_app(app)

    cid = "trace-verify-123456"
    with patch("src.correlation_middleware.store_trace") as mock_store:
        resp = client.get("/check", headers={CORRELATION_ID_HEADER: cid})
        assert resp.status_code == 200
        mock_store.assert_called_once()
        args, kwargs = mock_store.call_args
        assert args[0] == cid
        trace_data = args[1]
        # Verify fields in trace data
        for key in ("service", "method", "path", "timestamp", "correlation_id", "duration_ms", "status"):
            assert key in trace_data
        assert trace_data["method"] == "GET"
        assert trace_data["path"] == "/check"
        assert trace_data["correlation_id"] == cid
        assert isinstance(trace_data["duration_ms"], (int, float))
        assert trace_data["status"] == 200
        datetime.fromisoformat(trace_data["timestamp"])


def test_store_trace_and_cleanup_old_traces():
    """store_trace should append traces and cleanup_old_traces should remove old correlation entries."""
    cid_recent = "recent-1234567890"
    now_trace = {
        "service": "python-reviewer",
        "method": "GET",
        "path": "/now",
        "timestamp": datetime.now().isoformat(),
        "correlation_id": cid_recent,
        "duration_ms": 1.23,
        "status": 200,
    }
    store_trace(cid_recent, now_trace)
    assert get_traces(cid_recent) == [now_trace]

    # Add an old trace for a different ID
    cid_old = "old-1234567890"
    old_trace = {
        "service": "python-reviewer",
        "method": "GET",
        "path": "/old",
        "timestamp": (datetime.now() - timedelta(hours=2)).isoformat(),
        "correlation_id": cid_old,
        "duration_ms": 2.34,
        "status": 200,
    }
    trace_storage[cid_old] = [old_trace]

    # Run cleanup and verify old is removed, recent remains
    cleanup_old_traces()
    assert cid_old not in trace_storage
    assert cid_recent in trace_storage


def test_get_traces_returns_copy_not_reference():
    """get_traces should return a copy so that external mutation does not affect storage."""
    cid = "copy-1234567890"
    data = {
        "service": "python-reviewer",
        "method": "GET",
        "path": "/copy",
        "timestamp": datetime.now().isoformat(),
        "correlation_id": cid,
        "duration_ms": 0.5,
        "status": 200,
    }
    store_trace(cid, data)
    returned = get_traces(cid)
    assert returned == [data]
    returned.append({"fake": "data"})
    # Ensure storage not mutated
    assert get_traces(cid) == [data]


def test_get_all_traces_returns_shallow_copies():
    """get_all_traces should return copies of lists so that external mutation does not affect storage."""
    cid = "all-1234567890"
    data = {
        "service": "python-reviewer",
        "method": "GET",
        "path": "/all",
        "timestamp": datetime.now().isoformat(),
        "correlation_id": cid,
        "duration_ms": 0.7,
        "status": 200,
    }
    store_trace(cid, data)

    all_traces = get_all_traces()
    assert cid in all_traces
    # Mutate returned structure
    all_traces[cid].append({"fake": "data"})
    # Underlying storage should be unaffected
    assert len(get_traces(cid)) == 1


def test_CorrelationIDMiddleware_extract_or_generate_non_string_header():
    """extract_or_generate_correlation_id should generate a new ID when existing header is non-string."""
    mw = CorrelationIDMiddleware()
    mock_request = Mock()
    mock_request.headers = {CORRELATION_ID_HEADER: object()}
    result = mw.extract_or_generate_correlation_id(mock_request)
    assert isinstance(result, str)
    assert mw.is_valid_correlation_id(result) is True