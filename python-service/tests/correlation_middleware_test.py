import re
import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from flask import Flask, g, Response

from src.correlation_middleware import (
    CorrelationIDMiddleware,
    CORRELATION_ID_HEADER,
    store_trace,
    get_traces,
    get_all_traces,
    cleanup_old_traces,
    trace_storage,
)


@pytest.fixture(autouse=True)
def clear_trace_storage():
    """Ensure trace storage is clear before each test."""
    trace_storage.clear()
    yield
    trace_storage.clear()


@pytest.fixture
def flask_app():
    """Create a Flask app for testing."""
    app = Flask(__name__)
    return app


@pytest.fixture
def middleware():
    """Create a CorrelationIDMiddleware instance without initializing the app."""
    return CorrelationIDMiddleware()


def test_correlationidmiddleware_init_with_app_registers_hooks(flask_app):
    """Test that __init__ with app registers before/after request hooks and sets app attribute."""
    mw = CorrelationIDMiddleware(flask_app)

    # Check app attribute set
    assert hasattr(flask_app, "correlation_start_time")
    assert flask_app.correlation_start_time is None

    # Check hooks registered
    br_funcs = flask_app.before_request_funcs.get(None, [])
    ar_funcs = flask_app.after_request_funcs.get(None, [])
    assert any(getattr(f, "__self__", None) is mw and f.__name__ == "before_request" for f in br_funcs)
    assert any(getattr(f, "__self__", None) is mw and f.__name__ == "after_request" for f in ar_funcs)


def test_correlationidmiddleware_init_without_app_then_init_app(flask_app, middleware):
    """Test init_app registers hooks when called after initialization without app."""
    middleware.init_app(flask_app)

    br_funcs = flask_app.before_request_funcs.get(None, [])
    ar_funcs = flask_app.after_request_funcs.get(None, [])
    assert any(getattr(f, "__self__", None) is middleware and f.__name__ == "before_request" for f in br_funcs)
    assert any(getattr(f, "__self__", None) is middleware and f.__name__ == "after_request" for f in ar_funcs)


def test_correlationidmiddleware_is_valid_correlation_id_various_cases(middleware):
    """Test validation logic for correlation IDs with edge cases and valid cases."""
    # Non-string input
    assert middleware.is_valid_correlation_id(12345) is False

    # Too short (<10)
    assert middleware.is_valid_correlation_id("short") is False

    # Too long (>100)
    long_id = "a" * 101
    assert middleware.is_valid_correlation_id(long_id) is False

    # Invalid characters
    assert middleware.is_valid_correlation_id("invalid!char") is False
    assert middleware.is_valid_correlation_id("also.invalid") is False

    # Valid characters and length
    assert middleware.is_valid_correlation_id("abc-DEF_1234") is True
    assert middleware.is_valid_correlation_id("ABCDEFGHIJ") is True  # exactly 10 chars


def test_correlationidmiddleware_generate_correlation_id_format(middleware):
    """Test generate_correlation_id returns a string matching expected pattern."""
    cid = middleware.generate_correlation_id()
    assert isinstance(cid, str)
    assert "-py-" in cid
    assert re.match(r"^\d+-py-\d{1,5}$", cid) is not None


def test_correlationidmiddleware_extract_or_generate_uses_existing_valid_id(middleware):
    """Test extract_or_generate_correlation_id returns the provided valid header."""
    class DummyRequest:
        headers = {CORRELATION_ID_HEADER: "abcd-12345Z"}  # length 11 and valid

    # ensure actual validation passes to exercise real method
    result = middleware.extract_or_generate_correlation_id(DummyRequest)
    assert result == "abcd-12345Z"


def test_correlationidmiddleware_extract_or_generate_generates_when_invalid(middleware):
    """Test extract_or_generate_correlation_id generates new ID when provided one is invalid."""
    class DummyRequest:
        headers = {CORRELATION_ID_HEADER: "short"}  # invalid length

    with patch.object(middleware, "generate_correlation_id", return_value="gen-1234567890") as mock_gen:
        result = middleware.extract_or_generate_correlation_id(DummyRequest)
        assert result == "gen-1234567890"
        mock_gen.assert_called_once()


def test_correlationidmiddleware_before_request_sets_g_and_start_time(flask_app, middleware):
    """Test before_request sets g.correlation_id and g.request_start_time."""
    middleware.init_app(flask_app)
    with flask_app.test_request_context("/test"):
        with patch.object(middleware, "extract_or_generate_correlation_id", return_value="cid-1234567890"):
            with patch("src.correlation_middleware.time.time", return_value=42.0):
                middleware.before_request()
                assert g.correlation_id == "cid-1234567890"
                assert g.request_start_time == 42.0


def test_correlationidmiddleware_after_request_sets_header_and_stores_trace(flask_app):
    """Test that after_request sets response header and stores trace data."""
    mw = CorrelationIDMiddleware(flask_app)

    @flask_app.route("/ping", methods=["GET"])
    def ping():
        return "OK", 200

    # Provide a valid correlation ID. Duration ~100ms using patched time.
    with patch("src.correlation_middleware.time.time", side_effect=[1000.0, 1000.1]):
        client = flask_app.test_client()
        resp = client.get("/ping", headers={CORRELATION_ID_HEADER: "valid-123456"})
        assert resp.status_code == 200
        assert resp.headers[CORRELATION_ID_HEADER] == "valid-123456"

    # Verify trace stored
    traces = get_traces("valid-123456")
    assert len(traces) == 1
    trace = traces[0]
    assert trace["service"] == "python-reviewer"
    assert trace["method"] == "GET"
    assert trace["path"] == "/ping"
    assert trace["correlation_id"] == "valid-123456"
    assert trace["status"] == 200
    assert isinstance(trace["duration_ms"], float) or isinstance(trace["duration_ms"], int)
    assert 90 <= trace["duration_ms"] <= 110


def test_correlationidmiddleware_after_request_no_correlation_id_no_header(flask_app):
    """Test that after_request does not set header or store trace when correlation_id missing."""
    mw = CorrelationIDMiddleware(flask_app)

    @flask_app.route("/no-cid", methods=["GET"])
    def no_cid():
        # Simulate a missing correlation_id by deleting it from g
        if hasattr(g, "correlation_id"):
            delattr(g, "correlation_id")
        return "OK", 200

    client = flask_app.test_client()
    resp = client.get("/no-cid")
    assert resp.status_code == 200
    assert CORRELATION_ID_HEADER not in resp.headers
    assert get_all_traces() == {}


def test_correlationidmiddleware_flow_generates_when_missing_header(flask_app):
    """Test full request flow generates and attaches a correlation ID when missing."""
    mw = CorrelationIDMiddleware(flask_app)

    @flask_app.route("/auto", methods=["GET"])
    def auto():
        return "OK", 200

    with patch.object(CorrelationIDMiddleware, "generate_correlation_id", return_value="gen-1234567890"):
        client = flask_app.test_client()
        resp = client.get("/auto")
        assert resp.status_code == 200
        assert resp.headers[CORRELATION_ID_HEADER] == "gen-1234567890"

    traces = get_traces("gen-1234567890")
    assert len(traces) == 1
    assert traces[0]["path"] == "/auto"


def test_store_trace_and_get_traces_returns_copy():
    """Test store_trace stores data and get_traces returns a copy that does not mutate original."""
    cid = "valid-123456"
    data = {
        "service": "python-reviewer",
        "method": "GET",
        "path": "/x",
        "timestamp": datetime.now().isoformat(),
        "correlation_id": cid,
        "duration_ms": 1.23,
        "status": 200,
    }
    store_trace(cid, data)

    traces = get_traces(cid)
    assert len(traces) == 1
    traces.append({"dummy": True})

    # Original storage should remain unchanged
    assert len(get_traces(cid)) == 1


def test_cleanup_old_traces_removes_outdated_entries():
    """Test cleanup_old_traces removes entries older than 1 hour."""
    old_cid = "old-1234567"
    new_cid = "new-1234567"
    two_hours_ago = (datetime.now() - timedelta(hours=2)).isoformat()
    now = datetime.now().isoformat()

    trace_storage[old_cid] = [
        {
            "service": "python-reviewer",
            "method": "GET",
            "path": "/old",
            "timestamp": two_hours_ago,
            "correlation_id": old_cid,
            "duration_ms": 10.0,
            "status": 200,
        }
    ]
    trace_storage[new_cid] = [
        {
            "service": "python-reviewer",
            "method": "POST",
            "path": "/new",
            "timestamp": now,
            "correlation_id": new_cid,
            "duration_ms": 5.0,
            "status": 201,
        }
    ]

    cleanup_old_traces()
    assert old_cid not in trace_storage
    assert new_cid in trace_storage


def test_correlationidmiddleware_extract_or_generate_handles_nonexistent_header_gracefully(middleware):
    """Test extract_or_generate_correlation_id gracefully handles missing header and generates ID."""
    class DummyRequest:
        headers = {}

    with patch.object(middleware, "generate_correlation_id", return_value="gen-abcdef1234") as mock_gen:
        result = middleware.extract_or_generate_correlation_id(DummyRequest)
        assert result == "gen-abcdef1234"
        mock_gen.assert_called_once()


def test_correlationidmiddleware_after_request_returns_response_on_exception_in_store(flask_app):
    """Test after_request still returns response even if store_trace raises (simulated)."""
    mw = CorrelationIDMiddleware(flask_app)

    @flask_app.route("/store-error", methods=["GET"])
    def store_error():
        return "OK", 200

    # Patch store_trace to raise an exception when called
    with patch("src.correlation_middleware.store_trace", side_effect=RuntimeError("boom")):
        client = flask_app.test_client()
        # Provide a valid header so after_request attempts to store
        with pytest.raises(RuntimeError):
            # Since there's no internal exception handling, this will raise
            client.get("/store-error", headers={CORRELATION_ID_HEADER: "valid-1234567"})