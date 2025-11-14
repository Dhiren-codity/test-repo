import pytest
from unittest.mock import Mock, patch
from flask import Flask, g, Response

from src.correlation_middleware import (
    CorrelationIDMiddleware,
    CORRELATION_ID_HEADER,
    get_traces,
    get_all_traces,
    trace_storage,
    cleanup_old_traces,
)


@pytest.fixture
def flask_app():
    """Create and configure a new Flask app for each test."""
    app = Flask(__name__)
    app.config.update({"TESTING": True})

    @app.route("/ping")
    def ping():
        return "pong", 200

    return app


@pytest.fixture
def middleware():
    """Provide a fresh CorrelationIDMiddleware instance."""
    return CorrelationIDMiddleware()


@pytest.fixture(autouse=True)
def clear_trace_storage():
    """Clear the global trace storage before each test."""
    trace_storage.clear()
    yield
    trace_storage.clear()


def test_CorrelationIDMiddleware___init___without_app():
    """Ensure __init__ handles None app without registering hooks."""
    mw = CorrelationIDMiddleware(app=None)
    assert mw.app is None


def test_CorrelationIDMiddleware___init___with_app_calls_init_app(flask_app):
    """Ensure __init__ with app calls init_app."""
    with patch.object(CorrelationIDMiddleware, "init_app") as mock_init_app:
        mw = CorrelationIDMiddleware(app=flask_app)
        mock_init_app.assert_called_once_with(flask_app)
        assert mw.app is flask_app


def test_CorrelationIDMiddleware_init_app_registers_hooks_and_sets_attr(flask_app, middleware):
    """Verify init_app registers before/after request handlers and sets attribute on app."""
    middleware.init_app(flask_app)
    # Flask stores funcs per blueprint; None key is for app-wide
    assert middleware.before_request in flask_app.before_request_funcs.get(None, [])
    assert middleware.after_request in flask_app.after_request_funcs.get(None, [])
    assert hasattr(flask_app, "correlation_start_time")
    assert flask_app.correlation_start_time is None


def test_CorrelationIDMiddleware_before_request_sets_g_and_time(flask_app, middleware):
    """before_request should set g.correlation_id and g.request_start_time."""
    with flask_app.test_request_context("/test"):
        with patch.object(middleware, "extract_or_generate_correlation_id", return_value="valid-123456789") as _:
            with patch("src.correlation_middleware.time.time", return_value=1000.0):
                middleware.before_request()
                assert g.correlation_id == "valid-123456789"
                assert g.request_start_time == 1000.0


def test_CorrelationIDMiddleware_after_request_sets_header_and_stores_trace(flask_app, middleware):
    """after_request should add header and store a trace entry."""
    with flask_app.test_request_context("/foo", method="GET"):
        g.correlation_id = "cid-1234567890"
        g.request_start_time = 1000.0

        resp = Response("ok", status=200)

        with patch("src.correlation_middleware.time.time", return_value=1000.2):
            with patch("src.correlation_middleware.store_trace") as mock_store_trace:
                result = middleware.after_request(resp)

        assert result.headers[CORRELATION_ID_HEADER] == "cid-1234567890"
        # Validate store_trace call with expected data
        assert mock_store_trace.call_count == 1
        args, kwargs = mock_store_trace.call_args
        assert args[0] == "cid-1234567890"
        trace = args[1]
        assert trace["service"] == "python-reviewer"
        assert trace["method"] == "GET"
        assert trace["path"] == "/foo"
        assert trace["correlation_id"] == "cid-1234567890"
        assert trace["status"] == 200
        assert isinstance(trace["timestamp"], str)
        assert trace["duration_ms"] == 200.0


def test_CorrelationIDMiddleware_after_request_no_correlation_id_no_header_no_store(flask_app, middleware):
    """after_request should not add header or store trace if correlation_id is missing."""
    with flask_app.test_request_context("/bar", method="POST"):
        # g.correlation_id intentionally not set
        resp = Response("ok", status=204)
        with patch("src.correlation_middleware.store_trace") as mock_store_trace:
            result = middleware.after_request(resp)
        assert CORRELATION_ID_HEADER not in result.headers
        mock_store_trace.assert_not_called()


def test_CorrelationIDMiddleware_after_request_uses_current_time_when_start_missing(flask_app, middleware):
    """after_request should handle missing request_start_time by using current time."""
    with flask_app.test_request_context("/baz", method="GET"):
        g.correlation_id = "cid-abcdef12345"
        # g.request_start_time intentionally not set
        resp = Response("ok", status=200)
        with patch("src.correlation_middleware.time.time", return_value=12345.0):
            with patch("src.correlation_middleware.store_trace") as mock_store_trace:
                middleware.after_request(resp)
        # Duration should be 0.0 because both times are the same mocked value
        args, _ = mock_store_trace.call_args
        trace = args[1]
        assert trace["duration_ms"] == 0.0


def test_CorrelationIDMiddleware_extract_or_generate_uses_existing_valid_header(middleware):
    """extract_or_generate_correlation_id should use existing valid header."""
    fake_request = Mock()
    fake_request.headers = {CORRELATION_ID_HEADER: "valid-abcde12345"}
    cid = middleware.extract_or_generate_correlation_id(fake_request)
    assert cid == "valid-abcde12345"


def test_CorrelationIDMiddleware_extract_or_generate_generates_when_missing_or_invalid(middleware):
    """extract_or_generate_correlation_id should generate when header missing or invalid."""
    # Missing header
    fake_request_missing = Mock()
    fake_request_missing.headers = {}

    with patch.object(CorrelationIDMiddleware, "generate_correlation_id", return_value="gen-1234567890"):
        cid1 = middleware.extract_or_generate_correlation_id(fake_request_missing)
        assert cid1 == "gen-1234567890"

    # Invalid header (too short)
    fake_request_invalid = Mock()
    fake_request_invalid.headers = {CORRELATION_ID_HEADER: "short"}

    with patch.object(CorrelationIDMiddleware, "generate_correlation_id", return_value="gen-0987654321"):
        cid2 = middleware.extract_or_generate_correlation_id(fake_request_invalid)
        assert cid2 == "gen-0987654321"

    # Invalid header (non-string)
    fake_request_nonstring = Mock()
    fake_request_nonstring.headers = {CORRELATION_ID_HEADER: 12345}

    with patch.object(CorrelationIDMiddleware, "generate_correlation_id", return_value="gen-1122334455"):
        cid3 = middleware.extract_or_generate_correlation_id(fake_request_nonstring)
        assert cid3 == "gen-1122334455"


def test_CorrelationIDMiddleware_generate_correlation_id_format_with_mocked_time(middleware):
    """generate_correlation_id should create deterministic ID with mocked time."""
    with patch("src.correlation_middleware.time.time", return_value=1234567890.123456):
        cid = middleware.generate_correlation_id()
    assert cid == "1234567890-py-23456"


@pytest.mark.parametrize(
    "value,expected",
    [
        (123, False),  # non-string
        ("shortlen", False),  # length < 10
        ("validlen10", True),  # exactly 10 chars
        ("a" * 100, True),  # exactly 100 chars
        ("a" * 101, False),  # too long
        ("invalid id!", False),  # invalid chars (space and punctuation)
        ("valid-id_123", True),  # valid chars
    ],
)
def test_CorrelationIDMiddleware_is_valid_correlation_id_various(middleware, value, expected):
    """is_valid_correlation_id should validate type, length, and allowed characters."""
    assert middleware.is_valid_correlation_id(value) is expected


def test_CorrelationIDMiddleware_integration_flow_adds_header_and_stores_trace(flask_app, middleware):
    """Full integration: middleware attaches header and stores trace on request."""
    middleware.init_app(flask_app)
    client = flask_app.test_client()

    incoming_cid = "incoming-abcdef12"
    resp = client.get("/ping", headers={CORRELATION_ID_HEADER: incoming_cid})

    assert resp.status_code == 200
    assert resp.headers.get(CORRELATION_ID_HEADER) == incoming_cid

    traces = get_traces(incoming_cid)
    assert len(traces) == 1
    t = traces[0]
    assert t["method"] == "GET"
    assert t["path"] == "/ping"
    assert t["correlation_id"] == incoming_cid
    assert t["status"] == 200
    assert t["service"] == "python-reviewer"

    all_traces = get_all_traces()
    assert incoming_cid in all_traces
    assert len(all_traces[incoming_cid]) == 1


def test_cleanup_old_traces_removes_entries_older_than_one_hour():
    """cleanup_old_traces should delete correlation IDs whose oldest trace is >1 hour old."""
    from datetime import datetime, timedelta

    old_cid = "old-cid-123456"
    recent_cid = "recent-cid-123456"

    now = datetime.now()
    too_old_time = (now - timedelta(hours=1, minutes=1)).isoformat()
    recent_time = (now - timedelta(minutes=30)).isoformat()

    trace_storage[old_cid] = [{"timestamp": too_old_time}]
    trace_storage[recent_cid] = [{"timestamp": recent_time}]

    cleanup_old_traces()

    assert old_cid not in trace_storage
    assert recent_cid in trace_storage