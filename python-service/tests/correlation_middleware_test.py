import pytest
from unittest.mock import patch, Mock

from flask import Flask, g, Response

from src.correlation_middleware import (
    CorrelationIDMiddleware,
    CORRELATION_ID_HEADER,
    get_traces,
    get_all_traces,
    trace_storage,
    cleanup_old_traces,
    store_trace,
)


@pytest.fixture
def flask_app():
    """Create a Flask app for testing."""
    app = Flask(__name__)

    @app.route("/hello", methods=["GET"])
    def hello():
        return "ok", 200

    return app


@pytest.fixture
def middleware(flask_app):
    """Attach CorrelationIDMiddleware to the Flask app."""
    return CorrelationIDMiddleware(flask_app)


@pytest.fixture(autouse=True)
def clear_trace_storage():
    """Ensure trace storage is clean before each test."""
    trace_storage.clear()
    yield
    trace_storage.clear()


def test_correlationidmiddleware_init_with_app_registers_hooks(flask_app):
    """Ensure __init__ with app registers before and after request hooks."""
    mw = CorrelationIDMiddleware(flask_app)
    assert mw.app is flask_app
    # Flask stores app-level callbacks under the None blueprint key
    assert any(cb == mw.before_request for cb in flask_app.before_request_funcs.get(None, []))
    assert any(cb == mw.after_request for cb in flask_app.after_request_funcs.get(None, []))
    assert hasattr(flask_app, "correlation_start_time")
    assert flask_app.correlation_start_time is None


def test_correlationidmiddleware_init_without_app_does_not_register():
    """Ensure __init__ without app does not register hooks immediately."""
    mw = CorrelationIDMiddleware(app=None)
    assert mw.app is None
    # No hooks to assert since no app was provided; ensure we can still init later
    app = Flask(__name__)
    mw.init_app(app)
    assert any(cb == mw.before_request for cb in app.before_request_funcs.get(None, []))
    assert any(cb == mw.after_request for cb in app.after_request_funcs.get(None, []))


def test_correlationidmiddleware_init_app_registers(flask_app):
    """Ensure init_app explicitly registers hooks and sets app attributes."""
    mw = CorrelationIDMiddleware()
    mw.init_app(flask_app)
    assert any(cb == mw.before_request for cb in flask_app.before_request_funcs.get(None, []))
    assert any(cb == mw.after_request for cb in flask_app.after_request_funcs.get(None, []))
    assert hasattr(flask_app, "correlation_start_time")
    assert flask_app.correlation_start_time is None


def test_correlationidmiddleware_extract_or_generate_uses_existing_valid_id():
    """extract_or_generate_correlation_id should use a valid incoming header value."""
    mw = CorrelationIDMiddleware()
    valid_id = "valid-12345"

    request_mock = Mock()
    request_mock.headers = {CORRELATION_ID_HEADER: valid_id}

    result = mw.extract_or_generate_correlation_id(request_mock)
    assert result == valid_id


def test_correlationidmiddleware_extract_or_generate_generates_when_invalid_header():
    """extract_or_generate_correlation_id should generate a new ID when header is invalid."""
    mw = CorrelationIDMiddleware()

    request_mock = Mock()
    request_mock.headers = {CORRELATION_ID_HEADER: "short"}  # invalid due to length

    with patch.object(mw, "generate_correlation_id", return_value="generated-12345") as gen_mock:
        result = mw.extract_or_generate_correlation_id(request_mock)
        assert result == "generated-12345"
        gen_mock.assert_called_once()


def test_correlationidmiddleware_generate_correlation_id_valid_format():
    """generate_correlation_id should return a valid, non-empty correlation ID."""
    mw = CorrelationIDMiddleware()
    cid = mw.generate_correlation_id()
    assert isinstance(cid, str)
    assert mw.is_valid_correlation_id(cid)
    assert "-py-" in cid


def test_correlationidmiddleware_is_valid_various_cases():
    """is_valid_correlation_id should validate type, length, and allowed characters."""
    mw = CorrelationIDMiddleware()

    assert mw.is_valid_correlation_id("a" * 10) is True
    assert mw.is_valid_correlation_id("valid-ABC_123") is True

    assert mw.is_valid_correlation_id(123) is False
    assert mw.is_valid_correlation_id("short123") is False  # 8 chars
    assert mw.is_valid_correlation_id("a" * 101) is False
    assert mw.is_valid_correlation_id("invalid id with space") is False
    assert mw.is_valid_correlation_id("invalid!*char") is False


def test_correlationidmiddleware_before_and_after_request_sets_header_and_stores_trace(flask_app, middleware):
    """Middleware should generate an ID, set it in response headers, and store trace data."""
    client = flask_app.test_client()
    resp = client.get("/hello")

    assert resp.status_code == 200
    assert CORRELATION_ID_HEADER in resp.headers
    cid = resp.headers[CORRELATION_ID_HEADER]
    assert isinstance(cid, str)
    assert middleware.is_valid_correlation_id(cid)

    traces = get_traces(cid)
    assert len(traces) == 1
    t = traces[0]
    assert t["service"] == "python-reviewer"
    assert t["method"] == "GET"
    assert t["path"] == "/hello"
    assert t["correlation_id"] == cid
    assert isinstance(t["timestamp"], str)
    assert isinstance(t["duration_ms"], (int, float))
    assert t["status"] == 200


def test_correlationidmiddleware_propagates_existing_header(flask_app, middleware):
    """Middleware should propagate an existing valid correlation ID header."""
    client = flask_app.test_client()
    existing = "existing-12345"
    resp = client.get("/hello", headers={CORRELATION_ID_HEADER: existing})

    assert resp.status_code == 200
    assert resp.headers[CORRELATION_ID_HEADER] == existing

    traces = get_traces(existing)
    assert len(traces) == 1
    assert traces[0]["correlation_id"] == existing


def test_correlationidmiddleware_after_request_without_correlation_id_does_not_add_header(flask_app):
    """after_request should not add a correlation header or store a trace if not set in g."""
    mw = CorrelationIDMiddleware(flask_app)

    with flask_app.test_request_context("/hello", method="GET"):
        # Intentionally bypass mw.before_request to simulate missing g.correlation_id
        response = Response("ok", status=200)
        result = mw.after_request(response)

    assert CORRELATION_ID_HEADER not in result.headers
    assert get_all_traces() == {}


def test_store_trace_and_get_traces_return_copy():
    """store_trace should append traces, and get_traces should return a copy."""
    cid = "test-123456"
    data1 = {
        "service": "python-reviewer",
        "method": "GET",
        "path": "/x",
        "timestamp": "2000-01-01T00:00:00",
        "correlation_id": cid,
        "duration_ms": 1.23,
        "status": 200,
    }
    data2 = {
        "service": "python-reviewer",
        "method": "POST",
        "path": "/y",
        "timestamp": "2000-01-01T00:00:01",
        "correlation_id": cid,
        "duration_ms": 2.34,
        "status": 201,
    }
    store_trace(cid, data1)
    store_trace(cid, data2)

    traces = get_traces(cid)
    assert len(traces) == 2

    traces.append({"correlation_id": cid})
    # Original storage should not be modified by external changes
    assert len(get_traces(cid)) == 2


def test_get_all_traces_returns_copy():
    """get_all_traces should return a copy of the trace storage."""
    cid = "copy-123456"
    data = {
        "service": "python-reviewer",
        "method": "GET",
        "path": "/",
        "timestamp": "2000-01-01T00:00:00",
        "correlation_id": cid,
        "duration_ms": 1.0,
        "status": 200,
    }
    store_trace(cid, data)

    all_traces = get_all_traces()
    assert cid in all_traces
    all_traces[cid].append({"correlation_id": cid})
    # Ensure original storage is unchanged
    assert len(get_all_traces()[cid]) == 1


def test_cleanup_old_traces_removes_outdated():
    """cleanup_old_traces should remove correlation IDs whose oldest trace is older than 1 hour."""
    old_cid = "old-123456"
    new_cid = "new-123456"

    # Inject traces directly with timestamps to control age
    trace_storage[old_cid] = [
        {
            "service": "python-reviewer",
            "method": "GET",
            "path": "/old",
            "timestamp": "2000-01-01T00:00:00",
            "correlation_id": old_cid,
            "duration_ms": 1.0,
            "status": 200,
        }
    ]
    trace_storage[new_cid] = [
        {
            "service": "python-reviewer",
            "method": "GET",
            "path": "/new",
            "timestamp": "2999-01-01T00:00:00",
            "correlation_id": new_cid,
            "duration_ms": 1.0,
            "status": 200,
        }
    ]

    cleanup_old_traces()

    assert old_cid not in trace_storage
    assert new_cid in trace_storage