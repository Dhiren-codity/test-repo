import pytest
from unittest.mock import patch
from flask import Flask, jsonify, g, request, Response

from src.correlation_middleware import (
    CorrelationIDMiddleware,
    CORRELATION_ID_HEADER,
    trace_storage,
    store_trace,
    cleanup_old_traces,
    get_traces,
    get_all_traces,
)


@pytest.fixture(autouse=True)
def clean_trace_storage():
    """Ensure global trace storage is clean before each test."""
    trace_storage.clear()
    yield
    trace_storage.clear()


@pytest.fixture
def app_with_middleware():
    """Create a Flask app with CorrelationIDMiddleware initialized and sample routes."""
    app = Flask(__name__)
    app.testing = True
    middleware = CorrelationIDMiddleware()
    middleware.init_app(app)

    @app.route("/ping")
    def ping():
        return jsonify(
            cid=getattr(g, "correlation_id", None),
            start=isinstance(getattr(g, "request_start_time", None), float),
        )

    @app.route("/after")
    def after():
        return "ok", 200

    return app, middleware


@pytest.fixture
def client(app_with_middleware):
    """Return a Flask test client using the app with middleware."""
    app, _ = app_with_middleware
    return app.test_client()


def test_CorrelationIDMiddleware_init_app_registers_hooks():
    """init_app should register before_request and after_request and set correlation_start_time."""
    app = Flask(__name__)
    app.testing = True

    # Starting hooks should be empty for a new app
    assert not app.before_request_funcs
    assert not app.after_request_funcs

    middleware = CorrelationIDMiddleware()
    middleware.init_app(app)

    # Hooks are registered
    assert None in app.before_request_funcs
    assert None in app.after_request_funcs
    assert len(app.before_request_funcs[None]) == 1
    assert len(app.after_request_funcs[None]) == 1

    # App attribute set by init_app
    assert hasattr(app, "correlation_start_time")
    assert app.correlation_start_time is None


def test_CorrelationIDMiddleware_init_with_app_registers_hooks():
    """__init__ with app should register hooks immediately."""
    app = Flask(__name__)
    app.testing = True

    middleware = CorrelationIDMiddleware(app)

    assert None in app.before_request_funcs
    assert None in app.after_request_funcs
    assert len(app.before_request_funcs[None]) == 1
    assert len(app.after_request_funcs[None]) == 1
    assert hasattr(app, "correlation_start_time")
    assert app.correlation_start_time is None
    assert isinstance(middleware, CorrelationIDMiddleware)


def test_CorrelationIDMiddleware_before_request_sets_values_and_propagates_header(app_with_middleware, client):
    """before_request should set g.correlation_id and g.request_start_time; after_request should propagate header."""
    app, _ = app_with_middleware
    incoming_id = "Valid_ID-12345"

    resp = client.get("/ping", headers={CORRELATION_ID_HEADER: incoming_id})
    data = resp.get_json()

    assert data["cid"] == incoming_id
    assert data["start"] is True
    assert resp.status_code == 200
    assert resp.headers.get(CORRELATION_ID_HEADER) == incoming_id

    # Validate trace storage contains an entry for correlation ID
    traces = get_traces(incoming_id)
    assert len(traces) == 1
    assert traces[0]["correlation_id"] == incoming_id
    assert traces[0]["method"] == "GET"
    assert traces[0]["path"] == "/ping"
    assert traces[0]["status"] == 200
    assert traces[0]["service"] == "python-reviewer"


def test_CorrelationIDMiddleware_after_request_sets_header_and_calls_store_trace(app_with_middleware, client):
    """after_request should set X-Correlation-ID response header and call store_trace with expected data."""
    app, _ = app_with_middleware
    incoming_id = "incoming-123456"

    with patch("src.correlation_middleware.store_trace") as mock_store, patch(
        "src.correlation_middleware.time.time", side_effect=[1000.0, 1000.1]
    ):
        resp = client.get("/after", headers={CORRELATION_ID_HEADER: incoming_id})

    assert resp.status_code == 200
    assert resp.headers.get(CORRELATION_ID_HEADER) == incoming_id

    assert mock_store.call_count == 1
    args, kwargs = mock_store.call_args
    corr_id_arg, trace_data_arg = args
    assert corr_id_arg == incoming_id
    assert trace_data_arg["correlation_id"] == incoming_id
    assert trace_data_arg["method"] == "GET"
    assert trace_data_arg["path"] == "/after"
    assert trace_data_arg["status"] == 200
    assert trace_data_arg["duration_ms"] == 100.0


def test_CorrelationIDMiddleware_after_request_without_correlation_id_noop():
    """after_request should not set header or store traces if g.correlation_id is missing."""
    app = Flask(__name__)
    app.testing = True
    middleware = CorrelationIDMiddleware(app)

    with app.test_request_context("/manual", method="GET"):
        response = Response("ok", status=200)
        with patch("src.correlation_middleware.store_trace") as mock_store:
            result = middleware.after_request(response)

    assert CORRELATION_ID_HEADER not in result.headers
    mock_store.assert_not_called()


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_uses_existing_valid():
    """extract_or_generate_correlation_id should return existing valid ID from headers."""
    app = Flask(__name__)
    app.testing = True
    middleware = CorrelationIDMiddleware()

    with app.test_request_context("/path", headers={CORRELATION_ID_HEADER: "existingValid-12345"}):
        val = middleware.extract_or_generate_correlation_id(request)
        assert val == "existingValid-12345"


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_generates_on_invalid_or_missing():
    """extract_or_generate_correlation_id should call generator when header is invalid or missing."""
    app = Flask(__name__)
    app.testing = True
    middleware = CorrelationIDMiddleware()

    # Invalid (too short)
    with app.test_request_context("/path", headers={CORRELATION_ID_HEADER: "short"}):
        with patch.object(CorrelationIDMiddleware, "generate_correlation_id", return_value="gen-123") as gen_mock:
            val = middleware.extract_or_generate_correlation_id(request)
            assert val == "gen-123"
            gen_mock.assert_called_once()

    # Missing header
    with app.test_request_context("/path"):
        with patch.object(CorrelationIDMiddleware, "generate_correlation_id", return_value="gen-456") as gen_mock:
            val = middleware.extract_or_generate_correlation_id(request)
            assert val == "gen-456"
            gen_mock.assert_called_once()


def test_CorrelationIDMiddleware_generate_correlation_id_format():
    """generate_correlation_id should return a string in the expected format and components."""
    middleware = CorrelationIDMiddleware()
    with patch("src.correlation_middleware.time.time", side_effect=[1700000000.1, 1700000000.1]):
        cid = middleware.generate_correlation_id()

    assert isinstance(cid, str)
    assert cid.startswith("1700000000-py-")
    suffix = cid.split("-py-")[1]
    assert suffix.isdigit()
    assert 0 <= int(suffix) <= 99999


def test_CorrelationIDMiddleware_is_valid_correlation_id_various():
    """is_valid_correlation_id should validate types, length, and character set."""
    middleware = CorrelationIDMiddleware()

    # Valid
    assert middleware.is_valid_correlation_id("AbcDEF_123-xyz") is True

    # Non-string
    assert middleware.is_valid_correlation_id(12345) is False  # type: ignore[arg-type]

    # Too short
    assert middleware.is_valid_correlation_id("short-1") is False

    # Too long
    assert middleware.is_valid_correlation_id("a" * 101) is False

    # Invalid characters
    assert middleware.is_valid_correlation_id("invalid$chars-12345") is False


def test_store_trace_and_get_traces_and_all_traces_copies():
    """store_trace should append traces; getters should return copies not affecting internal storage."""
    cid = "cid-1234567890"
    trace1 = {
        "service": "python-reviewer",
        "method": "GET",
        "path": "/a",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "correlation_id": cid,
        "duration_ms": 1.0,
        "status": 200,
    }
    trace2 = {
        "service": "python-reviewer",
        "method": "POST",
        "path": "/b",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "correlation_id": cid,
        "duration_ms": 2.0,
        "status": 201,
    }

    store_trace(cid, trace1)
    store_trace(cid, trace2)

    traces_copy = get_traces(cid)
    assert len(traces_copy) == 2

    # Mutating the returned copy should not affect internal storage
    traces_copy.pop()
    assert len(traces_copy) == 1
    assert len(get_traces(cid)) == 2

    # get_all_traces returns copies of lists
    all_traces_copy = get_all_traces()
    assert cid in all_traces_copy
    assert all_traces_copy[cid] is not trace_storage[cid]
    all_traces_copy[cid].append({"fake": True})
    assert len(all_traces_copy[cid]) == 3
    assert len(trace_storage[cid]) == 2


def test_cleanup_old_traces_removes_old_entries():
    """cleanup_old_traces should remove correlation IDs whose oldest trace is older than 1 hour."""
    old_ts = (__import__("datetime").datetime.now() - __import__("datetime").timedelta(hours=2)).isoformat()
    cid = "old-cid-123456"
    trace_storage[cid] = [
        {
            "service": "python-reviewer",
            "method": "GET",
            "path": "/old",
            "timestamp": old_ts,
            "correlation_id": cid,
            "duration_ms": 10.0,
            "status": 200,
        },
        {
            "service": "python-reviewer",
            "method": "GET",
            "path": "/recent",
            "timestamp": __import__("datetime").datetime.now().isoformat(),
            "correlation_id": cid,
            "duration_ms": 5.0,
            "status": 200,
        },
    ]

    cleanup_old_traces()
    assert cid not in trace_storage


def test_cleanup_old_traces_keeps_recent_entries():
    """cleanup_old_traces should keep entries whose oldest trace is within the last hour."""
    recent_ts = (__import__("datetime").datetime.now() - __import__("datetime").timedelta(minutes=30)).isoformat()
    cid = "recent-cid-123456"
    trace_storage[cid] = [
        {
            "service": "python-reviewer",
            "method": "GET",
            "path": "/recent",
            "timestamp": recent_ts,
            "correlation_id": cid,
            "duration_ms": 3.0,
            "status": 200,
        }
    ]

    cleanup_old_traces()
    assert cid in trace_storage


def test_cleanup_old_traces_on_empty_storage_no_error():
    """cleanup_old_traces should not raise when storage is empty."""
    assert trace_storage == {}
    cleanup_old_traces()
    assert trace_storage == {}