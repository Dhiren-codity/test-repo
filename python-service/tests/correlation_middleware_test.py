import pytest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from flask import Flask, g, Response

from src.correlation_middleware import (
    CorrelationIDMiddleware,
    CORRELATION_ID_HEADER,
    store_trace,
    cleanup_old_traces,
    get_traces,
    get_all_traces,
    trace_storage,
)


@pytest.fixture(autouse=True)
def reset_trace_storage():
    """Ensure trace storage is clean before each test."""
    trace_storage.clear()
    yield
    trace_storage.clear()


@pytest.fixture
def middleware_instance():
    """Create a CorrelationIDMiddleware instance for testing."""
    return CorrelationIDMiddleware()


@pytest.fixture
def flask_app(middleware_instance):
    """Create a minimal Flask app with the middleware initialized."""
    app = Flask(__name__)

    @app.route("/ping", methods=["GET", "POST"])
    def ping():
        return "pong", 200

    middleware_instance.init_app(app)
    return app


@pytest.fixture
def client(flask_app):
    """Provide a Flask test client."""
    return flask_app.test_client()


def test_correlationidmiddleware_init_without_app():
    """CorrelationIDMiddleware can be initialized without an app and not raise."""
    mw = CorrelationIDMiddleware()
    assert mw.app is None


def test_correlationidmiddleware_init_with_app_registers_hooks():
    """init_app is called during __init__ when app is provided and registers hooks."""
    mock_app = SimpleNamespace()
    mock_app.before_request = Mock()
    mock_app.after_request = Mock()

    mw = CorrelationIDMiddleware(mock_app)

    mock_app.before_request.assert_called_once_with(mw.before_request)
    mock_app.after_request.assert_called_once_with(mw.after_request)
    assert hasattr(mock_app, "correlation_start_time")
    assert mock_app.correlation_start_time is None
    # also ensure mw.app is set
    assert mw.app is mock_app


def test_correlationidmiddleware_init_app_registers_hooks(middleware_instance):
    """init_app registers before_request and after_request handlers on the app."""
    mock_app = SimpleNamespace()
    mock_app.before_request = Mock()
    mock_app.after_request = Mock()

    middleware_instance.init_app(mock_app)

    mock_app.before_request.assert_called_once_with(middleware_instance.before_request)
    mock_app.after_request.assert_called_once_with(middleware_instance.after_request)
    assert hasattr(mock_app, "correlation_start_time")
    assert mock_app.correlation_start_time is None


def test_correlationidmiddleware_generate_correlation_id_with_mocked_time(middleware_instance, monkeypatch):
    """generate_correlation_id returns deterministic value when time is mocked."""
    # 1700000000.123456 -> int(time.time()) = 1700000000
    # int(time.time() * 1_000_000) % 100000 -> last 5 digits of 1700000000123456 = 23456
    monkeypatch.setattr("src.correlation_middleware.time.time", lambda: 1700000000.123456)
    cid = middleware_instance.generate_correlation_id()
    assert cid == "1700000000-py-23456"


def test_correlationidmiddleware_is_valid_correlation_id_cases(middleware_instance):
    """is_valid_correlation_id validates allowed characters and length bounds."""
    assert middleware_instance.is_valid_correlation_id("abc123-XYZ_45") is True  # valid, length >= 10
    assert middleware_instance.is_valid_correlation_id("a" * 10) is True  # min length
    assert middleware_instance.is_valid_correlation_id("short9aa") is False  # length 9
    assert middleware_instance.is_valid_correlation_id("a" * 101) is False  # too long
    assert middleware_instance.is_valid_correlation_id("bad space") is False  # invalid char
    assert middleware_instance.is_valid_correlation_id("unicode-Δelta") is False  # invalid char
    assert middleware_instance.is_valid_correlation_id(12345) is False  # not a string


def test_correlationidmiddleware_extract_or_generate_with_valid_header(middleware_instance):
    """When header provided and valid, extract_or_generate_correlation_id returns it."""
    headers = {CORRELATION_ID_HEADER: "valid-abc_12345"}
    fake_request = SimpleNamespace(headers=headers)
    result = middleware_instance.extract_or_generate_correlation_id(fake_request)
    assert result == "valid-abc_12345"


def test_correlationidmiddleware_extract_or_generate_with_invalid_header_generates(middleware_instance, monkeypatch):
    """When header provided but invalid, a new correlation ID is generated."""
    headers = {CORRELATION_ID_HEADER: "invalid header value"}  # space breaks regex
    fake_request = SimpleNamespace(headers=headers)
    monkeypatch.setattr("src.correlation_middleware.time.time", lambda: 1700000000.123456)
    result = middleware_instance.extract_or_generate_correlation_id(fake_request)
    assert result == "1700000000-py-23456"
    assert result != headers[CORRELATION_ID_HEADER]


def test_correlationidmiddleware_before_request_sets_g_and_time(flask_app):
    """before_request sets g.correlation_id and g.request_start_time."""
    mw = CorrelationIDMiddleware(flask_app)
    with flask_app.test_request_context("/ping"):
        # Simulate Flask calling before_request
        mw.before_request()
        assert hasattr(g, "correlation_id")
        assert isinstance(g.correlation_id, str)
        assert hasattr(g, "request_start_time")
        assert isinstance(g.request_start_time, float)


def test_correlationidmiddleware_after_request_sets_header_and_stores_trace(flask_app):
    """after_request attaches header and stores a trace with expected fields."""
    with flask_app.test_request_context("/ping", method="GET"):
        mw = CorrelationIDMiddleware(flask_app)
        mw.before_request()
        response = Response("ok", status=201)
        response = mw.after_request(response)

        assert CORRELATION_ID_HEADER in response.headers
        cid = response.headers[CORRELATION_ID_HEADER]
        assert isinstance(cid, str) and len(cid) >= 10

        traces = get_traces(cid)
        assert len(traces) == 1
        trace = traces[0]
        assert trace["service"] == "python-reviewer"
        assert trace["method"] == "GET"
        assert trace["path"] == "/ping"
        assert trace["status"] == 201
        assert trace["correlation_id"] == cid
        assert isinstance(trace["duration_ms"], float)
        assert "timestamp" in trace and isinstance(trace["timestamp"], str)
        assert "T" in trace["timestamp"]  # basic ISO-like format check


def test_correlationidmiddleware_after_request_without_g_correlation_id_does_not_set_header(flask_app, monkeypatch):
    """after_request returns response unchanged if correlation_id not present on g."""
    mw = CorrelationIDMiddleware(flask_app)
    with flask_app.test_request_context("/ping", method="GET"):
        response = Response("ok", status=200)
        with patch("src.correlation_middleware.store_trace") as mock_store:
            response2 = mw.after_request(response)
            assert response2 is response
            assert CORRELATION_ID_HEADER not in response.headers
            mock_store.assert_not_called()


def test_flask_integration_echoes_incoming_valid_header(client):
    """Middleware preserves and echoes a valid incoming X-Correlation-ID header."""
    incoming = "incoming-valid_12345"
    rv = client.get("/ping", headers={CORRELATION_ID_HEADER: incoming})
    assert rv.status_code == 200
    assert rv.headers[CORRELATION_ID_HEADER] == incoming

    traces = get_traces(incoming)
    assert len(traces) == 1
    assert traces[0]["correlation_id"] == incoming


def test_flask_integration_replaces_invalid_incoming_header(client):
    """Middleware replaces invalid incoming header and echoes a generated one."""
    invalid = "bad header"
    rv = client.get("/ping", headers={CORRELATION_ID_HEADER: invalid})
    assert rv.status_code == 200
    echoed = rv.headers.get(CORRELATION_ID_HEADER)
    assert echoed is not None
    assert echoed != invalid
    assert len(get_traces(echoed)) == 1


def test_correlationidmiddleware_after_request_calls_store_trace_payload(flask_app, monkeypatch):
    """after_request calls store_trace with expected payload including method/path/status."""
    captured = {}

    def fake_store_trace(correlation_id, trace_data):
        captured["cid"] = correlation_id
        captured["trace"] = trace_data

    monkeypatch.setattr("src.correlation_middleware.store_trace", fake_store_trace)
    mw = CorrelationIDMiddleware(flask_app)

    with flask_app.test_request_context("/ping?x=1", method="POST"):
        mw.before_request()
        response = Response("ok", status=202)
        response = mw.after_request(response)

        assert CORRELATION_ID_HEADER in response.headers
        assert "cid" in captured and "trace" in captured
        assert captured["trace"]["method"] == "POST"
        assert captured["trace"]["path"] == "/ping"  # no query string
        assert captured["trace"]["status"] == 202
        assert captured["trace"]["correlation_id"] == captured["cid"]
        assert captured["cid"] == response.headers[CORRELATION_ID_HEADER]


def test_store_trace_and_getters_return_copies():
    """store_trace stores traces, get_traces and get_all_traces return copies."""
    cid1 = "cid-one_12345"
    cid2 = "cid-two_12345"
    data1 = {"timestamp": "2021-01-01T00:00:00", "foo": "bar"}
    data2 = {"timestamp": "2021-01-01T00:00:01", "baz": "qux"}

    store_trace(cid1, data1)
    store_trace(cid1, data2)
    store_trace(cid2, data1)

    traces1 = get_traces(cid1)
    assert traces1 == [data1, data2]
    traces1.append({"timestamp": "2021-01-01T00:00:02", "extra": True})
    assert get_traces(cid1) == [data1, data2]  # original not mutated

    all_traces = get_all_traces()
    assert set(all_traces.keys()) == {cid1, cid2}
    all_traces[cid1].clear()
    # internal storage unaffected
    assert len(get_traces(cid1)) == 2


def test_cleanup_old_traces_removes_older_than_one_hour():
    """cleanup_old_traces removes entries whose oldest trace is over an hour old."""
    old_cid = "old_1234567890"
    recent_cid = "recent_1234567890"
    old_trace = {"timestamp": "2000-01-01T00:00:00"}
    recent_trace = {"timestamp": "2999-01-01T00:00:00"}

    trace_storage[old_cid] = [old_trace]
    trace_storage[recent_cid] = [recent_trace]
    cleanup_old_traces()

    assert old_cid not in trace_storage
    assert recent_cid in trace_storage


def test_store_trace_raises_when_missing_timestamp():
    """store_trace should propagate KeyError when trace_data lacks timestamp used in cleanup."""
    cid = "cid_error_123456"
    bad_trace = {"no_timestamp": True}

    with pytest.raises(KeyError):
        store_trace(cid, bad_trace)

    # The partial data may have been inserted before the failure
    assert cid in trace_storage
    # Clean up for safety
    trace_storage.clear()