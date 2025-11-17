import re
import pytest
from unittest.mock import patch

from flask import Flask, Response, g

from src.correlation_middleware import (
    CorrelationIDMiddleware,
    store_trace,
    get_traces,
    get_all_traces,
    trace_storage,
    cleanup_old_traces,
    CORRELATION_ID_HEADER,
)


@pytest.fixture
def app():
    """Create a Flask app for testing."""
    app = Flask(__name__)
    return app


@pytest.fixture(autouse=True)
def clear_trace_storage():
    """Ensure global trace storage is clean before and after each test."""
    trace_storage.clear()
    yield
    trace_storage.clear()


@pytest.fixture
def middleware():
    """Create middleware instance without binding to app."""
    return CorrelationIDMiddleware()


@pytest.fixture
def initialized_middleware(app):
    """Create and initialize middleware with the Flask app."""
    middleware = CorrelationIDMiddleware(app)
    return middleware


def test_CorrelationIDMiddleware___init___with_app_registers_hooks_and_sets_flag(app):
    """Init with app should register hooks and set app flag; making a request should set header."""
    CorrelationIDMiddleware(app)

    assert hasattr(app, "correlation_start_time")
    assert app.correlation_start_time is None

    @app.route("/ping")
    def ping():
        return "pong"

    client = app.test_client()
    resp = client.get("/ping")
    assert resp.status_code == 200
    assert CORRELATION_ID_HEADER in resp.headers
    assert isinstance(resp.headers[CORRELATION_ID_HEADER], str)
    assert len(resp.headers[CORRELATION_ID_HEADER]) >= 10


def test_CorrelationIDMiddleware___init___without_app_then_init_app_works(app):
    """Init without app then calling init_app should register behavior."""
    mid = CorrelationIDMiddleware()
    mid.init_app(app)

    @app.route("/ok")
    def ok():
        return "ok"

    client = app.test_client()
    resp = client.get("/ok")
    assert resp.status_code == 200
    assert CORRELATION_ID_HEADER in resp.headers


def test_CorrelationIDMiddleware_init_app_sets_before_and_after_hooks(app):
    """init_app should register before and after request handlers on the app."""
    mid = CorrelationIDMiddleware()
    mid.init_app(app)

    # Flask stores these in dicts keyed by blueprint (None for app-wide)
    before_funcs = app.before_request_funcs.get(None, [])
    after_funcs = app.after_request_funcs.get(None, [])

    # Ensure functions with the expected names are registered
    assert any(getattr(f, "__name__", "") == "before_request" for f in before_funcs)
    assert any(getattr(f, "__name__", "") == "after_request" for f in after_funcs)


def test_CorrelationIDMiddleware_before_request_sets_g_and_start_time_with_valid_header(app, middleware):
    """before_request should set g.correlation_id to header when valid, and start time."""
    valid_header = "abc-123_DEF"
    with app.test_request_context("/test", headers={CORRELATION_ID_HEADER: valid_header}):
        middleware.before_request()
        assert g.correlation_id == valid_header
        assert isinstance(g.request_start_time, float)
        assert g.request_start_time > 0.0


def test_CorrelationIDMiddleware_after_request_sets_header_and_stores_trace(app, middleware):
    """after_request should set correlation header and store a trace with correct fields."""
    cid = "VALID_ID_12345"
    path = "/trace"
    method = "POST"

    with app.test_request_context(path, method=method, headers={CORRELATION_ID_HEADER: cid}):
        # Control timing for duration calculation
        with patch("src.correlation_middleware.time.time") as mock_time:
            mock_time.side_effect = [1000.0, 1000.123]  # start, end
            middleware.before_request()
            response = Response("done", status=201)
            response = middleware.after_request(response)

    assert response.status_code == 201
    assert response.headers[CORRELATION_ID_HEADER] == cid

    traces = get_traces(cid)
    assert len(traces) == 1
    t = traces[0]
    assert t["service"] == "python-reviewer"
    assert t["method"] == method
    assert t["path"] == path
    # timestamp is ISO string
    assert isinstance(t["timestamp"], str)
    # duration approximately 123 ms
    assert isinstance(t["duration_ms"], float)
    assert t["duration_ms"] == pytest.approx(123.0, abs=0.01)
    assert t["status"] == 201


def test_CorrelationIDMiddleware_after_request_without_correlation_id_does_nothing(app, middleware):
    """after_request should not set header or store traces if no correlation_id in g."""
    with app.test_request_context("/no-cid"):
        # Do not call before_request
        response = Response("x", status=200)
        response = middleware.after_request(response)

    assert CORRELATION_ID_HEADER not in response.headers
    assert get_all_traces() == {}


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_uses_valid_header(app, middleware):
    """extract_or_generate_correlation_id should return valid header value as-is."""
    valid_header = "VALID_HEADER_1234"
    with app.test_request_context("/extract", headers={CORRELATION_ID_HEADER: valid_header}):
        from flask import request
        result = middleware.extract_or_generate_correlation_id(request)
        assert result == valid_header


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_generates_when_invalid(app, middleware):
    """extract_or_generate_correlation_id should generate a new value when header is invalid."""
    invalid_header = "invalid!header"
    expected_generated = "gen-1234567890"
    with app.test_request_context("/extract", headers={CORRELATION_ID_HEADER: invalid_header}):
        from flask import request
        with patch.object(middleware, "generate_correlation_id", return_value=expected_generated) as mock_gen:
            result = middleware.extract_or_generate_correlation_id(request)
            assert result == expected_generated
            mock_gen.assert_called_once()


def test_CorrelationIDMiddleware_generate_correlation_id_format(middleware):
    """generate_correlation_id should return a string with expected format."""
    cid = middleware.generate_correlation_id()
    assert isinstance(cid, str)
    assert "-py-" in cid
    assert re.match(r"^\d+-py-\d+$", cid) is not None


def test_CorrelationIDMiddleware_is_valid_correlation_id_edge_cases(middleware):
    """is_valid_correlation_id should validate length, type, and allowed characters."""
    # Non-string
    assert middleware.is_valid_correlation_id(12345) is False
    # Too short
    assert middleware.is_valid_correlation_id("short") is False
    # Too long
    assert middleware.is_valid_correlation_id("x" * 101) is False
    # Invalid characters
    assert middleware.is_valid_correlation_id("abc$%def--") is False
    assert middleware.is_valid_correlation_id("has space____") is False
    # Valid at boundaries: length 10 and 100
    assert middleware.is_valid_correlation_id("a" * 10) is True
    assert middleware.is_valid_correlation_id(("a_" * 50)) is True  # 100 chars
    # Valid with dashes/underscores
    assert middleware.is_valid_correlation_id("ABC_def-123") is True


def test_store_trace_and_cleanup_and_getters():
    """store_trace should append traces and cleanup should remove old correlation IDs."""
    # Recent trace
    recent_id = "RECENT_ID_12345"
    recent_trace = {
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "service": "svc",
        "method": "GET",
        "path": "/recent",
        "correlation_id": recent_id,
        "duration_ms": 1.23,
        "status": 200,
    }
    store_trace(recent_id, recent_trace)

    # Old trace (older than 1 hour)
    old_id = "OLD_ID_12345"
    old_timestamp = (__import__("datetime").datetime.now() - __import__("datetime").timedelta(hours=1, minutes=1)).isoformat()
    old_trace = {
        "timestamp": old_timestamp,
        "service": "svc",
        "method": "GET",
        "path": "/old",
        "correlation_id": old_id,
        "duration_ms": 2.34,
        "status": 200,
    }
    store_trace(old_id, old_trace)

    # After storing the old trace, cleanup runs and should delete the old_id traces
    assert old_id not in get_all_traces()
    assert recent_id in get_all_traces()
    assert get_traces(recent_id) == [recent_trace]

    # get_traces returns a copy
    copy_list = get_traces(recent_id)
    copy_list.append({"new": "item"})
    assert get_traces(recent_id) == [recent_trace]

    # get_all_traces returns deep-ish copy (list copies)
    all_copy = get_all_traces()
    assert recent_id in all_copy
    all_copy[recent_id].append({"mutate": True})
    assert len(get_all_traces()[recent_id]) == 1  # original unchanged


def test_cleanup_old_traces_manual_invocation():
    """cleanup_old_traces should remove entries whose oldest trace is older than cutoff."""
    now = __import__("datetime").datetime.now()
    old_ts = (now - __import__("datetime").timedelta(hours=2)).isoformat()
    ok_ts = (now - __import__("datetime").timedelta(minutes=30)).isoformat()

    # Populate trace_storage directly with controlled timestamps
    trace_storage["to_delete"] = [{"timestamp": old_ts}]
    trace_storage["to_keep"] = [{"timestamp": ok_ts}]

    cleanup_old_traces()

    assert "to_delete" not in trace_storage
    assert "to_keep" in trace_storage