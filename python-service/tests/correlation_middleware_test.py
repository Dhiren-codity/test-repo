import sys
import types
from datetime import datetime
from types import SimpleNamespace

import pytest
from unittest.mock import Mock, patch

from src.correlation_middleware import CorrelationIDMiddleware, CORRELATION_ID_HEADER


class DummyApp:
    def __init__(self):
        self.befores = []
        self.afters = []
        self.correlation_start_time = "not_none"

    def before_request(self, func):
        self.befores.append(func)

    def after_request(self, func):
        self.afters.append(func)


class DummyResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.headers = {}


@pytest.fixture
def middleware_instance():
    """Create a CorrelationIDMiddleware instance for testing."""
    return CorrelationIDMiddleware()


@pytest.fixture
def flask_stub(monkeypatch):
    """Provide a stubbed 'flask' module with request and g objects."""
    mod = types.ModuleType("flask")
    req = SimpleNamespace(headers={}, method="GET", path="/")
    g = SimpleNamespace()
    mod.request = req
    mod.g = g
    monkeypatch.setitem(sys.modules, "flask", mod)
    return mod


def test_CorrelationIDMiddleware___init___with_app_calls_init_app():
    """Ensure __init__ calls init_app when app is provided."""
    app = DummyApp()
    with patch.object(CorrelationIDMiddleware, "init_app") as mock_init:
        m = CorrelationIDMiddleware(app=app)
        assert m.app is app
        mock_init.assert_called_once_with(app)


def test_CorrelationIDMiddleware___init___without_app_does_not_call_init_app():
    """Ensure __init__ does not call init_app when app is None."""
    with patch.object(CorrelationIDMiddleware, "init_app") as mock_init:
        m = CorrelationIDMiddleware()
        assert m.app is None
        mock_init.assert_not_called()


def test_CorrelationIDMiddleware_init_app_registers_hooks_and_sets_attr(middleware_instance):
    """Ensure init_app wires before/after request hooks and sets app attributes."""
    app = DummyApp()
    middleware_instance.init_app(app)

    # Hooks registered
    assert len(app.befores) == 1
    assert len(app.afters) == 1

    # Hooks are bound to the middleware instance
    before = app.befores[0]
    after = app.afters[0]
    assert callable(before)
    assert callable(after)
    assert getattr(before, "__self__", None) is middleware_instance
    assert getattr(after, "__self__", None) is middleware_instance
    assert getattr(before, "__name__", "") == "before_request"
    assert getattr(after, "__name__", "") == "after_request"

    # App attribute set
    assert app.correlation_start_time is None


def test_CorrelationIDMiddleware_generate_correlation_id_deterministic_time(middleware_instance):
    """Ensure generate_correlation_id formats and uses time correctly."""
    with patch("src.correlation_middleware.time.time", return_value=1234.56789):
        cid = middleware_instance.generate_correlation_id()
    assert cid == "1234-py-67890"


def test_CorrelationIDMiddleware_is_valid_correlation_id_non_string_returns_false(middleware_instance):
    """is_valid_correlation_id returns False for non-string inputs."""
    assert middleware_instance.is_valid_correlation_id(None) is False
    assert middleware_instance.is_valid_correlation_id(123) is False


def test_CorrelationIDMiddleware_is_valid_correlation_id_too_short_returns_false(middleware_instance):
    """is_valid_correlation_id returns False for IDs shorter than 10 chars."""
    assert middleware_instance.is_valid_correlation_id("short-id") is False  # len 8


def test_CorrelationIDMiddleware_is_valid_correlation_id_too_long_returns_false(middleware_instance):
    """is_valid_correlation_id returns False for IDs longer than 100 chars."""
    long_id = "a" * 101
    assert middleware_instance.is_valid_correlation_id(long_id) is False


def test_CorrelationIDMiddleware_is_valid_correlation_id_invalid_charset_returns_false(middleware_instance):
    """is_valid_correlation_id returns False for IDs with invalid characters."""
    assert middleware_instance.is_valid_correlation_id("invalid.id.value") is False  # '.' not allowed


def test_CorrelationIDMiddleware_is_valid_correlation_id_valid_returns_true(middleware_instance):
    """is_valid_correlation_id returns True for valid IDs."""
    assert middleware_instance.is_valid_correlation_id("abc-DEF_1234") is True


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_header_valid(middleware_instance):
    """extract_or_generate_correlation_id returns existing header when valid."""
    req = SimpleNamespace(headers={CORRELATION_ID_HEADER: "valid-id-12345"})
    cid = middleware_instance.extract_or_generate_correlation_id(req)
    assert cid == "valid-id-12345"


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_header_missing_generates(middleware_instance):
    """extract_or_generate_correlation_id generates when header is missing."""
    req = SimpleNamespace(headers={})
    with patch.object(middleware_instance, "generate_correlation_id", return_value="gen-xyz") as mock_gen:
        cid = middleware_instance.extract_or_generate_correlation_id(req)
    assert cid == "gen-xyz"
    mock_gen.assert_called_once()


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_header_invalid_generates(middleware_instance):
    """extract_or_generate_correlation_id generates when header is invalid."""
    req = SimpleNamespace(headers={CORRELATION_ID_HEADER: "bad.id"})
    with patch.object(middleware_instance, "generate_correlation_id", return_value="gen-abc") as mock_gen:
        cid = middleware_instance.extract_or_generate_correlation_id(req)
    assert cid == "gen-abc"
    mock_gen.assert_called_once()


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_header_non_string_generates(middleware_instance):
    """extract_or_generate_correlation_id generates when header is non-string."""
    req = SimpleNamespace(headers={CORRELATION_ID_HEADER: 12345})
    with patch.object(middleware_instance, "generate_correlation_id", return_value="gen-123") as mock_gen:
        cid = middleware_instance.extract_or_generate_correlation_id(req)
    assert cid == "gen-123"
    mock_gen.assert_called_once()


def test_CorrelationIDMiddleware_before_request_sets_context_and_start_time(middleware_instance, flask_stub):
    """before_request sets g.correlation_id and g.request_start_time."""
    flask_stub.request.headers = {CORRELATION_ID_HEADER: "hdr-id-123456"}
    with patch.object(
        middleware_instance, "extract_or_generate_correlation_id", return_value="cid-1234567890"
    ) as mock_extract, patch("src.correlation_middleware.time.time", return_value=100.5):
        middleware_instance.before_request()
        mock_extract.assert_called_once_with(flask_stub.request)

    assert flask_stub.g.correlation_id == "cid-1234567890"
    assert flask_stub.g.request_start_time == 100.5


def test_CorrelationIDMiddleware_after_request_sets_header_and_calls_store_trace(middleware_instance, flask_stub):
    """after_request sets response header and stores trace with correct data."""
    flask_stub.g.correlation_id = "cid-xyz"
    flask_stub.g.request_start_time = 200.0
    flask_stub.request.method = "POST"
    flask_stub.request.path = "/items/42"
    response = DummyResponse(status_code=201)

    with patch("src.correlation_middleware.time.time", return_value=200.12345), patch(
        "src.correlation_middleware.store_trace"
    ) as mock_store:
        result = middleware_instance.after_request(response)

    assert result is response
    assert response.headers[CORRELATION_ID_HEADER] == "cid-xyz"
    mock_store.assert_called_once()

    # Validate trace payload
    called_args, called_kwargs = mock_store.call_args
    assert called_args[0] == "cid-xyz"
    trace = called_args[1]
    assert trace["service"] == "python-reviewer"
    assert trace["method"] == "POST"
    assert trace["path"] == "/items/42"
    assert trace["correlation_id"] == "cid-xyz"
    assert trace["duration_ms"] == 123.45
    assert trace["status"] == 201
    # Valid ISO timestamp
    datetime.fromisoformat(trace["timestamp"])


def test_CorrelationIDMiddleware_after_request_without_correlation_id_no_header_no_store(middleware_instance, flask_stub):
    """after_request should not set header or store trace when correlation_id is missing."""
    # Ensure no correlation_id set
    if hasattr(flask_stub.g, "correlation_id"):
        delattr(flask_stub.g, "correlation_id")

    response = DummyResponse(status_code=200)
    with patch("src.correlation_middleware.store_trace") as mock_store:
        result = middleware_instance.after_request(response)

    assert result is response
    assert CORRELATION_ID_HEADER not in response.headers
    mock_store.assert_not_called()


def test_CorrelationIDMiddleware_after_request_missing_start_time_uses_current_time(middleware_instance, flask_stub):
    """after_request uses current time when start time is missing, leading to ~0 duration."""
    flask_stub.g.correlation_id = "cid-no-start"
    # Ensure request_start_time is missing
    if hasattr(flask_stub.g, "request_start_time"):
        delattr(flask_stub.g, "request_start_time")

    flask_stub.request.method = "GET"
    flask_stub.request.path = "/ping"
    response = DummyResponse(status_code=200)

    with patch("src.correlation_middleware.time.time", return_value=300.0), patch(
        "src.correlation_middleware.store_trace"
    ) as mock_store:
        middleware_instance.after_request(response)

    # Duration should be 0.0 due to same timestamps
    called_args, _ = mock_store.call_args
    trace = called_args[1]
    assert trace["duration_ms"] == 0.0


def test_CorrelationIDMiddleware_after_request_store_trace_exception_propagates(middleware_instance, flask_stub):
    """after_request should propagate exceptions thrown by store_trace."""
    flask_stub.g.correlation_id = "cid-error"
    flask_stub.g.request_start_time = 10.0
    flask_stub.request.method = "GET"
    flask_stub.request.path = "/error"
    response = DummyResponse(status_code=500)

    with patch("src.correlation_middleware.store_trace", side_effect=RuntimeError("boom")), pytest.raises(
        RuntimeError
    ):
        middleware_instance.after_request(response)