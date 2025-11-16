import importlib
import types
from datetime import datetime
from unittest.mock import patch

import pytest

from src.correlation_middleware import (
    CORRELATION_ID_HEADER,
    CorrelationIDMiddleware,
)


@pytest.fixture
def middleware_instance():
    """Create CorrelationIDMiddleware instance for testing."""
    return CorrelationIDMiddleware()


@pytest.fixture
def install_fake_flask(monkeypatch):
    """Install a fake 'flask' module with request and g for testing middleware."""
    modules_to_restore = {}

    def _install(request_obj=None, g_obj=None):
        import sys

        if "flask" in sys.modules:
            modules_to_restore["flask"] = sys.modules["flask"]

        flask_mod = types.ModuleType("flask")
        if request_obj is None:
            request_obj = types.SimpleNamespace(headers={}, method="GET", path="/")
        if g_obj is None:
            g_obj = types.SimpleNamespace()
        flask_mod.request = request_obj
        flask_mod.g = g_obj

        monkeypatch.setitem(sys.modules, "flask", flask_mod)
        return flask_mod, request_obj, g_obj

    yield _install

    # Restore original flask module if it existed
    import sys

    if "flask" in modules_to_restore:
        sys.modules["flask"] = modules_to_restore["flask"]
    else:
        sys.modules.pop("flask", None)


def test_CorrelationIDMiddleware___init___without_app_does_not_call_init_app():
    """Ensure __init__ with app=None does not call init_app."""
    with patch.object(CorrelationIDMiddleware, "init_app") as mock_init:
        instance = CorrelationIDMiddleware()
        assert isinstance(instance, CorrelationIDMiddleware)
        mock_init.assert_not_called()


def test_CorrelationIDMiddleware___init___with_app_calls_init_app():
    """Ensure __init__ with app parameter calls init_app(app)."""
    fake_app = object()
    with patch.object(CorrelationIDMiddleware, "init_app") as mock_init:
        instance = CorrelationIDMiddleware(app=fake_app)
        assert isinstance(instance, CorrelationIDMiddleware)
        mock_init.assert_called_once_with(fake_app)


def test_CorrelationIDMiddleware_init_app_registers_hooks(middleware_instance):
    """Ensure init_app registers before_request and after_request and sets correlation_start_time."""
    class FakeApp:
        def __init__(self):
            self._before = None
            self._after = None
            self.correlation_start_time = "not-none"  # Will be set to None by init_app

        def before_request(self, func):
            self._before = func

        def after_request(self, func):
            self._after = func

    app = FakeApp()
    middleware_instance.init_app(app)

    assert app._before == middleware_instance.before_request
    assert app._after == middleware_instance.after_request
    assert app.correlation_start_time is None


def test_CorrelationIDMiddleware_is_valid_correlation_id_various_cases(middleware_instance):
    """Validate different correlation ID values for edge cases."""
    # Non-string
    assert middleware_instance.is_valid_correlation_id(123) is False
    # Too short
    assert middleware_instance.is_valid_correlation_id("short") is False
    # Too long
    long_id = "a" * 101
    assert middleware_instance.is_valid_correlation_id(long_id) is False
    # Invalid characters (space and punctuation)
    assert middleware_instance.is_valid_correlation_id("invalid id") is False
    assert middleware_instance.is_valid_correlation_id("invalid!") is False
    # Valid characters and lengths
    assert middleware_instance.is_valid_correlation_id("abcdefghij") is True  # length 10
    assert middleware_instance.is_valid_correlation_id("a" * 100) is True  # length 100
    assert middleware_instance.is_valid_correlation_id("abcde-ABCDE_12345") is True


def test_CorrelationIDMiddleware_generate_correlation_id_format(middleware_instance, monkeypatch):
    """Ensure generate_correlation_id format matches expected time-based pattern."""
    # Patch time to a fixed value
    cm = importlib.import_module("src.correlation_middleware")

    def fake_time():
        return 1700000000.123456

    monkeypatch.setattr(cm.time, "time", fake_time)
    cid = middleware_instance.generate_correlation_id()
    # Expected: "1700000000-py-23456"
    assert cid.startswith("1700000000-py-")
    assert cid == "1700000000-py-23456"


def test_CorrelationIDMiddleware_generate_correlation_id_uniqueness(monkeypatch):
    """Ensure generate_correlation_id produces different IDs on subsequent calls."""
    cm = importlib.import_module("src.correlation_middleware")

    times = iter([1000.0, 1000.0, 1000.2, 1000.2])  # two calls, each uses time twice

    def fake_time():
        return next(times)

    monkeypatch.setattr(cm.time, "time", fake_time)
    cid1 = CorrelationIDMiddleware.generate_correlation_id()
    cid2 = CorrelationIDMiddleware.generate_correlation_id()
    assert cid1 != cid2
    assert "-py-" in cid1 and "-py-" in cid2


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_uses_existing_valid(middleware_instance):
    """If a valid header is present, it should be returned unchanged."""
    request_obj = types.SimpleNamespace(
        headers={CORRELATION_ID_HEADER: "valid-ABC_def-12345"},
        method="GET",
        path="/api",
    )
    cid = middleware_instance.extract_or_generate_correlation_id(request_obj)
    assert cid == "valid-ABC_def-12345"


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_generates_when_invalid(middleware_instance, monkeypatch):
    """If header is missing or invalid, it should generate a new correlation ID."""
    request_obj = types.SimpleNamespace(
        headers={CORRELATION_ID_HEADER: "bad!"},  # invalid char
        method="GET",
        path="/api",
    )
    monkeypatch.setattr(
        middleware_instance, "generate_correlation_id", lambda: "generated-xyz-12345"
    )
    cid = middleware_instance.extract_or_generate_correlation_id(request_obj)
    assert cid == "generated-xyz-12345"


def test_CorrelationIDMiddleware_before_request_sets_g_and_start_time(middleware_instance, install_fake_flask, monkeypatch):
    """before_request should set g.correlation_id and g.request_start_time."""
    # Install fake flask
    _, request_obj, g_obj = install_fake_flask(
        request_obj=types.SimpleNamespace(headers={}, method="POST", path="/submit"),
        g_obj=types.SimpleNamespace(),
    )
    # Make extract return a known value
    monkeypatch.setattr(
        middleware_instance, "extract_or_generate_correlation_id", lambda req: "cid-1234567890"
    )
    # Patch time to a known value
    cm = importlib.import_module("src.correlation_middleware")
    monkeypatch.setattr(cm.time, "time", lambda: 1000.5)

    middleware_instance.before_request()
    assert getattr(g_obj, "correlation_id") == "cid-1234567890"
    assert getattr(g_obj, "request_start_time") == 1000.5


def test_CorrelationIDMiddleware_before_request_raises_if_extraction_fails(middleware_instance, install_fake_flask):
    """before_request should propagate exceptions from extract_or_generate_correlation_id."""
    install_fake_flask(
        request_obj=types.SimpleNamespace(headers={}, method="GET", path="/"),
        g_obj=types.SimpleNamespace(),
    )
    with patch.object(
        middleware_instance, "extract_or_generate_correlation_id", side_effect=RuntimeError("boom")
    ):
        with pytest.raises(RuntimeError):
            middleware_instance.before_request()


def test_CorrelationIDMiddleware_after_request_sets_header_and_stores_trace(middleware_instance, install_fake_flask, monkeypatch):
    """after_request should set correlation header and call store_trace with correct data."""
    # Setup fake flask and request context
    _, request_obj, g_obj = install_fake_flask(
        request_obj=types.SimpleNamespace(headers={}, method="GET", path="/test"),
        g_obj=types.SimpleNamespace(),
    )
    g_obj.correlation_id = "abcde-ABCDE_12345"
    g_obj.request_start_time = 100.0

    # Dummy response
    class DummyResponse:
        def __init__(self):
            self.headers = {}
            self.status_code = 200

    response = DummyResponse()

    # Patch time to compute known duration
    cm = importlib.import_module("src.correlation_middleware")
    monkeypatch.setattr(cm.time, "time", lambda: 100.256)

    # Patch store_trace to capture call
    with patch("src.correlation_middleware.store_trace") as mock_store:
        out = middleware_instance.after_request(response)

        # Response unchanged object, headers updated
        assert out is response
        assert response.headers[CORRELATION_ID_HEADER] == "abcde-ABCDE_12345"

        # Validate store_trace call and payload
        mock_store.assert_called_once()
        args, kwargs = mock_store.call_args
        assert args[0] == "abcde-ABCDE_12345"
        trace_data = args[1]
        assert trace_data["service"] == "python-reviewer"
        assert trace_data["method"] == "GET"
        assert trace_data["path"] == "/test"
        assert trace_data["correlation_id"] == "abcde-ABCDE_12345"
        assert trace_data["status"] == 200
        assert isinstance(trace_data["timestamp"], str)
        # Parseable timestamp
        datetime.fromisoformat(trace_data["timestamp"])
        # Duration approx 256.0 ms rounded to 2 decimals
        assert trace_data["duration_ms"] == pytest.approx(256.0, rel=0, abs=0.01)


def test_CorrelationIDMiddleware_after_request_without_correlation_id_no_header_no_store(middleware_instance, install_fake_flask):
    """after_request should not set header or call store_trace when correlation_id missing."""
    _, request_obj, g_obj = install_fake_flask(
        request_obj=types.SimpleNamespace(headers={}, method="POST", path="/no-cid"),
        g_obj=types.SimpleNamespace(),
    )

    class DummyResponse:
        def __init__(self):
            self.headers = {}
            self.status_code = 204

    response = DummyResponse()

    with patch("src.correlation_middleware.store_trace") as mock_store:
        out = middleware_instance.after_request(response)
        assert out is response
        assert CORRELATION_ID_HEADER not in response.headers
        mock_store.assert_not_called()