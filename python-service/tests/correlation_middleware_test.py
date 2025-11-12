import re
import pytest
from unittest.mock import Mock, patch
from flask import Flask, Response, g

from src.correlation_middleware import (
    CorrelationIDMiddleware,
    CORRELATION_ID_HEADER,
    get_traces,
    get_all_traces,
    trace_storage,
    store_trace,
    cleanup_old_traces,
)


@pytest.fixture(autouse=True)
def clear_trace_storage():
    """Ensure trace storage is clean before and after each test."""
    trace_storage.clear()
    yield
    trace_storage.clear()


@pytest.fixture()
def app():
    """Create a Flask app with the CorrelationIDMiddleware registered and sample routes."""
    app = Flask(__name__)
    app.config.update(TESTING=True)
    middleware = CorrelationIDMiddleware()
    middleware.init_app(app)

    @app.get("/echo")
    def echo():
        """Return the correlation ID set in before_request."""
        return getattr(g, "correlation_id", "none")

    @app.get("/preset-header")
    def preset_header():
        """Return a response with a preset header to test overwrite behavior."""
        resp = Response("ok", status=200)
        resp.headers[CORRELATION_ID_HEADER] = "pre-set-header"
        return resp

    @app.get("/nocid")
    def nocid():
        """Remove correlation_id from g to simulate missing ID in after_request."""
        if hasattr(g, "correlation_id"):
            delattr(g, "correlation_id")
        return "no"

    @app.get("/check-start")
    def check_start():
        """Check that request start time is set in before_request."""
        return "1" if hasattr(g, "request_start_time") else "0"

    return app


@pytest.fixture()
def client(app):
    """Return a test client for the Flask app."""
    return app.test_client()


def test_CorrelationIDMiddleware_init_app_registers_hooks_each_time():
    """init_app should register before_request and after_request hooks each time and set app attribute."""
    app = Flask(__name__)
    app.config.update(TESTING=True)
    middleware = CorrelationIDMiddleware()

    before_count_0 = len(app.before_request_funcs.get(None, []))
    after_count_0 = len(app.after_request_funcs.get(None, []))

    middleware.init_app(app)
    before_count_1 = len(app.before_request_funcs.get(None, []))
    after_count_1 = len(app.after_request_funcs.get(None, []))

    assert before_count_1 == before_count_0 + 1
    assert after_count_1 == after_count_0 + 1
    assert hasattr(app, "correlation_start_time")
    assert app.correlation_start_time is None

    # Calling a second time should register again with this implementation
    middleware.init_app(app)
    before_count_2 = len(app.before_request_funcs.get(None, []))
    after_count_2 = len(app.after_request_funcs.get(None, []))
    assert before_count_2 == before_count_1 + 1
    assert after_count_2 == after_count_1 + 1


def test_CorrelationIDMiddleware_before_after_request_sets_header_and_stores_trace(monkeypatch, app, client):
    """before_request must set g.correlation_id and request_start_time; after_request should set header and store a trace with expected fields."""
    # Fix generated correlation ID to a known value
    monkeypatch.setattr(
        CorrelationIDMiddleware,
        "generate_correlation_id",
        staticmethod(lambda: "fixed-1234567890"),
    )

    # Control time for duration calculation: start=1000.0, end=1000.123456 -> 123.46 ms
    times = iter([1000.0, 1000.123456])
    monkeypatch.setattr("src.correlation_middleware.time", "time", lambda: next(times))

    resp = client.get("/echo")
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == "fixed-1234567890"
    assert resp.headers[CORRELATION_ID_HEADER] == "fixed-1234567890"

    traces = get_traces("fixed-1234567890")
    assert len(traces) == 1
    trace = traces[0]
    assert trace["service"] == "python-reviewer"
    assert trace["method"] == "GET"
    assert trace["path"] == "/echo"
    assert trace["correlation_id"] == "fixed-1234567890"
    assert trace["status"] == 200
    assert isinstance(trace["timestamp"], str) and re.match(r"^\d{4}-\d{2}-\d{2}T", trace["timestamp"])
    assert trace["duration_ms"] == 123.46


def test_CorrelationIDMiddleware_extract_or_generate_uses_existing_valid_id():
    """extract_or_generate_correlation_id should return incoming valid header value."""
    middleware = CorrelationIDMiddleware()
    dummy_request = type("R", (), {"headers": {CORRELATION_ID_HEADER: "valid_1234567890"}})()
    result = middleware.extract_or_generate_correlation_id(dummy_request)
    assert result == "valid_1234567890"


def test_CorrelationIDMiddleware_extract_or_generate_generates_for_missing_or_invalid(monkeypatch):
    """extract_or_generate_correlation_id should generate a new ID when input is missing or invalid."""
    middleware = CorrelationIDMiddleware()
    monkeypatch.setattr(
        CorrelationIDMiddleware,
        "generate_correlation_id",
        staticmethod(lambda: "gen-1234567890"),
    )

    # Missing header
    dummy_request_missing = type("R", (), {"headers": {}})()
    assert middleware.extract_or_generate_correlation_id(dummy_request_missing) == "gen-1234567890"

    # Invalid header (too short)
    dummy_request_invalid = type("R", (), {"headers": {CORRELATION_ID_HEADER: "short"}})()
    assert middleware.extract_or_generate_correlation_id(dummy_request_invalid) == "gen-1234567890"

    # Invalid header (disallowed character '.')
    dummy_request_invalid2 = type("R", (), {"headers": {CORRELATION_ID_HEADER: "invalid.id"}})()
    assert middleware.extract_or_generate_correlation_id(dummy_request_invalid2) == "gen-1234567890"


def test_CorrelationIDMiddleware_is_valid_correlation_id_boundaries_and_chars():
    """is_valid_correlation_id should enforce length and allowed characters."""
    assert CorrelationIDMiddleware.is_valid_correlation_id("a" * 10)
    assert CorrelationIDMiddleware.is_valid_correlation_id("a" * 100)
    assert CorrelationIDMiddleware.is_valid_correlation_id("abcDEF_123-456")

    # Invalid: too short
    assert not CorrelationIDMiddleware.is_valid_correlation_id("a" * 9)
    # Invalid: too long
    assert not CorrelationIDMiddleware.is_valid_correlation_id("a" * 101)
    # Invalid: contains dot and space
    assert not CorrelationIDMiddleware.is_valid_correlation_id("abc.def")
    assert not CorrelationIDMiddleware.is_valid_correlation_id("abc def")
    # Invalid: non-string types
    assert not CorrelationIDMiddleware.is_valid_correlation_id(None)  # type: ignore[arg-type]
    assert not CorrelationIDMiddleware.is_valid_correlation_id(123)   # type: ignore[arg-type]


def test_CorrelationIDMiddleware_generate_correlation_id_format(monkeypatch):
    """generate_correlation_id should use current time to produce expected formatted string."""
    # Set a fixed time
    monkeypatch.setattr("src.correlation_middleware.time", "time", lambda: 1700000000.123456)
    # Both time() calls will return the same fixed value
    result = CorrelationIDMiddleware.generate_correlation_id()
    assert result == "1700000000-py-23456"


def test_CorrelationIDMiddleware_after_request_overwrites_existing_header(monkeypatch, app, client):
    """after_request must overwrite any pre-existing correlation header with the current request ID."""
    monkeypatch.setattr(
        CorrelationIDMiddleware,
        "generate_correlation_id",
        staticmethod(lambda: "fixed-abcdef1234"),
    )
    resp = client.get("/preset-header")
    assert resp.status_code == 200
    assert resp.headers[CORRELATION_ID_HEADER] == "fixed-abcdef1234"


def test_CorrelationIDMiddleware_after_request_without_correlation_id_sets_no_header_and_does_not_store(app, client):
    """If g.correlation_id is missing, after_request should not set header nor store traces."""
    with patch("src.correlation_middleware.store_trace") as mock_store:
        resp = client.get("/nocid")
        assert resp.status_code == 200
        assert CORRELATION_ID_HEADER not in resp.headers
        mock_store.assert_not_called()


def test_cleanup_old_traces_removes_entries_older_than_one_hour():
    """cleanup_old_traces should remove stored traces whose oldest entry is older than one hour."""
    # Add an old trace (way older than 1 hour)
    trace_storage["old-id"] = [{"timestamp": "2000-01-01T00:00:00"}]
    # Add a new trace with current timestamp
    from datetime import datetime
    trace_storage["new-id"] = [{"timestamp": datetime.now().isoformat()}]

    cleanup_old_traces()

    assert "old-id" not in trace_storage
    assert "new-id" in trace_storage


def test_get_traces_and_get_all_traces_return_copies():
    """get_traces and get_all_traces must return copies so list mutations don't affect storage."""
    trace_storage["cid"] = [{"timestamp": "2000-01-01T00:00:00"}]
    lst = get_traces("cid")
    assert lst == trace_storage["cid"]
    lst.append({"timestamp": "extra"})
    assert len(trace_storage["cid"]) == 1  # original not modified

    all_traces = get_all_traces()
    assert "cid" in all_traces
    all_traces["cid"].append({"timestamp": "another"})
    assert len(trace_storage["cid"]) == 1  # original still not modified


def test_cleanup_old_traces_raises_with_invalid_timestamp():
    """cleanup_old_traces should raise ValueError if a stored trace has an invalid timestamp format."""
    trace_storage["bad"] = [{"timestamp": "not-a-date"}]
    with pytest.raises(ValueError):
        cleanup_old_traces()


def test_CorrelationIDMiddleware_before_request_sets_start_time_flag(client):
    """before_request should set request_start_time on g before view executes."""
    resp = client.get("/check-start")
    assert resp.get_data(as_text=True) == "1"


def test_CorrelationIDMiddleware_uses_incoming_valid_header_in_request_response(app, client):
    """Middleware should use incoming valid header and echo it back in response header."""
    incoming = "valid_ExistingID-12345"
    resp = client.get("/echo", headers={CORRELATION_ID_HEADER: incoming})
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == incoming
    assert resp.headers[CORRELATION_ID_HEADER] == incoming


def test_store_trace_appends_and_cleanup_called(monkeypatch):
    """store_trace should append trace and invoke cleanup_old_traces."""
    calls = {"cleanup": 0}

    def fake_cleanup():
        calls["cleanup"] += 1

    monkeypatch.setattr("src.correlation_middleware.cleanup_old_traces", fake_cleanup)

    cid = "valid_trace_12345"
    data = {"timestamp": "2000-01-01T00:00:00", "status": 200}
    store_trace(cid, data)
    assert cid in trace_storage
    assert trace_storage[cid][0] == data
    assert calls["cleanup"] == 1