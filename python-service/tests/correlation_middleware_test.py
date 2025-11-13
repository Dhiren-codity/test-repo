import pytest
from unittest.mock import Mock, patch
from flask import Flask, g, make_response

from src.correlation_middleware import (
    CorrelationIDMiddleware,
    CORRELATION_ID_HEADER,
    get_traces,
    trace_storage,
    cleanup_old_traces,
)


@pytest.fixture(autouse=True)
def reset_trace_storage():
    """Ensure trace storage is cleared before and after each test."""
    trace_storage.clear()
    yield
    trace_storage.clear()


@pytest.fixture
def middleware_instance():
    """Provide a fresh CorrelationIDMiddleware instance."""
    return CorrelationIDMiddleware()


@pytest.fixture
def flask_app():
    """Create a Flask app for testing without middleware registered."""
    app = Flask(__name__)
    return app


@pytest.fixture
def flask_app_with_middleware(flask_app):
    """Create a Flask app with CorrelationIDMiddleware registered and a simple route."""
    app = flask_app
    middleware = CorrelationIDMiddleware()
    middleware.init_app(app)

    @app.route("/ping")
    def ping():
        return "pong", 200

    return app


def test_CorrelationIDMiddleware___init___without_app_does_not_call_init_app():
    """Ensure __init__ does not call init_app when app is None."""
    with patch.object(CorrelationIDMiddleware, "init_app", autospec=True) as mock_init:
        CorrelationIDMiddleware(app=None)
        mock_init.assert_not_called()


def test_CorrelationIDMiddleware___init___with_app_calls_init_app(flask_app):
    """Ensure __init__ calls init_app when an app is provided."""
    app = flask_app
    with patch.object(CorrelationIDMiddleware, "init_app", autospec=True) as mock_init:
        mid = CorrelationIDMiddleware(app=app)
        mock_init.assert_called_once_with(mid, app)


def test_CorrelationIDMiddleware_init_app_registers_hooks(flask_app):
    """Verify init_app registers before_request and after_request hooks."""
    app = flask_app
    mid = CorrelationIDMiddleware()
    mid.init_app(app)

    assert None in app.before_request_funcs
    assert mid.before_request in app.before_request_funcs[None]

    assert None in app.after_request_funcs
    assert mid.after_request in app.after_request_funcs[None]

    # extra attribute set in init_app
    assert hasattr(app, "correlation_start_time")
    assert app.correlation_start_time is None


def test_CorrelationIDMiddleware_before_request_sets_correlation_id_from_header(middleware_instance, flask_app):
    """before_request should use a valid incoming correlation ID from headers."""
    app = flask_app
    mid = middleware_instance
    with app.test_request_context("/test", headers={CORRELATION_ID_HEADER: "valid-id_12345"}):
        mid.before_request()
        assert getattr(g, "correlation_id", None) == "valid-id_12345"
        assert isinstance(getattr(g, "request_start_time", None), float)


def test_CorrelationIDMiddleware_before_request_generates_id_when_invalid_header(middleware_instance, flask_app):
    """before_request should generate a new correlation ID when incoming is invalid."""
    app = flask_app
    mid = middleware_instance
    with patch.object(mid, "generate_correlation_id", return_value="generated-123456") as mock_gen:
        with app.test_request_context("/test", headers={CORRELATION_ID_HEADER: "bad id"}):
            mid.before_request()
            assert g.correlation_id == "generated-123456"
            mock_gen.assert_called_once()


def test_CorrelationIDMiddleware_after_request_sets_header_and_stores_trace(flask_app_with_middleware):
    """after_request should add the correlation ID header and store trace data."""
    app = flask_app_with_middleware
    client = app.test_client()

    cid = "cid-1234567890"
    resp = client.get("/ping", headers={CORRELATION_ID_HEADER: cid})

    assert resp.status_code == 200
    assert resp.headers.get(CORRELATION_ID_HEADER) == cid

    traces = get_traces(cid)
    assert len(traces) >= 1
    t = traces[-1]
    assert t["service"] == "python-reviewer"
    assert t["method"] == "GET"
    assert t["path"] == "/ping"
    assert t["correlation_id"] == cid
    assert t["status"] == 200
    assert isinstance(t["duration_ms"], float)


def test_CorrelationIDMiddleware_after_request_no_correlation_id_no_header_change(middleware_instance, flask_app):
    """after_request should not set the header or store trace if no correlation_id is present."""
    app = flask_app
    mid = middleware_instance

    with app.test_request_context("/no-cid"):
        # Do not call before_request, so no g.correlation_id is set
        response = make_response("ok", 200)
        result = mid.after_request(response)

        assert result.status_code == 200
        assert CORRELATION_ID_HEADER not in result.headers
        assert trace_storage == {}


def test_CorrelationIDMiddleware_extract_or_generate_uses_existing_when_valid(middleware_instance):
    """extract_or_generate_correlation_id should return incoming ID if valid."""
    mid = middleware_instance

    class DummyReq:
        def __init__(self, headers):
            self.headers = headers

    req = DummyReq(headers={CORRELATION_ID_HEADER: "abcDEF_123-xyz"})
    result = mid.extract_or_generate_correlation_id(req)
    assert result == "abcDEF_123-xyz"


def test_CorrelationIDMiddleware_extract_or_generate_generates_when_missing(middleware_instance):
    """extract_or_generate_correlation_id should generate new ID when header is missing."""
    mid = middleware_instance

    class DummyReq:
        def __init__(self, headers):
            self.headers = headers

    req = DummyReq(headers={})
    with patch.object(mid, "generate_correlation_id", return_value="gid-1") as mock_gen:
        result = mid.extract_or_generate_correlation_id(req)
        assert result == "gid-1"
        mock_gen.assert_called_once()


def test_CorrelationIDMiddleware_generate_correlation_id_uses_time(middleware_instance):
    """generate_correlation_id should incorporate the current time in a deterministic format."""
    mid = middleware_instance
    with patch("src.correlation_middleware.time.time", return_value=1700000000.123456):
        cid = mid.generate_correlation_id()
        assert cid == "1700000000-py-23456"


def test_CorrelationIDMiddleware_is_valid_correlation_id_various(middleware_instance):
    """is_valid_correlation_id should validate length, type, and allowed characters."""
    mid = middleware_instance
    assert mid.is_valid_correlation_id("abcDEF_123-xyz") is True
    assert mid.is_valid_correlation_id("short-id") is False  # too short
    assert mid.is_valid_correlation_id("a" * 101) is False  # too long
    assert mid.is_valid_correlation_id("bad$id$chars") is False  # invalid chars
    assert mid.is_valid_correlation_id(12345) is False  # non-str


def test_cleanup_old_traces_removes_old_entries():
    """cleanup_old_traces should remove correlation IDs older than 1 hour."""
    # Build old and new traces
    old_timestamp = "2000-01-01T00:00:00"
    new_timestamp = "2999-01-01T00:00:00"
    trace_storage["oldcid"] = [{"timestamp": old_timestamp}]
    trace_storage["newcid"] = [{"timestamp": new_timestamp}]

    cleanup_old_traces()

    assert "oldcid" not in trace_storage
    assert "newcid" in trace_storage