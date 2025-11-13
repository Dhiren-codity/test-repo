import pytest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from datetime import datetime

from src.correlation_middleware import (
    CorrelationIDMiddleware,
    CORRELATION_ID_HEADER,
    trace_storage,
)


class FakeApp:
    def __init__(self):
        self.before_handlers = []
        self.after_handlers = []
        self.correlation_start_time = "should be set to None"

    def before_request(self, func):
        self.before_handlers.append(func)
        return func

    def after_request(self, func):
        self.after_handlers.append(func)
        return func


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.headers = {}


@pytest.fixture(autouse=True)
def clear_trace_storage():
    """Clear the global trace storage before each test."""
    trace_storage.clear()
    yield
    trace_storage.clear()


@pytest.fixture
def middleware_instance():
    """Create a CorrelationIDMiddleware instance for testing."""
    return CorrelationIDMiddleware()


@pytest.fixture
def fake_response():
    """Create a fake Flask-like response object."""
    return FakeResponse(status_code=200)


def test_CorrelationIDMiddleware___init___without_app_does_not_call_init_app():
    """Ensure __init__ does not call init_app when app is None."""
    with patch.object(CorrelationIDMiddleware, "init_app") as mock_init_app:
        mw = CorrelationIDMiddleware(app=None)
        assert mw.app is None
        mock_init_app.assert_not_called()


def test_CorrelationIDMiddleware___init___with_app_calls_init_app():
    """Ensure __init__ calls init_app when app is provided."""
    app = FakeApp()
    with patch.object(CorrelationIDMiddleware, "init_app") as mock_init_app:
        mw = CorrelationIDMiddleware(app=app)
        assert mw.app is app
        mock_init_app.assert_called_once_with(app)


def test_CorrelationIDMiddleware_init_app_registers_handlers(middleware_instance):
    """Ensure init_app registers before_request and after_request handlers and sets attribute."""
    app = FakeApp()
    middleware_instance.init_app(app)
    assert app.correlation_start_time is None
    assert len(app.before_handlers) == 1
    assert len(app.after_handlers) == 1
    assert app.before_handlers[0] is middleware_instance.before_request
    assert app.after_handlers[0] is middleware_instance.after_request


def test_CorrelationIDMiddleware_before_request_sets_g_and_start_time(middleware_instance):
    """before_request should set g.correlation_id and g.request_start_time."""
    fake_request = SimpleNamespace(headers={})
    fake_g = SimpleNamespace()

    with patch("flask.request", fake_request), \
         patch("flask.g", fake_g), \
         patch.object(middleware_instance, "extract_or_generate_correlation_id", return_value="cid-123") as mock_extract, \
         patch("src.correlation_middleware.time.time", return_value=1000.5):

        middleware_instance.before_request()
        mock_extract.assert_called_once_with(fake_request)
        assert getattr(fake_g, "correlation_id", None) == "cid-123"
        assert getattr(fake_g, "request_start_time", None) == 1000.5


def test_CorrelationIDMiddleware_after_request_sets_header_and_stores_trace(middleware_instance, fake_response):
    """after_request should set response header and call store_trace with correct data."""
    fake_g = SimpleNamespace(correlation_id="cid-1", request_start_time=100.0)
    fake_request = SimpleNamespace(method="GET", path="/test")

    with patch("flask.g", fake_g), \
         patch("flask.request", fake_request), \
         patch("src.correlation_middleware.time.time", return_value=100.123), \
         patch("src.correlation_middleware.store_trace") as mock_store:

        result = middleware_instance.after_request(fake_response)

        assert result is fake_response
        assert fake_response.headers.get(CORRELATION_ID_HEADER) == "cid-1"
        mock_store.assert_called_once()
        args, kwargs = mock_store.call_args
        assert args[0] == "cid-1"
        trace = args[1]
        assert trace["service"] == "python-reviewer"
        assert trace["method"] == "GET"
        assert trace["path"] == "/test"
        assert trace["correlation_id"] == "cid-1"
        assert trace["status"] == 200
        assert trace["duration_ms"] == 123.0
        # Validate timestamp is ISO format
        datetime.fromisoformat(trace["timestamp"])


def test_CorrelationIDMiddleware_after_request_no_correlation_id_does_nothing(middleware_instance, fake_response):
    """after_request should not set header or store trace when no correlation_id present."""
    fake_g = SimpleNamespace()  # no correlation_id
    fake_request = SimpleNamespace(method="POST", path="/no-cid")

    with patch("flask.g", fake_g), \
         patch("flask.request", fake_request), \
         patch("src.correlation_middleware.store_trace") as mock_store:

        result = middleware_instance.after_request(fake_response)

        assert result is fake_response
        assert CORRELATION_ID_HEADER not in fake_response.headers
        mock_store.assert_not_called()


def test_CorrelationIDMiddleware_after_request_missing_start_time_uses_current_time(middleware_instance, fake_response):
    """after_request should compute duration from current time when start time is missing."""
    fake_g = SimpleNamespace(correlation_id="cid-2")  # request_start_time missing
    fake_request = SimpleNamespace(method="GET", path="/duration")

    with patch("flask.g", fake_g), \
         patch("flask.request", fake_request), \
         patch("src.correlation_middleware.time.time", side_effect=[200.0, 200.25]), \
         patch("src.correlation_middleware.store_trace") as mock_store:

        middleware_instance.after_request(fake_response)

        # First time.time() used for start_time default, second for end time
        args, _ = mock_store.call_args
        trace = args[1]
        assert trace["duration_ms"] == 250.0
        assert fake_response.headers.get(CORRELATION_ID_HEADER) == "cid-2"


def test_CorrelationIDMiddleware_extract_or_generate_returns_existing_valid(middleware_instance):
    """extract_or_generate_correlation_id returns existing valid header value."""
    existing_id = "valid-id-12345"
    request = SimpleNamespace(headers={CORRELATION_ID_HEADER: existing_id})

    result = middleware_instance.extract_or_generate_correlation_id(request)
    assert result == existing_id


def test_CorrelationIDMiddleware_extract_or_generate_invalid_triggers_generate(middleware_instance):
    """extract_or_generate_correlation_id calls generator when header is invalid."""
    request = SimpleNamespace(headers={CORRELATION_ID_HEADER: "bad id"})
    with patch.object(middleware_instance, "is_valid_correlation_id", return_value=False) as mock_valid, \
         patch.object(middleware_instance, "generate_correlation_id", return_value="gen-abc") as mock_gen:

        result = middleware_instance.extract_or_generate_correlation_id(request)
        mock_valid.assert_called_once()
        mock_gen.assert_called_once()
        assert result == "gen-abc"


def test_CorrelationIDMiddleware_generate_correlation_id_deterministic_with_time_patch():
    """generate_correlation_id should produce deterministic string based on patched time."""
    with patch("src.correlation_middleware.time.time", return_value=1000.123456):
        result = CorrelationIDMiddleware.generate_correlation_id()
        assert result == "1000-py-23456"


def test_CorrelationIDMiddleware_is_valid_correlation_id_edge_cases():
    """is_valid_correlation_id should handle non-strings, length bounds, and charset."""
    # Non-string
    assert CorrelationIDMiddleware.is_valid_correlation_id(123) is False
    # Too short
    assert CorrelationIDMiddleware.is_valid_correlation_id("short") is False
    # Too long
    too_long = "a" * 101
    assert CorrelationIDMiddleware.is_valid_correlation_id(too_long) is False
    # Invalid charset (contains '*'), ensure length >= 10
    assert CorrelationIDMiddleware.is_valid_correlation_id("invalid*id___") is False
    # Valid case
    assert CorrelationIDMiddleware.is_valid_correlation_id("abc-DEF_12345") is True


def test_CorrelationIDMiddleware_after_request_propagates_exception_from_store_trace(middleware_instance):
    """after_request should propagate exceptions raised by store_trace; header is still set before error."""
    fake_g = SimpleNamespace(correlation_id="cid-ex", request_start_time=50.0)
    fake_request = SimpleNamespace(method="GET", path="/error")
    response = FakeResponse(status_code=500)

    with patch("flask.g", fake_g), \
         patch("flask.request", fake_request), \
         patch("src.correlation_middleware.store_trace", side_effect=RuntimeError("boom")):

        with pytest.raises(RuntimeError):
            middleware_instance.after_request(response)

        # Header was set before exception occurred
        assert response.headers.get(CORRELATION_ID_HEADER) == "cid-ex"