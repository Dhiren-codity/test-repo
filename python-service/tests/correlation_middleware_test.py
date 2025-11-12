import pytest
from unittest.mock import patch, Mock
from datetime import datetime, timedelta
from flask import Flask, g, Response

from src.correlation_middleware import (
    CorrelationIDMiddleware,
    CORRELATION_ID_HEADER,
    trace_storage,
    get_traces,
    get_all_traces,
    store_trace,
    cleanup_old_traces,
)


@pytest.fixture(autouse=True)
def reset_trace_storage():
    """Ensure trace storage is clean before and after each test."""
    trace_storage.clear()
    yield
    trace_storage.clear()


@pytest.fixture
def app():
    """Create a Flask app with a simple route."""
    app = Flask(__name__)
    app.testing = True

    @app.route("/ping")
    def ping():
        return "pong"

    return app


@pytest.fixture
def client(app):
    """Create a Flask test client."""
    return app.test_client()


def test_CorrelationIDMiddleware___init___binds_app_and_registers_hooks(app):
    """Ensure that passing an app to __init__ registers hooks and sets app attributes."""
    CorrelationIDMiddleware(app)

    assert hasattr(app, "correlation_start_time")
    assert app.correlation_start_time is None

    hdr = {CORRELATION_ID_HEADER: "valid-ABCDE1234"}
    rv = app.test_client().get("/ping", headers=hdr)
    assert rv.status_code == 200
    assert rv.headers.get(CORRELATION_ID_HEADER) == "valid-ABCDE1234"

    traces = get_traces("valid-ABCDE1234")
    assert len(traces) == 1
    assert traces[0]["path"] == "/ping"
    assert traces[0]["method"] == "GET"
    assert traces[0]["status"] == 200


def test_CorrelationIDMiddleware___init___without_app_then_init_app(app):
    """Verify __init__ without app and later init_app works correctly."""
    mw = CorrelationIDMiddleware()
    mw.init_app(app)

    hdr = {CORRELATION_ID_HEADER: "valid-ABCDE1234"}
    rv = app.test_client().get("/ping", headers=hdr)
    assert rv.status_code == 200
    assert rv.headers.get(CORRELATION_ID_HEADER) == "valid-ABCDE1234"


def test_CorrelationIDMiddleware_init_app_registers_middleware(app):
    """Test that init_app registers before and after request handlers."""
    mw = CorrelationIDMiddleware()
    mw.init_app(app)

    hdr = {CORRELATION_ID_HEADER: "valid-ABCDE1234"}
    rv = app.test_client().get("/ping", headers=hdr)
    assert rv.headers.get(CORRELATION_ID_HEADER) == "valid-ABCDE1234"


def test_CorrelationIDMiddleware_before_request_sets_g_and_respects_valid_header(app):
    """before_request should set g fields and use the incoming valid correlation ID."""
    mw = CorrelationIDMiddleware(app)
    valid_id = "valid-ABCDE1234"
    with patch("time.time", return_value=100.0):
        with app.test_request_context("/ping", headers={CORRELATION_ID_HEADER: valid_id}):
            mw.before_request()
            assert g.correlation_id == valid_id
            assert g.request_start_time == 100.0


def test_CorrelationIDMiddleware_before_request_valid_header_does_not_call_generate(app):
    """before_request should not call generate_correlation_id when a valid header is present."""
    mw = CorrelationIDMiddleware(app)
    valid_id = "valid-ABCDE1234"
    with app.test_request_context("/ping", headers={CORRELATION_ID_HEADER: valid_id}):
        with patch.object(CorrelationIDMiddleware, "generate_correlation_id", side_effect=RuntimeError("should not be called")) as gen_mock:
            mw.before_request()
            assert g.correlation_id == valid_id
            gen_mock.assert_not_called()


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_header_variants(app):
    """extract_or_generate_correlation_id should use valid headers and generate for invalid/missing ones."""
    mw = CorrelationIDMiddleware(app)

    # Valid header
    with app.test_request_context("/path", headers={CORRELATION_ID_HEADER: "abcdefghij"}):
        cid = mw.extract_or_generate_correlation_id(g._get_current_object()._get_current_object()._get_current_object() if False else g)  # dummy; won't be used
    # Above line is irrelevant due to not using g; use request directly:
    with app.test_request_context("/path", headers={CORRELATION_ID_HEADER: "abcdefghij"}) as ctx:
        cid = mw.extract_or_generate_correlation_id(ctx.request)
        assert cid == "abcdefghij"

    # Invalid header (too short)
    with app.test_request_context("/path", headers={CORRELATION_ID_HEADER: "short"}):
        with patch.object(CorrelationIDMiddleware, "generate_correlation_id", return_value="gen-abc-12345") as gen_mock:
            cid = mw.extract_or_generate_correlation_id(ctx.request)
            assert cid == "gen-abc-12345"
            gen_mock.assert_called_once()

    # Invalid characters
    with app.test_request_context("/path", headers={CORRELATION_ID_HEADER: "abc$defghij"}):
        with patch.object(CorrelationIDMiddleware, "generate_correlation_id", return_value="gen-xyz-67890") as gen_mock:
            cid = mw.extract_or_generate_correlation_id(ctx.request)
            assert cid == "gen-xyz-67890"
            gen_mock.assert_called_once()


def test_CorrelationIDMiddleware_generate_correlation_id_deterministic_with_mock_time():
    """generate_correlation_id should use the time-based format when mocked."""
    with patch("time.time", return_value=1700000000.123456):
        cid = CorrelationIDMiddleware.generate_correlation_id()
    assert cid == "1700000000-py-23456"


def test_CorrelationIDMiddleware_is_valid_correlation_id_edge_cases():
    """Verify validator behavior across different edge cases."""
    assert CorrelationIDMiddleware.is_valid_correlation_id("abc-DEF_12345") is True
    assert CorrelationIDMiddleware.is_valid_correlation_id(12345) is False
    assert CorrelationIDMiddleware.is_valid_correlation_id("short") is False
    assert CorrelationIDMiddleware.is_valid_correlation_id("a" * 101) is False
    assert CorrelationIDMiddleware.is_valid_correlation_id("bad$chars_12345") is False
    assert CorrelationIDMiddleware.is_valid_correlation_id("abcdefghij") is True  # exactly 10 chars


def test_CorrelationIDMiddleware_after_request_sets_header_and_calls_store_trace(app):
    """after_request should set response header and store trace with correct details."""
    mw = CorrelationIDMiddleware(app)

    @app.route("/echo")
    def echo():
        return "ok"

    valid_id = "valid-ABCDE1234"
    with patch("src.correlation_middleware.store_trace") as mock_store, patch("time.time", side_effect=[100.0, 100.1234]):
        rv = app.test_client().get("/echo", headers={CORRELATION_ID_HEADER: valid_id})

    assert rv.headers.get(CORRELATION_ID_HEADER) == valid_id
    assert mock_store.call_count == 1
    called_cid, trace = mock_store.call_args.args
    assert called_cid == valid_id
    assert trace["service"] == "python-reviewer"
    assert trace["method"] == "GET"
    assert trace["path"] == "/echo"
    assert trace["status"] == 200
    # validate timestamp format
    datetime.fromisoformat(trace["timestamp"])
    # duration check: (100.1234 - 100.0) * 1000 = 123.4 ms
    assert trace["duration_ms"] == 123.4


def test_CorrelationIDMiddleware_after_request_without_start_time_uses_fallback(app):
    """after_request should compute duration using fallback when start time is missing."""
    mw = CorrelationIDMiddleware(app)
    resp = Response("x", status=201)
    with app.test_request_context("/x", method="PUT"):
        g.correlation_id = "valid-ABCDE1234"
        with patch("src.correlation_middleware.store_trace") as mock_store, patch("time.time", side_effect=[200.0, 200.002]):
            out = mw.after_request(resp)

    assert out.headers.get(CORRELATION_ID_HEADER) == "valid-ABCDE1234"
    called_cid, trace = mock_store.call_args.args
    assert called_cid == "valid-ABCDE1234"
    assert trace["status"] == 201
    assert trace["method"] == "PUT"
    assert trace["path"] == "/x"
    assert trace["duration_ms"] == round((200.002 - 200.0) * 1000, 2)


def test_CorrelationIDMiddleware_after_request_no_correlation_id_noop(app):
    """after_request should be a no-op when no correlation_id is present in g."""
    mw = CorrelationIDMiddleware(app)
    resp = Response("ok", status=200)
    with app.test_request_context("/noop", method="GET"):
        if hasattr(g, "correlation_id"):
            delattr(g, "correlation_id")
        with patch("src.correlation_middleware.store_trace") as mock_store:
            out_resp = mw.after_request(resp)
            mock_store.assert_not_called()

    assert out_resp.headers.get(CORRELATION_ID_HEADER) is None


def test_store_trace_and_get_traces_copy_semantics():
    """store_trace should append traces; getters should return copies."""
    cid = "trace-ABCDEF12"
    data1 = {"timestamp": datetime.now().isoformat(), "path": "/a"}
    data2 = {"timestamp": datetime.now().isoformat(), "path": "/b"}

    store_trace(cid, data1)
    store_trace(cid, data2)

    # get_traces returns a copy
    traces_copy = get_traces(cid)
    assert traces_copy == trace_storage[cid]
    traces_copy[0]["path"] = "/mutated"
    assert trace_storage[cid][0]["path"] == "/a"

    # get_all_traces returns deep-ish copy (lists copied)
    all_copy = get_all_traces()
    assert all_copy[cid] == trace_storage[cid]
    all_copy[cid][1]["path"] = "/mutated2"
    assert trace_storage[cid][1]["path"] == "/b"


def test_cleanup_old_traces_removes_expired_entries():
    """cleanup_old_traces should remove correlation IDs with oldest trace older than cutoff."""
    now = datetime.now()
    old_ts = (now - timedelta(hours=2)).isoformat()
    new_ts = (now - timedelta(minutes=10)).isoformat()

    trace_storage["old"] = [{"timestamp": old_ts}]
    trace_storage["new"] = [{"timestamp": new_ts}]

    cleanup_old_traces()

    assert "old" not in trace_storage
    assert "new" in trace_storage


def test_cleanup_old_traces_raises_on_bad_timestamp():
    """cleanup_old_traces should raise ValueError when timestamps are not ISO format."""
    trace_storage["bad"] = [{"timestamp": "not-a-valid-iso"}]
    with pytest.raises(ValueError):
        cleanup_old_traces()