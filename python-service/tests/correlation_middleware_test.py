import re
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from flask import Flask, Response, jsonify, g

from src.correlation_middleware import (
    CORRELATION_ID_HEADER,
    CorrelationIDMiddleware,
    cleanup_old_traces,
    get_all_traces,
    get_traces,
    store_trace,
    trace_storage,
)


@pytest.fixture(autouse=True)
def clear_trace_storage():
    """Clear trace_storage before each test to avoid cross-test contamination."""
    trace_storage.clear()
    yield
    trace_storage.clear()


@pytest.fixture()
def app_with_middleware():
    """Create a Flask app with CorrelationIDMiddleware and an echo route."""
    app = Flask(__name__)
    CorrelationIDMiddleware(app)

    @app.get("/echo")
    def echo():
        """Echo the correlation_id and request_start_time from flask.g."""
        return jsonify(
            correlation_id=getattr(g, "correlation_id", None),
            request_start_time=getattr(g, "request_start_time", None),
        )

    @app.get("/hello")
    def hello():
        """Simple endpoint for testing after_request behavior."""
        return jsonify(message="hello")

    return app


@pytest.fixture()
def client(app_with_middleware):
    """Flask test client for the app_with_middleware."""
    return app_with_middleware.test_client()


def test_CorrelationIDMiddleware___init___with_app_registers_hooks():
    """__init__ should register before/after request hooks when app is provided."""
    app = Flask(__name__)
    assert not app.before_request_funcs.get(None)
    assert not app.after_request_funcs.get(None)

    CorrelationIDMiddleware(app)

    assert app.correlation_start_time is None
    before_funcs = app.before_request_funcs.get(None, [])
    after_funcs = app.after_request_funcs.get(None, [])
    assert any(callable(f) for f in before_funcs)
    assert any(callable(f) for f in after_funcs)


def test_CorrelationIDMiddleware_init_app_registers_before_after_and_sets_attribute():
    """init_app should register handlers and set app.correlation_start_time."""
    app = Flask(__name__)
    mid = CorrelationIDMiddleware()
    mid.init_app(app)

    assert app.correlation_start_time is None
    before_funcs = app.before_request_funcs.get(None, [])
    after_funcs = app.after_request_funcs.get(None, [])
    assert len(before_funcs) >= 1
    assert len(after_funcs) >= 1


def test_CorrelationIDMiddleware_init_app_called_twice_adds_duplicate_handlers():
    """init_app called twice on the same instance registers duplicate handlers (no idempotence)."""
    app = Flask(__name__)
    mid = CorrelationIDMiddleware()
    mid.init_app(app)
    mid.init_app(app)  # Called twice

    before_funcs = app.before_request_funcs.get(None, [])
    after_funcs = app.after_request_funcs.get(None, [])
    # Expect at least two handlers registered due to repeated registration
    assert len(before_funcs) >= 2
    assert len(after_funcs) >= 2


def test_CorrelationIDMiddleware_before_request_uses_valid_incoming_header(client):
    """before_request should use the incoming valid correlation ID from the header."""
    incoming = "abc_123-def4567"  # valid chars, length >= 10
    resp = client.get("/echo", headers={CORRELATION_ID_HEADER: incoming})
    assert resp.status_code == 200
    assert resp.json["correlation_id"] == incoming
    assert isinstance(resp.json["request_start_time"], float)


def test_CorrelationIDMiddleware_before_request_generates_when_missing_header(app_with_middleware):
    """before_request should generate a correlation ID when the header is missing."""
    generated = "1111111111-py-99999"
    with patch.object(CorrelationIDMiddleware, "generate_correlation_id", return_value=generated):
        client = app_with_middleware.test_client()
        resp = client.get("/echo")
        assert resp.status_code == 200
        assert resp.json["correlation_id"] == generated
        assert isinstance(resp.json["request_start_time"], float)


def test_CorrelationIDMiddleware_before_request_replaces_invalid_header(app_with_middleware):
    """before_request should replace an invalid incoming correlation ID with a generated one."""
    generated = "2222222222-py-88888"
    with patch.object(CorrelationIDMiddleware, "generate_correlation_id", return_value=generated):
        client = app_with_middleware.test_client()
        resp = client.get("/echo", headers={CORRELATION_ID_HEADER: "bad!"})
        assert resp.status_code == 200
        assert resp.json["correlation_id"] == generated


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_returns_existing_when_valid():
    """extract_or_generate_correlation_id should return the existing valid ID."""
    mid = CorrelationIDMiddleware()
    mock_request = type("Req", (), {"headers": {CORRELATION_ID_HEADER: "valid_id_12345"}})()

    with patch.object(CorrelationIDMiddleware, "is_valid_correlation_id", return_value=True) as mock_valid, \
         patch.object(CorrelationIDMiddleware, "generate_correlation_id") as mock_gen:
        result = mid.extract_or_generate_correlation_id(mock_request)
        assert result == "valid_id_12345"
        mock_valid.assert_called_once_with("valid_id_12345")
        mock_gen.assert_not_called()


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_generates_when_missing():
    """extract_or_generate_correlation_id should generate a new ID when header is missing."""
    mid = CorrelationIDMiddleware()
    mock_request = type("Req", (), {"headers": {}})()

    with patch.object(CorrelationIDMiddleware, "generate_correlation_id", return_value="gen-1") as mock_gen:
        result = mid.extract_or_generate_correlation_id(mock_request)
        assert result == "gen-1"
        mock_gen.assert_called_once()


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_generates_when_invalid():
    """extract_or_generate_correlation_id should generate a new ID when existing header is invalid."""
    mid = CorrelationIDMiddleware()
    mock_request = type("Req", (), {"headers": {CORRELATION_ID_HEADER: "invalid!"}})()

    with patch.object(CorrelationIDMiddleware, "is_valid_correlation_id", return_value=False) as mock_valid, \
         patch.object(CorrelationIDMiddleware, "generate_correlation_id", return_value="gen-2") as mock_gen:
        result = mid.extract_or_generate_correlation_id(mock_request)
        assert result == "gen-2"
        mock_valid.assert_called_once_with("invalid!")
        mock_gen.assert_called_once()


def test_CorrelationIDMiddleware_generate_correlation_id_format_deterministic():
    """generate_correlation_id should produce a deterministic format using time.time() values."""
    mid = CorrelationIDMiddleware()
    with patch("src.correlation_middleware.time.time", return_value=1234567890.0):
        gen = mid.generate_correlation_id()
        assert gen == "1234567890-py-0"
        assert re.match(r"^\d+-py-\d+$", gen)


def test_CorrelationIDMiddleware_is_valid_correlation_id_various():
    """is_valid_correlation_id should validate strings based on length and allowed characters."""
    mid = CorrelationIDMiddleware()
    assert mid.is_valid_correlation_id("abc-123_DEF0") is True  # valid
    assert mid.is_valid_correlation_id("short") is False  # too short
    assert mid.is_valid_correlation_id("a" * 101) is False  # too long
    assert mid.is_valid_correlation_id("invalid!chars") is False  # invalid chars
    assert mid.is_valid_correlation_id(12345) is False  # non-string
    # Exactly boundary length 10 with valid chars
    assert mid.is_valid_correlation_id("a" * 10) is True


def test_CorrelationIDMiddleware_after_request_sets_header_and_stores_trace_with_duration(app_with_middleware):
    """after_request should set the response header and store a trace with computed duration."""
    client = app_with_middleware.test_client()
    cid = "valid-12345-id"

    with patch("src.correlation_middleware.store_trace") as mock_store_trace, \
         patch("src.correlation_middleware.time.time", side_effect=[1000.0, 1000.123]):
        resp = client.get("/hello", headers={CORRELATION_ID_HEADER: cid})
        assert resp.status_code == 200
        assert resp.headers.get(CORRELATION_ID_HEADER) == cid

        # Validate store_trace called with expected trace_data
        assert mock_store_trace.call_count == 1
        args, kwargs = mock_store_trace.call_args
        called_cid, trace_data = args
        assert called_cid == cid
        assert trace_data["service"] == "python-reviewer"
        assert trace_data["method"] == "GET"
        assert trace_data["path"] == "/hello"
        assert trace_data["status"] == 200
        assert trace_data["correlation_id"] == cid
        assert isinstance(trace_data["timestamp"], str)
        assert trace_data["duration_ms"] == 123.0


def test_CorrelationIDMiddleware_after_request_no_correlation_id_does_nothing():
    """after_request should not add header or store traces if g.correlation_id is missing."""
    app = Flask(__name__)
    mid = CorrelationIDMiddleware()  # not auto-registered

    with app.test_request_context("/none", method="GET"):
        response = Response("OK", status=200)
        with patch("src.correlation_middleware.store_trace") as mock_store:
            result = mid.after_request(response)
            assert CORRELATION_ID_HEADER not in result.headers
            mock_store.assert_not_called()


def test_trace_storage_store_and_retrieve_and_cleanup_and_copy_semantics():
    """store_trace should append traces, cleanup_old_traces should remove old ones, and getters should return copies."""
    # Prepare traces
    now = datetime.now()
    old_time = (now - timedelta(hours=2)).isoformat()
    recent_time = now.isoformat()

    old_cid = "old-1234567890"
    recent_cid = "recent-1234567890"

    # Directly populate storage with timestamps
    trace_storage[old_cid] = [{"timestamp": old_time, "dummy": 1}]
    trace_storage[recent_cid] = [{"timestamp": recent_time, "dummy": 2}]

    # Perform cleanup
    cleanup_old_traces()

    # Old should be removed; recent should remain
    assert old_cid not in trace_storage
    assert recent_cid in trace_storage

    # Test store_trace appends and get_traces returns a copy
    new_trace = {"timestamp": recent_time, "dummy": 3}
    store_trace(recent_cid, new_trace)
    traces_copy = get_traces(recent_cid)
    assert len(traces_copy) == 2
    # Mutate the copy and ensure original not affected
    traces_copy.append({"timestamp": recent_time, "dummy": 99})
    assert len(trace_storage[recent_cid]) == 2

    # Test get_all_traces returns shallow copies of lists
    all_copy = get_all_traces()
    assert recent_cid in all_copy
    all_copy[recent_cid].append({"timestamp": recent_time, "dummy": 100})
    assert len(all_copy[recent_cid]) == 3
    # Original should still have 2 entries
    assert len(trace_storage[recent_cid]) == 2


def test_CorrelationIDMiddleware_after_request_integration_with_store_trace(app_with_middleware):
    """Integration: after_request should write into trace_storage via store_trace if not patched."""
    client = app_with_middleware.test_client()
    cid = "abcde-12345-XYZ"

    # Ensure storage is empty
    assert get_traces(cid) == []

    resp = client.get("/hello", headers={CORRELATION_ID_HEADER: cid})
    assert resp.status_code == 200
    assert resp.headers.get(CORRELATION_ID_HEADER) == cid

    traces = get_traces(cid)
    assert len(traces) == 1
    trace = traces[0]
    assert trace["correlation_id"] == cid
    assert trace["path"] == "/hello"
    assert trace["method"] == "GET"
    assert trace["status"] == 200
    assert "duration_ms" in trace and isinstance(trace["duration_ms"], float) or isinstance(trace["duration_ms"], int)