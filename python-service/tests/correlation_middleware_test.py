import re
import types
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.correlation_middleware import (
    CorrelationIDMiddleware,
    CORRELATION_ID_HEADER,
    store_trace,
    get_traces,
    get_all_traces,
    cleanup_old_traces,
    trace_storage,
    trace_lock,
)


@pytest.fixture(autouse=True)
def reset_trace_storage():
    """Ensure trace storage is clean before and after each test."""
    with trace_lock:
        trace_storage.clear()
    yield
    with trace_lock:
        trace_storage.clear()


@pytest.fixture
def middleware_instance():
    """Create a CorrelationIDMiddleware instance for testing."""
    return CorrelationIDMiddleware()


def install_fake_flask(monkeypatch, headers=None, method="GET", path="/"):
    """
    Install a fake 'flask' module with minimal request and g objects.
    Returns the fake g object for inspection.
    """
    fake_flask = types.ModuleType("flask")
    req = SimpleNamespace(
        headers=headers or {},
        method=method,
        path=path,
    )
    g = SimpleNamespace()
    fake_flask.request = req
    fake_flask.g = g
    monkeypatch.setitem(__import__("sys").modules, "flask", fake_flask)
    return g, req


def test_correlationidmiddleware___init___with_none_app():
    """Ensure __init__ with app=None sets the app attribute and does not fail."""
    mw = CorrelationIDMiddleware(app=None)
    assert mw.app is None


def test_correlationidmiddleware_init_app_registers_hooks(middleware_instance):
    """init_app should register before_request and after_request and set an attribute on app."""
    class DummyApp:
        def __init__(self):
            self._before = []
            self._after = []
            self.correlation_start_time = "not_none"

        def before_request(self, func):
            self._before.append(func)

        def after_request(self, func):
            self._after.append(func)

    app = DummyApp()
    middleware_instance.init_app(app)

    assert middleware_instance.before_request in app._before
    assert middleware_instance.after_request in app._after
    assert app.correlation_start_time is None


def test_correlationidmiddleware___init___with_app_auto_registration():
    """Passing app to __init__ should auto-register hooks via init_app."""
    class DummyApp:
        def __init__(self):
            self._before = []
            self._after = []
            self.correlation_start_time = "x"

        def before_request(self, func):
            self._before.append(func)

        def after_request(self, func):
            self._after.append(func)

    app = DummyApp()
    mw = CorrelationIDMiddleware(app=app)
    assert mw.app is app
    assert mw.before_request in app._before
    assert mw.after_request in app._after
    assert app.correlation_start_time is None


def test_correlationidmiddleware_extract_or_generate_correlation_id_uses_valid_inbound_header(middleware_instance):
    """extract_or_generate_correlation_id should use a valid inbound header."""
    class FakeRequest:
        def __init__(self, headers):
            self.headers = headers

    existing = "valid-abcde-12345"
    req = FakeRequest(headers={CORRELATION_ID_HEADER: existing})

    result = middleware_instance.extract_or_generate_correlation_id(req)
    assert result == existing


def test_correlationidmiddleware_extract_or_generate_correlation_id_generates_when_missing(monkeypatch, middleware_instance):
    """extract_or_generate_correlation_id should generate a new ID when header is missing."""
    class FakeRequest:
        def __init__(self, headers):
            self.headers = headers

    generated = "gen-1234567890"
    monkeypatch.setattr(middleware_instance, "generate_correlation_id", lambda: generated)

    req = FakeRequest(headers={})
    result = middleware_instance.extract_or_generate_correlation_id(req)
    assert result == generated


def test_correlationidmiddleware_extract_or_generate_correlation_id_generates_when_invalid(monkeypatch, middleware_instance):
    """extract_or_generate_correlation_id should generate a new ID when header is invalid."""
    class FakeRequest:
        def __init__(self, headers):
            self.headers = headers

    generated = "gen-0987654321"
    monkeypatch.setattr(middleware_instance, "generate_correlation_id", lambda: generated)

    # Invalid: too short
    req = FakeRequest(headers={CORRELATION_ID_HEADER: "short"})
    result = middleware_instance.extract_or_generate_correlation_id(req)
    assert result == generated


def test_correlationidmiddleware_is_valid_correlation_id_various_cases(middleware_instance):
    """is_valid_correlation_id should validate strings with allowed chars and length constraints."""
    assert middleware_instance.is_valid_correlation_id(123) is False  # non-str
    assert middleware_instance.is_valid_correlation_id("short") is False  # length < 10
    assert middleware_instance.is_valid_correlation_id("a" * 101) is False  # length > 100
    assert middleware_instance.is_valid_correlation_id("invalid id!*") is False  # invalid chars

    assert middleware_instance.is_valid_correlation_id("a" * 10) is True  # exactly min length
    assert middleware_instance.is_valid_correlation_id("a" * 100) is True  # exactly max length
    assert middleware_instance.is_valid_correlation_id("valid_ID-12345") is True  # underscores/hyphen are ok


def test_correlationidmiddleware_generate_correlation_id_format(middleware_instance):
    """generate_correlation_id should produce a string with the expected pattern and be valid per validator."""
    cid = middleware_instance.generate_correlation_id()
    assert isinstance(cid, str)
    assert re.match(r"^\d+-py-\d+$", cid) is not None
    assert middleware_instance.is_valid_correlation_id(cid) is True


def test_correlationidmiddleware_before_request_sets_context_from_header(monkeypatch, middleware_instance):
    """before_request should set g.correlation_id and g.request_start_time using the inbound header."""
    headers = {CORRELATION_ID_HEADER: "valid-ABCDE-12345"}
    g, _req = install_fake_flask(monkeypatch, headers=headers)

    # Freeze time
    monkeypatch.setattr("src.correlation_middleware.time", SimpleNamespace(time=lambda: 1234.5))

    middleware_instance.before_request()
    assert getattr(g, "correlation_id", None) == "valid-ABCDE-12345"
    assert getattr(g, "request_start_time", None) == 1234.5


def test_correlationidmiddleware_before_request_generates_when_invalid_header(monkeypatch, middleware_instance):
    """before_request should generate a correlation ID if inbound header is invalid."""
    headers = {CORRELATION_ID_HEADER: "short"}
    g, _req = install_fake_flask(monkeypatch, headers=headers)

    monkeypatch.setattr("src.correlation_middleware.time", SimpleNamespace(time=lambda: 999.0))
    monkeypatch.setattr(middleware_instance, "generate_correlation_id", lambda: "gen-AAAAAAAAAA")

    middleware_instance.before_request()
    assert getattr(g, "correlation_id", None) == "gen-AAAAAAAAAA"
    assert getattr(g, "request_start_time", None) == 999.0


def test_correlationidmiddleware_after_request_sets_header_and_stores_trace(monkeypatch, middleware_instance):
    """after_request should add the correlation header and call store_trace with expected data."""
    g, req = install_fake_flask(
        monkeypatch,
        headers={},
        method="POST",
        path="/api/test",
    )
    setattr(g, "correlation_id", "valid-ABCDE-12345")
    setattr(g, "request_start_time", 100.0)

    # Patch time to compute duration
    monkeypatch.setattr("src.correlation_middleware.time", SimpleNamespace(time=lambda: 100.1))

    mock_store = Mock()
    monkeypatch.setattr("src.correlation_middleware.store_trace", mock_store)

    class Response:
        def __init__(self):
            self.headers = {}
            self.status_code = 202

    resp = Response()
    out = middleware_instance.after_request(resp)

    assert out is resp
    assert resp.headers[CORRELATION_ID_HEADER] == "valid-ABCDE-12345"
    mock_store.assert_called_once()
    args, kwargs = mock_store.call_args
    cid_arg, trace_data = args
    assert cid_arg == "valid-ABCDE-12345"
    assert trace_data["service"] == "python-reviewer"
    assert trace_data["method"] == "POST"
    assert trace_data["path"] == "/api/test"
    assert isinstance(trace_data["timestamp"], str)
    assert trace_data["correlation_id"] == "valid-ABCDE-12345"
    assert trace_data["duration_ms"] == 100.0
    assert trace_data["status"] == 202


def test_correlationidmiddleware_after_request_no_correlation_id_noop(monkeypatch, middleware_instance):
    """after_request should not set header or call store_trace if g has no correlation_id."""
    g, req = install_fake_flask(monkeypatch)
    # Ensure no correlation_id attribute on g
    if hasattr(g, "correlation_id"):
        delattr(g, "correlation_id")

    mock_store = Mock()
    monkeypatch.setattr("src.correlation_middleware.store_trace", mock_store)

    class Response:
        def __init__(self):
            self.headers = {}
            self.status_code = 200

    resp = Response()
    out = middleware_instance.after_request(resp)

    assert out is resp
    assert CORRELATION_ID_HEADER not in resp.headers
    mock_store.assert_not_called()


def test_store_and_get_traces_roundtrip_and_copy_semantics():
    """store_trace should append traces and get_traces/get_all_traces should return copies."""
    cid = "trace-abcde-12345"
    data1 = {"timestamp": datetime.now().isoformat(), "foo": 1}
    data2 = {"timestamp": datetime.now().isoformat(), "foo": 2}

    store_trace(cid, data1)
    store_trace(cid, data2)

    traces = get_traces(cid)
    assert len(traces) == 2
    assert traces[0]["foo"] == 1
    assert traces[1]["foo"] == 2

    # Copy semantics: modifying returned list should not affect storage
    traces.append({"timestamp": datetime.now().isoformat(), "foo": 3})
    assert len(get_traces(cid)) == 2

    all_traces = get_all_traces()
    assert cid in all_traces
    all_traces[cid].clear()
    # Internal storage should remain intact
    assert len(get_traces(cid)) == 2


def test_cleanup_old_traces_removes_entries_older_than_one_hour():
    """cleanup_old_traces should delete correlation IDs whose oldest trace is > 1 hour old."""
    now = datetime.now()
    old_ts = (now - timedelta(hours=2)).isoformat()
    new_ts = (now - timedelta(minutes=30)).isoformat()

    with trace_lock:
        trace_storage["old-cid-12345"] = [{"timestamp": old_ts, "foo": "old"}]
        trace_storage["new-cid-12345"] = [{"timestamp": new_ts, "foo": "new"}]

    cleanup_old_traces()

    with trace_lock:
        assert "old-cid-12345" not in trace_storage
        assert "new-cid-12345" in trace_storage


def test_cleanup_old_traces_raises_on_invalid_timestamp():
    """cleanup_old_traces should propagate errors if a trace has an invalid timestamp format."""
    with trace_lock:
        trace_storage["bad-cid-12345"] = [{"timestamp": "not-a-time"}]

    with pytest.raises(ValueError):
        cleanup_old_traces()