import pytest
from unittest.mock import Mock, patch
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


@pytest.fixture
def flask_app():
    """Create a Flask app instance for testing with testing enabled."""
    app = Flask(__name__)
    app.testing = True
    return app


@pytest.fixture
def middleware():
    """Create a CorrelationIDMiddleware instance not bound to an app."""
    return CorrelationIDMiddleware()


@pytest.fixture(autouse=True)
def clean_trace_storage():
    """Ensure trace_storage is clean before and after each test."""
    trace_storage.clear()
    yield
    trace_storage.clear()


def test_CorrelationIDMiddleware___init___with_app_calls_init_app(flask_app):
    """__init__ should call init_app when app is provided."""
    with patch.object(CorrelationIDMiddleware, "init_app") as mock_init:
        mid = CorrelationIDMiddleware(app=flask_app)
        mock_init.assert_called_once_with(flask_app)
        assert isinstance(mid, CorrelationIDMiddleware)


def test_CorrelationIDMiddleware___init___without_app_does_not_call_init_app():
    """__init__ should not call init_app when app is None."""
    with patch.object(CorrelationIDMiddleware, "init_app") as mock_init:
        _ = CorrelationIDMiddleware()
        mock_init.assert_not_called()


def test_CorrelationIDMiddleware_init_app_registers_hooks_and_sets_attr(flask_app, middleware):
    """init_app should register before/after request hooks and set app attribute."""
    middleware.init_app(flask_app)
    # Flask stores functions keyed by blueprint name None
    assert any(func.__name__ == middleware.before_request.__name__
               for func in flask_app.before_request_funcs.get(None, []))
    assert any(func.__name__ == middleware.after_request.__name__
               for func in flask_app.after_request_funcs.get(None, []))
    assert hasattr(flask_app, "correlation_start_time")
    assert flask_app.correlation_start_time is None


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_valid_header(middleware):
    """extract_or_generate_correlation_id should return existing valid header."""
    req = Mock()
    valid_id = "valid_id-12345"
    req.headers = {CORRELATION_ID_HEADER: valid_id}
    cid = middleware.extract_or_generate_correlation_id(req)
    assert cid == valid_id


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_invalid_header_generates(middleware):
    """extract_or_generate_correlation_id should generate when header is invalid."""
    req = Mock()
    req.headers = {CORRELATION_ID_HEADER: "bad id!*"}
    with patch.object(middleware, "generate_correlation_id", return_value="generated-42") as mock_gen:
        cid = middleware.extract_or_generate_correlation_id(req)
        mock_gen.assert_called_once()
        assert cid == "generated-42"


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_missing_header_generates(middleware):
    """extract_or_generate_correlation_id should generate when header is missing."""
    req = Mock()
    req.headers = {}
    with patch.object(middleware, "generate_correlation_id", return_value="gen-1") as mock_gen:
        cid = middleware.extract_or_generate_correlation_id(req)
        mock_gen.assert_called_once()
        assert cid == "gen-1"


def test_CorrelationIDMiddleware_is_valid_correlation_id_various_cases(middleware):
    """is_valid_correlation_id should validate length, type, and allowed chars."""
    # Valid cases
    assert middleware.is_valid_correlation_id("abcdefghij") is True  # length 10
    assert middleware.is_valid_correlation_id("a" * 100) is True     # length 100
    assert middleware.is_valid_correlation_id("valid_ABC-12345") is True

    # Invalid type
    assert middleware.is_valid_correlation_id(12345) is False

    # Too short
    assert middleware.is_valid_correlation_id("short") is False

    # Too long
    assert middleware.is_valid_correlation_id("a" * 101) is False

    # Invalid characters (space and punctuation not allowed)
    assert middleware.is_valid_correlation_id("invalid id") is False
    assert middleware.is_valid_correlation_id("bad*chars") is False


def test_CorrelationIDMiddleware_generate_correlation_id_deterministic_with_time_patch(middleware, monkeypatch):
    """generate_correlation_id should produce deterministic format based on time."""
    def fake_time():
        return 1700000000.123456

    monkeypatch.setattr("time.time", fake_time)
    expected = "1700000000-py-23456"
    assert middleware.generate_correlation_id() == expected


def test_CorrelationIDMiddleware_before_request_sets_g_values_from_header(flask_app):
    """before_request should set g.correlation_id and g.request_start_time."""
    CorrelationIDMiddleware(flask_app)

    @flask_app.route("/ping")
    def ping():
        return jsonify(
            cid=getattr(g, "correlation_id", None),
            start=getattr(g, "request_start_time", None),
        )

    client = flask_app.test_client()
    cid = "cid_valid_12345"
    rv = client.get("/ping", headers={CORRELATION_ID_HEADER: cid})
    data = rv.get_json()
    assert data["cid"] == cid
    assert isinstance(data["start"], float)


def test_CorrelationIDMiddleware_after_request_sets_header_and_stores_trace(flask_app, monkeypatch):
    """after_request should set header and call store_trace with expected data."""
    CorrelationIDMiddleware(flask_app)

    @flask_app.route("/test")
    def test_route():
        return "ok", 200

    captured = {}

    def fake_store_trace(correlation_id, trace_data):
        captured["correlation_id"] = correlation_id
        captured["trace_data"] = trace_data

    # Use a small deterministic delta for duration
    times = [1000.0, 1000.050]
    def fake_time():
        return times.pop(0) if times else 1000.050

    monkeypatch.setattr("src.correlation_middleware.store_trace", fake_store_trace)
    monkeypatch.setattr("time.time", fake_time)

    client = flask_app.test_client()
    cid = "valid_abc12345"
    rv = client.get("/test", headers={CORRELATION_ID_HEADER: cid})

    assert rv.status_code == 200
    assert rv.headers[CORRELATION_ID_HEADER] == cid

    assert captured["correlation_id"] == cid
    td = captured["trace_data"]
    assert td["service"] == "python-reviewer"
    assert td["method"] == "GET"
    assert td["path"] == "/test"
    assert td["correlation_id"] == cid
    assert td["status"] == 200
    # Timestamp should be ISO format parseable
    from datetime import datetime
    _ = datetime.fromisoformat(td["timestamp"])
    # Duration should be float with rounding applied
    assert isinstance(td["duration_ms"], float)
    assert td["duration_ms"] >= 0.0


def test_CorrelationIDMiddleware_after_request_with_missing_g_correlation_id_skips(flask_app, monkeypatch):
    """after_request should skip header setting and trace storage if correlation_id not present."""
    CorrelationIDMiddleware(flask_app)

    @flask_app.route("/skip")
    def skip():
        # Simulate code that removes the correlation_id before after_request runs
        if hasattr(g, "correlation_id"):
            delattr(g, "correlation_id")
        return "ok", 200

    mocked = Mock()
    monkeypatch.setattr("src.correlation_middleware.store_trace", mocked)

    client = flask_app.test_client()
    rv = client.get("/skip", headers={CORRELATION_ID_HEADER: "valid_cid_1234"})
    assert rv.status_code == 200
    assert CORRELATION_ID_HEADER not in rv.headers
    mocked.assert_not_called()


def test_CorrelationIDMiddleware_after_request_path_excludes_query_string(flask_app, monkeypatch):
    """after_request should record request.path without query string."""
    CorrelationIDMiddleware(flask_app)

    @flask_app.route("/q")
    def q():
        return "ok", 200

    captured = {}

    def fake_store_trace(correlation_id, trace_data):
        captured["trace_data"] = trace_data

    monkeypatch.setattr("src.correlation_middleware.store_trace", fake_store_trace)

    client = flask_app.test_client()
    rv = client.get("/q?x=1&y=2", headers={CORRELATION_ID_HEADER: "valid_q_123456"})
    assert rv.status_code == 200
    assert captured["trace_data"]["path"] == "/q"


def test_store_trace_and_get_traces_end_to_end():
    """store_trace should append traces and get_traces should return a copy."""
    cid = "trace_id_12345"
    td1 = {"timestamp": __import__("datetime").datetime.now().isoformat(), "x": 1}
    store_trace(cid, td1)
    traces = get_traces(cid)
    assert len(traces) == 1
    assert traces[0]["x"] == 1

    # Mutate the returned list; underlying storage should not change
    traces.append({"timestamp": td1["timestamp"], "x": 2})
    assert len(get_traces(cid)) == 1


def test_get_all_traces_returns_copy():
    """get_all_traces should return a deep-ish copy so external mutations don't affect storage."""
    cid1 = "cid1_valid_123"
    cid2 = "cid2_valid_456"
    now_iso = __import__("datetime").datetime.now().isoformat()
    store_trace(cid1, {"timestamp": now_iso, "v": 1})
    store_trace(cid2, {"timestamp": now_iso, "v": 2})

    all_traces = get_all_traces()
    assert set(all_traces.keys()) == {cid1, cid2}
    # Mutating returned lists should not affect internal storage
    all_traces[cid1].append({"timestamp": now_iso, "v": 99})
    assert len(get_traces(cid1)) == 1


def test_cleanup_old_traces_removes_older_than_one_hour():
    """cleanup_old_traces should delete correlation_ids whose oldest trace is older than 1 hour."""
    from datetime import datetime, timedelta

    now = datetime.now()
    old_ts = (now - timedelta(hours=2)).isoformat()
    new_ts = (now - timedelta(minutes=10)).isoformat()

    cid_old = "old_trace_12345"
    cid_new = "new_trace_12345"

    # Directly setup storage
    trace_storage[cid_old] = [{"timestamp": old_ts, "v": 1}]
    trace_storage[cid_new] = [{"timestamp": new_ts, "v": 2}]

    cleanup_old_traces()
    assert cid_old not in trace_storage
    assert cid_new in trace_storage


def test_CorrelationIDMiddleware_is_valid_correlation_id_non_string_returns_false(middleware):
    """is_valid_correlation_id should handle non-string input without raising exceptions."""
    assert middleware.is_valid_correlation_id(None) is False
    assert middleware.is_valid_correlation_id(123) is False