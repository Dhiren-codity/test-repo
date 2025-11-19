import pytest
from unittest.mock import Mock, patch
from types import ModuleType, SimpleNamespace
import sys
import re

from src.correlation_middleware import (
    CorrelationIDMiddleware,
    CORRELATION_ID_HEADER,
    store_trace,
    get_traces,
    get_all_traces,
    cleanup_old_traces,
    trace_storage,
)


@pytest.fixture
def middleware_instance():
    """Create a CorrelationIDMiddleware instance without binding to an app."""
    return CorrelationIDMiddleware()


@pytest.fixture
def fake_flask(monkeypatch):
    """
    Provide a utility to inject a fake 'flask' module into sys.modules
    with customizable request and g objects.
    """
    def _install(request_headers=None, method='GET', path='/test', g_obj=None):
        fake_module = ModuleType("flask")
        req_obj = SimpleNamespace(
            headers=request_headers or {},
            method=method,
            path=path,
        )
        if g_obj is None:
            g_obj = SimpleNamespace()
        fake_module.request = req_obj
        fake_module.g = g_obj
        monkeypatch.setitem(sys.modules, "flask", fake_module)
        return fake_module
    return _install


def test_correlationidmiddleware_init_app_registration_and_attr():
    """Test that init_app registers hooks and sets correlation_start_time."""
    class FakeApp:
        def __init__(self):
            self.before = []
            self.after = []
            self.correlation_start_time = "existing"

        def before_request(self, func):
            self.before.append(func)

        def after_request(self, func):
            self.after.append(func)

    app = FakeApp()
    mw = CorrelationIDMiddleware()
    mw.init_app(app)

    assert len(app.before) == 1
    assert len(app.after) == 1
    assert app.before[0] is mw.before_request
    assert app.after[0] is mw.after_request
    assert app.correlation_start_time is None


def test_correlationidmiddleware_init_calls_init_app_when_app_passed():
    """Test that __init__ with app parameter calls init_app."""
    class FakeApp:
        def __init__(self):
            self.before = []
            self.after = []
            self.correlation_start_time = None

        def before_request(self, func):
            self.before.append(func)

        def after_request(self, func):
            self.after.append(func)

    app = FakeApp()
    _ = CorrelationIDMiddleware(app=app)
    assert len(app.before) == 1
    assert len(app.after) == 1


def test_correlationidmiddleware_before_request_sets_g_and_start_time(middleware_instance, fake_flask, monkeypatch):
    """Test before_request sets g.correlation_id and g.request_start_time."""
    fake_flask_module = fake_flask(request_headers={})
    monkeypatch.setattr("src.correlation_middleware.time.time", lambda: 1000.0)
    with patch.object(middleware_instance, "generate_correlation_id", return_value="gen-id-123"):
        middleware_instance.before_request()
    assert fake_flask_module.g.correlation_id == "gen-id-123"
    assert fake_flask_module.g.request_start_time == 1000.0


def test_correlationidmiddleware_before_request_uses_existing_valid_header(middleware_instance, fake_flask, monkeypatch):
    """Test before_request uses an existing valid X-Correlation-ID header."""
    header_value = "ValidHeader01"
    fake_flask_module = fake_flask(request_headers={CORRELATION_ID_HEADER: header_value})
    monkeypatch.setattr("src.correlation_middleware.time.time", lambda: 42.0)

    middleware_instance.before_request()
    assert fake_flask_module.g.correlation_id == header_value
    assert fake_flask_module.g.request_start_time == 42.0


def test_correlationidmiddleware_extract_or_generate_reuses_valid_header(middleware_instance):
    """Test extract_or_generate_correlation_id returns header if valid."""
    req = SimpleNamespace(headers={CORRELATION_ID_HEADER: "valid_id-12345"})
    with patch.object(middleware_instance, "is_valid_correlation_id", return_value=True):
        with patch.object(middleware_instance, "generate_correlation_id", return_value="should-not-be-used") as gen_mock:
            cid = middleware_instance.extract_or_generate_correlation_id(req)
            assert cid == "valid_id-12345"
            gen_mock.assert_not_called()


def test_correlationidmiddleware_extract_or_generate_generates_when_invalid(middleware_instance):
    """Test extract_or_generate_correlation_id generates when header invalid or missing."""
    req = SimpleNamespace(headers={CORRELATION_ID_HEADER: "invalid id!"})
    with patch.object(middleware_instance, "is_valid_correlation_id", return_value=False):
        with patch.object(middleware_instance, "generate_correlation_id", return_value="new-generated-id") as gen_mock:
            cid = middleware_instance.extract_or_generate_correlation_id(req)
            assert cid == "new-generated-id"
            gen_mock.assert_called_once()


def test_correlationidmiddleware_generate_correlation_id_format(monkeypatch):
    """Test generate_correlation_id produces deterministic string based on time."""
    mw = CorrelationIDMiddleware()
    T = 1700000000.123456
    monkeypatch.setattr("src.correlation_middleware.time.time", lambda: T)
    cid = mw.generate_correlation_id()
    # Expected format "<int_seconds>-py-<last_5_digits_of_microseconds>"
    sec = int(T)
    micro_mod = int(T * 1_000_000) % 100_000
    assert re.fullmatch(r"\d+-py-\d+", cid)
    assert cid.startswith(f"{sec}-py-")
    assert cid.split("-py-")[1] == str(micro_mod)


def test_correlationidmiddleware_is_valid_correlation_id_cases(middleware_instance):
    """Test is_valid_correlation_id for various edge cases and valid samples."""
    # Non-string
    assert middleware_instance.is_valid_correlation_id(123) is False
    # Too short
    assert middleware_instance.is_valid_correlation_id("a" * 9) is False
    # Too long
    assert middleware_instance.is_valid_correlation_id("a" * 101) is False
    # Invalid chars (space)
    assert middleware_instance.is_valid_correlation_id("invalid id") is False
    # Exactly min length valid
    assert middleware_instance.is_valid_correlation_id("a" * 10) is True
    # Exactly max length valid
    assert middleware_instance.is_valid_correlation_id("a" * 100) is True
    # Valid with allowed chars
    assert middleware_instance.is_valid_correlation_id("abc_123-XYZ_token") is True


def test_correlationidmiddleware_after_request_sets_header_and_stores_trace(middleware_instance, fake_flask, monkeypatch):
    """Test after_request sets header and calls store_trace with expected trace data."""
    # Set up g and request
    g_obj = SimpleNamespace(correlation_id="valid_id-12345", request_start_time=100.0)
    fake_flask_module = fake_flask(
        request_headers={},
        method="GET",
        path="/foo",
        g_obj=g_obj,
    )

    # Mock timing to produce deterministic duration
    monkeypatch.setattr("src.correlation_middleware.time.time", lambda: 100.25)

    # Mock store_trace to capture input
    with patch("src.correlation_middleware.store_trace") as mock_store_trace:
        response = SimpleNamespace(headers={}, status_code=201)
        out = middleware_instance.after_request(response)

        assert out is response
        assert response.headers[CORRELATION_ID_HEADER] == "valid_id-12345"

        mock_store_trace.assert_called_once()
        args, kwargs = mock_store_trace.call_args
        assert args[0] == "valid_id-12345"
        trace = args[1]
        assert trace["service"] == "python-reviewer"
        assert trace["method"] == "GET"
        assert trace["path"] == "/foo"
        assert trace["correlation_id"] == "valid_id-12345"
        assert trace["status"] == 201
        assert isinstance(trace["timestamp"], str)
        assert trace["duration_ms"] == round((100.25 - 100.0) * 1000, 2)


def test_correlationidmiddleware_after_request_without_correlation_id(middleware_instance, fake_flask, monkeypatch):
    """Test after_request when correlation_id is missing: no header set, no trace stored."""
    g_obj = SimpleNamespace()  # No correlation_id
    _ = fake_flask(method="POST", path="/no-cid", g_obj=g_obj)

    with patch("src.correlation_middleware.store_trace") as mock_store_trace:
        response = SimpleNamespace(headers={}, status_code=200)
        out = middleware_instance.after_request(response)
        assert out is response
        assert CORRELATION_ID_HEADER not in response.headers
        mock_store_trace.assert_not_called()


def test_correlationidmiddleware_after_request_uses_default_start_time_when_missing(middleware_instance, fake_flask, monkeypatch):
    """Test after_request falls back to current time when request_start_time missing."""
    g_obj = SimpleNamespace(correlation_id="valid_id-56789")  # No request_start_time
    _ = fake_flask(method="PUT", path="/fallback", g_obj=g_obj)

    # When start time missing, it uses time.time() twice, but in code it calls time.time only once
    # for duration as start_time is missing and defaulted to time.time() captured at that moment.
    # To make duration deterministic, emulate two successive calls in expression:
    # start_time = time.time() -> 200.0
    # duration = time.time() - start_time -> 200.2 - 200.0 = 0.2
    times = iter([200.0, 200.2])
    monkeypatch.setattr("src.correlation_middleware.time.time", lambda: next(times))

    with patch("src.correlation_middleware.store_trace") as mock_store_trace:
        response = SimpleNamespace(headers={}, status_code=204)
        _ = middleware_instance.after_request(response)
        mock_store_trace.assert_called_once()
        trace = mock_store_trace.call_args[0][1]
        assert trace["duration_ms"] == round((200.2 - 200.0) * 1000, 2)


def test_store_trace_and_get_traces_copy_behavior(monkeypatch):
    """Test store_trace saves traces and get_traces/get_all_traces return copies."""
    # Clear global storage
    trace_storage.clear()

    # Use current valid timestamp to avoid cleanup
    trace = {
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "service": "s",
        "method": "M",
        "path": "/p",
        "correlation_id": "cid1",
        "duration_ms": 1.23,
        "status": 200,
    }
    store_trace("cid1", trace)

    # get_traces returns a copy
    traces_copy = get_traces("cid1")
    assert traces_copy == [trace]
    traces_copy.append({"extra": "mutate"})
    assert get_traces("cid1") == [trace]  # original not affected

    # get_all_traces returns deep-ish copy of lists
    all_copy = get_all_traces()
    assert "cid1" in all_copy
    assert all_copy["cid1"] == [trace]
    all_copy["cid1"].append({"extra": "mutate"})
    assert get_all_traces()["cid1"] == [trace]


def test_cleanup_old_traces_removes_old_and_keeps_recent():
    """Test cleanup_old_traces removes entries older than 1 hour and keeps recent ones."""
    trace_storage.clear()
    from datetime import datetime, timedelta

    now = datetime.now()
    old_ts = (now - timedelta(hours=2)).isoformat()
    new_ts = (now - timedelta(minutes=10)).isoformat()

    trace_storage["oldcid"] = [{"timestamp": old_ts, "dummy": 1}]
    trace_storage["newcid"] = [{"timestamp": new_ts, "dummy": 2}]

    cleanup_old_traces()

    assert "oldcid" not in trace_storage
    assert "newcid" in trace_storage
    assert trace_storage["newcid"][0]["timestamp"] == new_ts