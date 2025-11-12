import pytest
from unittest.mock import patch, MagicMock
from flask import Flask, g, jsonify

from src.correlation_middleware import (
    CorrelationIDMiddleware,
    CORRELATION_ID_HEADER,
    store_trace,
    get_traces,
    get_all_traces,
    cleanup_old_traces,
    trace_storage,
)
from datetime import datetime, timedelta


@pytest.fixture(autouse=True)
def clear_trace_storage():
    """Ensure trace_storage is cleared before and after each test."""
    trace_storage.clear()
    yield
    trace_storage.clear()


@pytest.fixture
def app():
    """Create a Flask app with CorrelationIDMiddleware registered."""
    app = Flask(__name__)
    CorrelationIDMiddleware(app)

    @app.route("/ping")
    def ping():
        # Return correlation_id and request_start_time for assertions
        cid = getattr(g, "correlation_id", "")
        start = getattr(g, "request_start_time", None)
        return jsonify({"cid": cid, "start": start})

    return app


@pytest.fixture
def client(app):
    """Return a test client for the Flask app."""
    return app.test_client()


def test_CorrelationIDMiddleware_init_without_app():
    """__init__ with app=None should not register hooks or set app attribute."""
    mw = CorrelationIDMiddleware()
    assert mw.app is None


def test_CorrelationIDMiddleware_init_with_app_registers_hooks_and_attr():
    """__init__ with app should register hooks and set app.correlation_start_time."""
    app = Flask(__name__)
    mw = CorrelationIDMiddleware(app)
    assert hasattr(app, "correlation_start_time")
    assert app.correlation_start_time is None

    # Verify that making a request triggers middleware (header is set)
    @app.route("/test")
    def test():
        return "ok"

    c = app.test_client()
    resp = c.get("/test")
    assert resp.status_code == 200
    assert CORRELATION_ID_HEADER in resp.headers


def test_CorrelationIDMiddleware_init_app_registers_lifecycle():
    """init_app should register before_request and after_request handlers."""
    app = Flask(__name__)
    mw = CorrelationIDMiddleware()
    mw.init_app(app)

    @app.route("/route")
    def route():
        return getattr(g, "correlation_id", "")

    c = app.test_client()
    resp = c.get("/route")
    assert resp.status_code == 200
    assert CORRELATION_ID_HEADER in resp.headers
    assert resp.data.decode() == resp.headers[CORRELATION_ID_HEADER]


def test_CorrelationIDMiddleware_before_request_sets_g_values(client):
    """before_request should set g.correlation_id and g.request_start_time."""
    valid_id = "valid-corr-12345"
    with patch("src.correlation_middleware.time.time", return_value=1234.5678):
        resp = client.get("/ping", headers={CORRELATION_ID_HEADER: valid_id})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["cid"] == valid_id
    assert data["start"] == pytest.approx(1234.5678)


def test_CorrelationIDMiddleware_extract_or_generate_uses_existing_valid_header():
    """extract_or_generate_correlation_id returns existing header if valid."""
    mw = CorrelationIDMiddleware()
    valid_id = "valid-HEADER_12345"
    req = MagicMock()
    req.headers = {CORRELATION_ID_HEADER: valid_id}
    assert mw.extract_or_generate_correlation_id(req) == valid_id


def test_CorrelationIDMiddleware_extract_or_generate_generates_when_invalid_or_missing():
    """extract_or_generate_correlation_id calls generate when header missing/invalid."""
    mw = CorrelationIDMiddleware()

    # Missing header
    req_missing = MagicMock()
    req_missing.headers = {}
    with patch.object(mw, "generate_correlation_id", return_value="gen-fixed") as gen:
        result = mw.extract_or_generate_correlation_id(req_missing)
        assert result == "gen-fixed"
        gen.assert_called_once()

    # Invalid header
    req_invalid = MagicMock()
    req_invalid.headers = {CORRELATION_ID_HEADER: "bad$$$$$id!"}
    with patch.object(mw, "generate_correlation_id", return_value="gen-fixed-2") as gen2:
        result2 = mw.extract_or_generate_correlation_id(req_invalid)
        assert result2 == "gen-fixed-2"
        gen2.assert_called_once()


def test_CorrelationIDMiddleware_generate_correlation_id_deterministic_with_patched_time():
    """generate_correlation_id should produce expected format using patched time."""
    mw = CorrelationIDMiddleware()
    # time.time() will be 1700000000.123456
    with patch("src.correlation_middleware.time.time", return_value=1700000000.123456):
        cid = mw.generate_correlation_id()
    # int(1700000000.123456) = 1700000000
    # int(1700000000.123456 * 1e6) % 100000 = 23456
    assert cid == "1700000000-py-23456"


@pytest.mark.parametrize(
    "value, expected",
    [
        ("abcdefghij", True),  # length 10
        ("a" * 100, True),     # length 100
        ("abc_def-123XYZ", True),
        ("short", False),               # too short
        ("a" * 101, False),             # too long
        ("invalid$$$chars", False),     # invalid chars
        (None, False),                  # non-string
        (12345, False),                 # non-string
        (12.34, False),                 # non-string
    ],
)
def test_CorrelationIDMiddleware_is_valid_correlation_id_cases(value, expected):
    """is_valid_correlation_id should validate length and allowed characters."""
    mw = CorrelationIDMiddleware()
    assert mw.is_valid_correlation_id(value) is expected


def test_CorrelationIDMiddleware_after_request_sets_header_and_stores_trace():
    """after_request should set the header and call store_trace with expected data."""
    app = Flask(__name__)
    CorrelationIDMiddleware(app)

    @app.route("/trace")
    def trace():
        return "ok"

    valid_id = "valid-corr-12345"
    with patch("src.correlation_middleware.store_trace") as mock_store, \
         patch("src.correlation_middleware.time.time", side_effect=[100.0, 100.2]):
        c = app.test_client()
        resp = c.get("/trace", headers={CORRELATION_ID_HEADER: valid_id})

    assert resp.status_code == 200
    assert resp.headers.get(CORRELATION_ID_HEADER) == valid_id

    # Ensure store_trace called once with proper correlation_id and trace_data
    assert mock_store.call_count == 1
    args, kwargs = mock_store.call_args
    assert args[0] == valid_id
    trace_data = args[1]
    assert trace_data["service"] == "python-reviewer"
    assert trace_data["method"] == "GET"
    assert trace_data["path"] == "/trace"
    assert trace_data["correlation_id"] == valid_id
    assert isinstance(trace_data["timestamp"], str)
    assert trace_data["status"] == 200
    assert trace_data["duration_ms"] == pytest.approx(200.0)


def test_CorrelationIDMiddleware_after_request_no_header_when_no_correlation_id():
    """after_request should not set header or store trace when no correlation_id on g."""
    app = Flask(__name__)
    CorrelationIDMiddleware(app)

    @app.route("/no-header")
    def no_header():
        # Simulate removing correlation_id set by before_request
        if hasattr(g, "correlation_id"):
            delattr(g, "correlation_id")
        return "ok"

    with patch("src.correlation_middleware.store_trace") as mock_store:
        c = app.test_client()
        resp = c.get("/no-header")

    assert resp.status_code == 200
    assert CORRELATION_ID_HEADER not in resp.headers
    mock_store.assert_not_called()


def test_store_trace_and_get_traces_and_get_all_traces_copy_semantics():
    """store_trace should append and getters should return copies."""
    cid = "trace-id-12345"
    now_iso = datetime.now().isoformat()
    td = {"timestamp": now_iso, "path": "/a", "status": 200}

    store_trace(cid, td)

    # get_traces returns a copy
    traces1 = get_traces(cid)
    assert traces1 == [td]
    traces1.append({"timestamp": now_iso, "path": "/b", "status": 201})
    # Original storage should be unchanged
    assert get_traces(cid) == [td]

    # get_all_traces returns copies
    all1 = get_all_traces()
    assert list(all1.keys()) == [cid]
    assert all1[cid] == [td]
    all1[cid].append({"timestamp": now_iso, "path": "/c", "status": 202})
    # Original storage should be unchanged
    assert get_traces(cid) == [td]


def test_cleanup_old_traces_removes_entries_older_than_one_hour():
    """cleanup_old_traces should delete correlation IDs whose oldest trace is older than 1 hour."""
    recent_cid = "recent-12345"
    old_cid = "old-12345"

    recent_td = {"timestamp": datetime.now().isoformat(), "path": "/recent", "status": 200}
    old_td = {"timestamp": (datetime.now() - timedelta(hours=2)).isoformat(), "path": "/old", "status": 200}

    # Store recent first (should remain)
    store_trace(recent_cid, recent_td)
    # Store old; cleanup runs inside store_trace and should delete the old entry immediately
    store_trace(old_cid, old_td)

    # Verify only recent remains
    all_traces = get_all_traces()
    assert recent_cid in all_traces
    assert old_cid not in all_traces


def test_cleanup_old_traces_raises_on_invalid_timestamp():
    """cleanup_old_traces should raise ValueError if timestamps are invalid ISO strings."""
    bad_cid = "badts-12345"
    trace_storage[bad_cid] = [{"timestamp": "not-an-iso", "path": "/bad", "status": 500}]
    with pytest.raises(ValueError):
        cleanup_old_traces()