import pytest
from unittest.mock import Mock, patch
from flask import Flask, g
from datetime import datetime as real_datetime

from src.correlation_middleware import (
    CorrelationIDMiddleware,
    store_trace,
    cleanup_old_traces,
    get_traces,
    get_all_traces,
    trace_storage,
    CORRELATION_ID_HEADER,
)


@pytest.fixture(autouse=True)
def clear_trace_storage():
    """Ensure trace storage is clean before and after each test."""
    trace_storage.clear()
    yield
    trace_storage.clear()


@pytest.fixture
def app():
    """Create a Flask app for testing."""
    return Flask(__name__)


@pytest.fixture
def middleware():
    """Create a CorrelationIDMiddleware instance for testing."""
    return CorrelationIDMiddleware()


def test_CorrelationIDMiddleware___init___without_app():
    """__init__ should not initialize app hooks when app is None."""
    m = CorrelationIDMiddleware()
    assert m.app is None


def test_CorrelationIDMiddleware___init___with_app_calls_init_app():
    """__init__ should call init_app when app is provided."""
    fake_app = object()
    with patch("src.correlation_middleware.CorrelationIDMiddleware.init_app") as mock_init:
        m = CorrelationIDMiddleware(fake_app)
        assert m.app is fake_app
        mock_init.assert_called_once_with(fake_app)


def test_CorrelationIDMiddleware_init_app_registers_handlers(middleware):
    """init_app should register before_request and after_request handlers and set app attribute."""
    mock_app = Mock()
    # Ensure attributes exist for assignment
    mock_app.before_request = Mock()
    mock_app.after_request = Mock()

    middleware.init_app(mock_app)

    assert mock_app.before_request.call_count == 1
    assert mock_app.after_request.call_count == 1

    # Validate that callables are the middleware methods
    args_before, _ = mock_app.before_request.call_args
    args_after, _ = mock_app.after_request.call_args
    assert args_before[0] == middleware.before_request
    assert args_after[0] == middleware.after_request

    # Attribute set
    assert hasattr(mock_app, "correlation_start_time")
    assert mock_app.correlation_start_time is None


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_uses_valid_header(middleware):
    """extract_or_generate_correlation_id should return existing valid correlation ID from headers."""
    fake_request = Mock()
    valid_id = "valid-12345-id"
    fake_request.headers = {CORRELATION_ID_HEADER: valid_id}
    with patch.object(CorrelationIDMiddleware, "is_valid_correlation_id", return_value=True) as mock_valid:
        result = middleware.extract_or_generate_correlation_id(fake_request)
        assert result == valid_id
        mock_valid.assert_called_once_with(valid_id)


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_generates_if_invalid_or_missing(middleware):
    """extract_or_generate_correlation_id should generate a new ID when incoming header is missing or invalid."""
    fake_request = Mock()
    fake_request.headers = {CORRELATION_ID_HEADER: "invalid@id"}
    with patch.object(CorrelationIDMiddleware, "is_valid_correlation_id", return_value=False), \
         patch.object(CorrelationIDMiddleware, "generate_correlation_id", return_value="generated-id") as mock_gen:
        result = middleware.extract_or_generate_correlation_id(fake_request)
        assert result == "generated-id"
        mock_gen.assert_called_once()


def test_CorrelationIDMiddleware_generate_correlation_id_uses_time(middleware):
    """generate_correlation_id should include time-derived components deterministically when time is mocked."""
    with patch("src.correlation_middleware.time.time", return_value=1700000000.123456):
        generated = middleware.generate_correlation_id()
        assert generated == "1700000000-py-23456"


def test_CorrelationIDMiddleware_is_valid_correlation_id_various(middleware):
    """is_valid_correlation_id should validate different input cases correctly."""
    assert middleware.is_valid_correlation_id("valid-OK_id123") is True
    assert middleware.is_valid_correlation_id("short") is False
    assert middleware.is_valid_correlation_id("a" * 101) is False
    assert middleware.is_valid_correlation_id("inv@lid") is False
    assert middleware.is_valid_correlation_id(12345) is False


def test_CorrelationIDMiddleware_before_request_sets_context(app, middleware):
    """before_request should set g.correlation_id and g.request_start_time."""
    with app.test_request_context("/test", method="GET"):
        with patch.object(CorrelationIDMiddleware, "extract_or_generate_correlation_id", return_value="cid-abc") as mock_extract, \
             patch("src.correlation_middleware.time.time", return_value=100.0):
            middleware.before_request()
            assert g.correlation_id == "cid-abc"
            assert g.request_start_time == 100.0
            mock_extract.assert_called_once()


def test_CorrelationIDMiddleware_after_request_sets_header_and_stores_trace(app, middleware):
    """after_request should add correlation ID header and store a trace record."""
    class FakeDateTime:
        @staticmethod
        def now():
            return real_datetime(2020, 1, 1, 0, 0, 0)

        @staticmethod
        def fromisoformat(s):
            return real_datetime.fromisoformat(s)

    with app.test_request_context("/hello", method="GET"):
        g.correlation_id = "cid-xyz"
        g.request_start_time = 100.0
        response = app.response_class("ok", status=201)

        with patch("src.correlation_middleware.time.time", return_value=100.2), \
             patch("src.correlation_middleware.datetime", new=FakeDateTime):
            updated_response = middleware.after_request(response)

        assert updated_response.headers[CORRELATION_ID_HEADER] == "cid-xyz"

        traces = get_traces("cid-xyz")
        assert len(traces) == 1
        t = traces[0]
        assert t["service"] == "python-reviewer"
        assert t["method"] == "GET"
        assert t["path"] == "/hello"
        assert t["timestamp"] == "2020-01-01T00:00:00"
        assert t["correlation_id"] == "cid-xyz"
        assert t["duration_ms"] == 200.0
        assert t["status"] == 201


def test_CorrelationIDMiddleware_after_request_without_correlation_id_noop(app, middleware):
    """after_request should not set header or store trace when correlation ID is missing."""
    with app.test_request_context("/noop", method="GET"):
        # g.correlation_id is intentionally not set
        response = app.response_class("ok", status=200)
        updated = middleware.after_request(response)
        assert CORRELATION_ID_HEADER not in updated.headers
        assert get_all_traces() == {}


def test_cleanup_old_traces_removes_expired():
    """cleanup_old_traces should remove trace groups whose oldest trace is older than 1 hour."""
    # Prepare trace storage with timestamps
    trace_storage["old"] = [{"timestamp": "2020-01-01T00:00:00"}]
    trace_storage["new"] = [{"timestamp": "2020-01-01T02:00:00"}]

    class FakeDateTime:
        @staticmethod
        def now():
            return real_datetime(2020, 1, 1, 3, 0, 0)  # cutoff = 02:00:00

        @staticmethod
        def fromisoformat(s):
            return real_datetime.fromisoformat(s)

    with patch("src.correlation_middleware.datetime", new=FakeDateTime):
        cleanup_old_traces()

    assert "old" not in trace_storage
    assert "new" in trace_storage


def test_get_traces_and_get_all_traces_return_copies():
    """get_traces and get_all_traces should return copies that do not mutate underlying storage."""
    trace_storage["cid1"] = [{"timestamp": "2020-01-01T00:00:00", "path": "/a"}]
    trace_storage["cid2"] = [{"timestamp": "2020-01-01T00:00:01", "path": "/b"}]

    traces_copy = get_traces("cid1")
    all_copy = get_all_traces()

    # mutate copies
    traces_copy.append({"timestamp": "2020-01-01T00:00:02", "path": "/c"})
    all_copy["cid1"].append({"timestamp": "2020-01-01T00:00:03", "path": "/d"})

    # original storage should remain unchanged
    assert len(trace_storage["cid1"]) == 1
    assert len(trace_storage["cid2"]) == 1


def test_CorrelationIDMiddleware_after_request_propagates_store_trace_exceptions(app, middleware):
    """after_request should propagate exceptions raised by store_trace."""
    with app.test_request_context("/error", method="GET"):
        g.correlation_id = "cid-error"
        g.request_start_time = 0.0
        response = app.response_class("err", status=500)

        with patch("src.correlation_middleware.store_trace", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                middleware.after_request(response)


def test_integration_flask_request_response_headers_and_trace(app):
    """Full integration: middleware should propagate/echo header and store trace."""
    # Setup route
    @app.route("/ping", methods=["GET"])
    def ping():
        return "pong", 200

    # Register middleware
    mw = CorrelationIDMiddleware()
    mw.init_app(app)

    client = app.test_client()
    incoming_cid = "abcdefghijk-valid-12345"

    resp = client.get("/ping", headers={CORRELATION_ID_HEADER: incoming_cid})
    assert resp.status_code == 200
    assert resp.headers[CORRELATION_ID_HEADER] == incoming_cid

    traces = get_traces(incoming_cid)
    assert len(traces) == 1
    assert traces[0]["method"] == "GET"
    assert traces[0]["path"] == "/ping"
    assert traces[0]["status"] == 200