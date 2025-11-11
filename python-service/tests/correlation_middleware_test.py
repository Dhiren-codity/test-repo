import pytest
from unittest.mock import patch, MagicMock
from flask import Flask, jsonify, g, request
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
def clear_trace_storage():
    """Clear the global trace storage before each test."""
    trace_storage.clear()
    yield
    trace_storage.clear()


@pytest.fixture
def app():
    """Create a Flask app and register the CorrelationIDMiddleware with a simple route."""
    app = Flask(__name__)
    mw = CorrelationIDMiddleware(app)

    @app.get("/echo")
    def echo():
        return jsonify(
            header_name=CORRELATION_ID_HEADER,
            g_corr=getattr(g, "correlation_id", None),
            has_start_time=hasattr(g, "request_start_time"),
            path=request.path,
        )

    @app.get("/nop")
    def nop():
        return "ok", 200

    return app


@pytest.fixture
def client(app):
    """Flask test client for the app."""
    return app.test_client()


def test_CorrelationIDMiddleware_init_sets_app_and_registers_hooks(app, client):
    """Ensure __init__ with app registers before/after request hooks and sets app attribute."""
    # The presence of a correlation ID header in the response implies the hooks are installed.
    resp = client.get("/echo")
    assert resp.status_code == 200
    assert CORRELATION_ID_HEADER in resp.headers
    assert hasattr(app, "correlation_start_time")
    assert app.correlation_start_time is None


def test_CorrelationIDMiddleware_init_app_manual_registration():
    """Ensure init_app can be called after construction without app."""
    app = Flask(__name__)

    mw = CorrelationIDMiddleware()
    assert mw.app is None  # attribute isn't set in __init__ without app
    mw.init_app(app)

    @app.get("/x")
    def x():
        return "x"

    client = app.test_client()
    resp = client.get("/x")
    # Header should be set by after_request hook
    assert CORRELATION_ID_HEADER in resp.headers


def test_CorrelationIDMiddleware_before_request_sets_g_values(client):
    """Verify before_request sets g.correlation_id and g.request_start_time."""
    resp = client.get("/echo")
    payload = resp.get_json()
    assert payload["g_corr"] is not None
    assert payload["has_start_time"] is True


def test_CorrelationIDMiddleware_after_request_sets_header_and_stores_trace(client):
    """Verify after_request attaches header and stores trace data in global storage."""
    incoming_id = "valid-1234567890"
    resp = client.get("/echo", headers={CORRELATION_ID_HEADER: incoming_id})
    assert resp.status_code == 200
    assert resp.headers[CORRELATION_ID_HEADER] == incoming_id

    traces = get_traces(incoming_id)
    assert isinstance(traces, list)
    assert len(traces) == 1
    t = traces[0]
    assert t["service"] == "python-reviewer"
    assert t["method"] == "GET"
    assert t["path"] == "/echo"
    assert t["correlation_id"] == incoming_id
    assert isinstance(t["duration_ms"], float) or isinstance(t["duration_ms"], int)
    assert t["status"] == 200
    assert "timestamp" in t and isinstance(t["timestamp"], str)


def test_CorrelationIDMiddleware_after_request_no_correlation_id_safe():
    """after_request should be safe when g.correlation_id is missing and not mutate headers or traces."""
    app = Flask(__name__)
    mw = CorrelationIDMiddleware(app)

    with app.test_request_context("/manual"):
        resp = app.make_response(("OK", 200))
        # Ensure g has no correlation_id set by avoiding calling before_request
        out = mw.after_request(resp)
        assert CORRELATION_ID_HEADER not in out.headers
        assert len(get_all_traces()) == 0


def test_CorrelationIDMiddleware_extract_or_generate_valid_header(client, monkeypatch):
    """extract_or_generate_correlation_id should accept a valid incoming header and not call generate."""
    # Make generate_correlation_id raise if called, ensuring existing header is used
    with patch.object(CorrelationIDMiddleware, "generate_correlation_id", side_effect=AssertionError("Should not be called")):
        incoming = "valid-ABCDEFGHIJ"
        resp = client.get("/echo", headers={CORRELATION_ID_HEADER: incoming})
        assert resp.headers[CORRELATION_ID_HEADER] == incoming


def test_CorrelationIDMiddleware_extract_or_generate_invalid_header_generates_new(client, monkeypatch):
    """Invalid header should trigger ID generation and header replacement."""
    gen_value = "generated-id-12345"
    with patch.object(CorrelationIDMiddleware, "generate_correlation_id", return_value=gen_value):
        incoming = "short"
        resp = client.get("/echo", headers={CORRELATION_ID_HEADER: incoming})
        assert resp.status_code == 200
        assert resp.headers[CORRELATION_ID_HEADER] == gen_value
        assert resp.headers[CORRELATION_ID_HEADER] != incoming


def test_CorrelationIDMiddleware_generate_correlation_id_time_based(monkeypatch):
    """generate_correlation_id should follow the 'epoch-py-suffix' format using time.time()."""
    # The function uses time.time() twice; set a deterministic float
    fixed_time = 1700000000.123456
    with patch("src.correlation_middleware.time.time", return_value=fixed_time):
        result = CorrelationIDMiddleware.generate_correlation_id()
        # Expected prefix and suffix computation
        expected_epoch = str(int(fixed_time))
        expected_suffix = int(fixed_time * 1000000) % 100000
        assert result.startswith(expected_epoch + "-py-")
        assert result.endswith(str(expected_suffix))


def test_CorrelationIDMiddleware_is_valid_correlation_id_cases():
    """Test is_valid_correlation_id across valid and invalid cases."""
    assert CorrelationIDMiddleware.is_valid_correlation_id(123) is False
    assert CorrelationIDMiddleware.is_valid_correlation_id("short") is False
    assert CorrelationIDMiddleware.is_valid_correlation_id("a" * 101) is False
    assert CorrelationIDMiddleware.is_valid_correlation_id("invalid!!char") is False
    assert CorrelationIDMiddleware.is_valid_correlation_id("abc-1234567890") is True
    assert CorrelationIDMiddleware.is_valid_correlation_id("abc_def-12345") is True


def test_store_trace_appends_and_calls_cleanup(monkeypatch):
    """store_trace should append trace and call cleanup_old_traces."""
    called = {"cleanup": 0}

    def fake_cleanup():
        called["cleanup"] += 1

    monkeypatch.setattr("src.correlation_middleware.cleanup_old_traces", fake_cleanup)
    cid = "valid-1234567890"
    trace_data = {"timestamp": "2024-01-01T12:00:00", "path": "/t", "status": 200}
    store_trace(cid, trace_data)

    assert called["cleanup"] == 1
    traces = get_traces(cid)
    assert len(traces) == 1
    assert traces[0]["path"] == "/t"
    assert traces[0]["status"] == 200


def test_cleanup_old_traces_removes_old_entries():
    """cleanup_old_traces should remove entries older than one hour based on oldest trace timestamp."""
    from datetime import datetime, timedelta

    old_id = "old-1234567890"
    new_id = "new-1234567890"
    old_ts = (datetime.now() - timedelta(hours=2)).isoformat()
    trace_storage[old_id] = [{"timestamp": old_ts, "path": "/old", "status": 200}]

    # Trigger cleanup by storing a new trace for another id
    store_trace(new_id, {"timestamp": datetime.now().isoformat(), "path": "/new", "status": 201})

    assert old_id not in trace_storage
    assert new_id in trace_storage


def test_get_traces_returns_copy_not_reference():
    """get_traces should return a copy such that mutations do not affect internal storage."""
    cid = "valid-1234567890"
    store_trace(cid, {"timestamp": "2024-01-01T00:00:00", "path": "/a", "status": 200})
    res = get_traces(cid)
    assert len(res) == 1
    res.append({"timestamp": "2024-01-01T00:00:01"})
    # Internal storage should not be affected
    assert len(get_traces(cid)) == 1


def test_get_all_traces_returns_deep_copy_like_structure():
    """get_all_traces should return a structure that can be mutated without affecting storage."""
    cid = "valid-1234567890"
    store_trace(cid, {"timestamp": "2024-01-01T00:00:00", "path": "/a", "status": 200})
    all_traces = get_all_traces()
    assert cid in all_traces
    all_traces[cid].append({"timestamp": "2024-01-01T00:00:05"})
    # Original storage should remain unchanged
    original = get_all_traces()
    assert len(original[cid]) == 1


def test_CorrelationIDMiddleware_response_cycle_with_valid_header_fields_present(client):
    """Full request cycle with a valid header should preserve ID and set fields correctly."""
    incoming_id = "valid-ABCDEFGHIJ"
    resp = client.get("/echo", headers={CORRELATION_ID_HEADER: incoming_id})
    payload = resp.get_json()
    assert resp.headers[CORRELATION_ID_HEADER] == incoming_id
    assert payload["g_corr"] == incoming_id
    assert payload["path"] == "/echo"


def test_CorrelationIDMiddleware_generate_called_when_missing_header(client):
    """When header is missing, generate_correlation_id should be called and its value used."""
    with patch.object(CorrelationIDMiddleware, "generate_correlation_id", return_value="gen-9999999999") as gen:
        resp = client.get("/echo")
        assert resp.headers[CORRELATION_ID_HEADER] == "gen-9999999999"
        gen.assert_called_once()