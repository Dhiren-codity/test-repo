import pytest
from unittest.mock import MagicMock, patch
from flask import Flask, jsonify, g

from src.correlation_middleware import (
    CorrelationIDMiddleware,
    CORRELATION_ID_HEADER,
    get_traces,
    get_all_traces,
    store_trace,
    cleanup_old_traces,
    trace_storage,
)


@pytest.fixture(autouse=True)
def clear_traces():
    """Ensure trace storage is clean before and after each test"""
    trace_storage.clear()
    yield
    trace_storage.clear()


@pytest.fixture
def flask_app():
    """Create a Flask app with CorrelationIDMiddleware installed and test routes."""
    app = Flask(__name__)
    middleware = CorrelationIDMiddleware(app)

    @app.route("/ok")
    def ok():
        return jsonify(cid=getattr(g, "correlation_id", None))

    @app.route("/nocid")
    def nocid():
        # Simulate a scenario where correlation_id is missing before after_request runs
        if hasattr(g, "correlation_id"):
            delattr(g, "correlation_id")
        return jsonify(msg="no cid")

    @app.route("/no-start")
    def nostart():
        # Simulate missing start time to exercise fallback in after_request
        if hasattr(g, "request_start_time"):
            delattr(g, "request_start_time")
        return jsonify(msg="no start")

    return app


@pytest.fixture
def client(flask_app):
    """Return test client for the Flask app."""
    return flask_app.test_client()


def test_correlationidmiddleware___init___with_app_registers_handlers():
    """Ensure __init__ with app registers handlers and sets app attribute."""
    app = Flask(__name__)
    mw = CorrelationIDMiddleware(app)
    assert mw.app is app
    # Flask stores handlers under blueprint None for the app
    assert any(h.__name__ == mw.before_request.__name__ for h in app.before_request_funcs[None])
    assert any(h.__name__ == mw.after_request.__name__ for h in app.after_request_funcs[None])
    # init_app sets correlation_start_time attribute on app
    assert hasattr(app, "correlation_start_time")
    assert app.correlation_start_time is None


def test_correlationidmiddleware_init_app_registers_handlers():
    """Ensure init_app registers before_request and after_request handlers."""
    app = Flask(__name__)
    mw = CorrelationIDMiddleware()
    mw.init_app(app)
    assert any(h.__name__ == mw.before_request.__name__ for h in app.before_request_funcs[None])
    assert any(h.__name__ == mw.after_request.__name__ for h in app.after_request_funcs[None])
    assert hasattr(app, "correlation_start_time")
    assert app.correlation_start_time is None


def test_correlationidmiddleware_before_request_sets_correlation_id_and_time(client):
    """before_request should set g.correlation_id from valid header and set start time."""
    incoming = "validID-12345"
    resp = client.get("/ok", headers={CORRELATION_ID_HEADER: incoming})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["cid"] == incoming
    assert resp.headers.get(CORRELATION_ID_HEADER) == incoming


def test_correlationidmiddleware_before_request_generates_when_header_missing(monkeypatch, client):
    """before_request generates a new correlation id when header is missing."""
    monkeypatch.setattr(
        CorrelationIDMiddleware,
        "generate_correlation_id",
        staticmethod(lambda: "gen-fixed-12345"),
    )
    resp = client.get("/ok")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["cid"] == "gen-fixed-12345"
    assert resp.headers.get(CORRELATION_ID_HEADER) == "gen-fixed-12345"


def test_correlationidmiddleware_extract_or_generate_correlation_id_valid_and_invalid():
    """extract_or_generate_correlation_id returns incoming when valid, otherwise generates."""
    mw = CorrelationIDMiddleware()
    valid_request = MagicMock()
    valid_request.headers = {CORRELATION_ID_HEADER: "Valid_ID-12345"}
    assert mw.extract_or_generate_correlation_id(valid_request) == "Valid_ID-12345"

    invalid_request = MagicMock()
    invalid_request.headers = {CORRELATION_ID_HEADER: "bad id"}  # invalid due to space and length
    with patch.object(
        CorrelationIDMiddleware,
        "generate_correlation_id",
        return_value="generated-99999",
    ):
        assert mw.extract_or_generate_correlation_id(invalid_request) == "generated-99999"

    missing_request = MagicMock()
    missing_request.headers = {}
    with patch.object(
        CorrelationIDMiddleware,
        "generate_correlation_id",
        return_value="generated-88888",
    ):
        assert mw.extract_or_generate_correlation_id(missing_request) == "generated-88888"


def test_correlationidmiddleware_generate_correlation_id_deterministic_with_mock(monkeypatch):
    """generate_correlation_id should use time-based components; verify with patched time."""
    mw = CorrelationIDMiddleware()
    monkeypatch.setattr("src.correlation_middleware.time.time", lambda: 1700000000.0)
    cid = mw.generate_correlation_id()
    assert cid == "1700000000-py-0"


def test_correlationidmiddleware_is_valid_correlation_id_rules():
    """is_valid_correlation_id should enforce type, length, and safe character set."""
    mw = CorrelationIDMiddleware()
    assert mw.is_valid_correlation_id("ABCdef_123-XYZ")
    assert mw.is_valid_correlation_id("a" * 10)
    assert mw.is_valid_correlation_id("a" * 100)
    assert not mw.is_valid_correlation_id(123)  # non-string
    assert not mw.is_valid_correlation_id("short")  # < 10
    assert not mw.is_valid_correlation_id("a" * 101)  # > 100
    assert not mw.is_valid_correlation_id("invalid space")
    assert not mw.is_valid_correlation_id("bad/chars!")  # '/' and '!' not allowed by regex


def test_correlationidmiddleware_after_request_sets_header_and_stores_trace(monkeypatch, client):
    """after_request appends correlation header and stores a trace with expected fields."""
    # Set predictable timing for duration calculation: before = 1000.0, after = 1000.1
    times = iter([1000.0, 1000.1])
    monkeypatch.setattr("src.correlation_middleware.time.time", lambda: next(times))

    incoming = "incoming-123456789"
    resp = client.get("/ok", headers={CORRELATION_ID_HEADER: incoming})
    assert resp.status_code == 200
    assert resp.headers.get(CORRELATION_ID_HEADER) == incoming

    traces = get_traces(incoming)
    assert len(traces) == 1
    t = traces[0]
    assert t["service"] == "python-reviewer"
    assert t["method"] == "GET"
    assert t["path"] == "/ok"
    assert t["correlation_id"] == incoming
    assert t["status"] == 200
    assert isinstance(t["duration_ms"], float)
    assert t["duration_ms"] == 100.0  # 0.1s -> 100 ms


def test_correlationidmiddleware_after_request_no_correlation_id_does_not_set_header_or_store(monkeypatch, flask_app):
    """If g.correlation_id is missing, header is not set and store_trace is not called."""
    with patch("src.correlation_middleware.store_trace") as mock_store:
        with flask_app.test_client() as client:
            resp = client.get("/nocid")
    assert CORRELATION_ID_HEADER not in resp.headers
    mock_store.assert_not_called()


def test_correlationidmiddleware_after_request_fallback_when_no_start_time(monkeypatch, client):
    """after_request should gracefully handle missing g.request_start_time using current time."""
    # Use constant time to ensure computed duration is zero when start time not present.
    monkeypatch.setattr("src.correlation_middleware.time.time", lambda: 2000.0)
    resp = client.get("/no-start", headers={CORRELATION_ID_HEADER: "fallback-123456"})
    assert resp.status_code == 200
    assert resp.headers.get(CORRELATION_ID_HEADER) == "fallback-123456"
    traces = get_traces("fallback-123456")
    assert len(traces) == 1
    assert traces[0]["duration_ms"] == 0.0


def test_store_and_get_traces_return_copies(monkeypatch):
    """get_traces and get_all_traces should return copies to prevent external mutation."""
    # Prevent cleanup from deleting entries mid-test
    monkeypatch.setattr("src.correlation_middleware.cleanup_old_traces", lambda: None)
    cid = "cid-1234567890"
    data1 = {"timestamp": "2024-01-01T12:00:00", "x": 1}
    data2 = {"timestamp": "2024-01-01T12:01:00", "x": 2}
    store_trace(cid, data1)
    store_trace(cid, data2)

    traces_copy = get_traces(cid)
    assert traces_copy == trace_storage[cid]
    traces_copy[0]["x"] = 99
    # Original should not reflect mutation
    assert trace_storage[cid][0]["x"] == 1

    all_copy = get_all_traces()
    # Modify returned list and ensure original not changed
    all_copy[cid].append({"timestamp": "2024-01-01T12:02:00"})
    assert len(all_copy[cid]) == len(trace_storage[cid]) + 1
    assert len(trace_storage[cid]) == 2


def test_cleanup_old_traces_removes_groups_older_than_one_hour(monkeypatch):
    """cleanup_old_traces should delete groups whose first trace is older than 1 hour."""
    from datetime import datetime as real_datetime, timedelta

    fixed_now = real_datetime(2024, 1, 1, 12, 0, 0)

    class DummyDateTime:
        @classmethod
        def now(cls):
            return fixed_now

        @classmethod
        def fromisoformat(cls, s: str):
            return real_datetime.fromisoformat(s)

    monkeypatch.setattr("src.correlation_middleware.datetime", DummyDateTime)

    # Setup traces: 'old' -> first older than 1h, 'mixed' -> first older than 1h but contains newer,
    # 'recent' -> first newer than 1h even if contains older later (should be kept).
    trace_storage.clear()
    trace_storage["old"] = [
        {"timestamp": (fixed_now - timedelta(hours=2)).isoformat()},
        {"timestamp": (fixed_now - timedelta(minutes=30)).isoformat()},
    ]
    trace_storage["mixed"] = [
        {"timestamp": (fixed_now - timedelta(hours=2)).isoformat()},
        {"timestamp": (fixed_now - timedelta(minutes=10)).isoformat()},
    ]
    trace_storage["recent"] = [
        {"timestamp": (fixed_now - timedelta(minutes=30)).isoformat()},
        {"timestamp": (fixed_now - timedelta(hours=2)).isoformat()},
    ]

    cleanup_old_traces()

    assert "old" not in trace_storage
    assert "mixed" not in trace_storage
    assert "recent" in trace_storage
    assert len(trace_storage["recent"]) == 2