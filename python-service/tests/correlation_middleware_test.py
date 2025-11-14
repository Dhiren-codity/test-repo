import re
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from flask import Flask, g, jsonify

from src.correlation_middleware import (
    CORRELATION_ID_HEADER,
    CorrelationIDMiddleware,
    cleanup_old_traces,
    get_all_traces,
    get_traces,
    store_trace,
    trace_storage,
)


@pytest.fixture(autouse=True)
def clear_trace_storage():
    """Ensure trace storage is cleared before and after each test."""
    trace_storage.clear()
    yield
    trace_storage.clear()


@pytest.fixture
def flask_app():
    """Create a Flask app with routes for testing."""
    app = Flask(__name__)

    @app.route("/ping")
    def ping():
        return jsonify({"message": "pong"}), 200

    @app.route("/noci")
    def noci():
        # Explicitly remove correlation_id to test after_request no-op path
        if hasattr(g, "correlation_id"):
            del g.correlation_id
        return jsonify({"message": "no correlation"}), 200

    return app


@pytest.fixture
def middleware(flask_app):
    """Instantiate the CorrelationIDMiddleware and register it with the Flask app."""
    return CorrelationIDMiddleware(flask_app)


@pytest.fixture
def client(flask_app, middleware):
    """Flask test client with middleware registered."""
    return flask_app.test_client()


def test_correlationidmiddleware_init_without_app():
    """Test that initializing without an app does not raise and retains app=None."""
    middleware = CorrelationIDMiddleware(app=None)
    assert middleware.app is None


def test_correlationidmiddleware_init_app_registers_hooks():
    """Test that init_app registers before_request and after_request, and sets correlation_start_time."""
    class DummyApp:
        def __init__(self):
            self._before = []
            self._after = []
            self.correlation_start_time = "should_be_overwritten"

        def before_request(self, f):
            self._before.append(f)

        def after_request(self, f):
            self._after.append(f)

    app = DummyApp()
    middleware = CorrelationIDMiddleware()
    middleware.init_app(app)

    assert len(app._before) == 1
    assert len(app._after) == 1
    assert app.correlation_start_time is None

    # Ensure the registered functions are the middleware's methods
    assert app._before[0].__func__ is CorrelationIDMiddleware.before_request
    assert app._after[0].__func__ is CorrelationIDMiddleware.after_request


def test_correlationidmiddleware_before_and_after_request_integration_sets_header_and_traces(client):
    """Test that the middleware sets the correlation header and stores the trace with expected fields."""
    # Provide a valid correlation id in header to avoid generate_correlation_id and control timing precisely
    corr_id = "valid_id-12345"

    # Simulate two time.time() calls: before_request and after_request for duration calculation
    times = iter([100.0, 100.123])  # 123ms duration

    def fake_time():
        return next(times)

    with patch("src.correlation_middleware.time.time", side_effect=fake_time):
        resp = client.get("/ping", headers={CORRELATION_ID_HEADER: corr_id})

    assert resp.status_code == 200
    assert resp.headers.get(CORRELATION_ID_HEADER) == corr_id

    traces = get_traces(corr_id)
    assert len(traces) == 1
    trace = traces[0]

    assert trace["service"] == "python-reviewer"
    assert trace["method"] == "GET"
    assert trace["path"] == "/ping"
    # Validate ISO timestamp format
    assert re.match(r"\d{4}-\d{2}-\d{2}T", trace["timestamp"]) is not None
    assert trace["correlation_id"] == corr_id
    assert trace["duration_ms"] == 123.0
    assert trace["status"] == 200


def test_correlationidmiddleware_extract_or_generate_uses_existing_header_when_valid():
    """Test that extract_or_generate_correlation_id returns the header value if valid."""
    middleware = CorrelationIDMiddleware()
    mock_request = SimpleNamespace(headers={CORRELATION_ID_HEADER: "abc_def-123456"})
    result = middleware.extract_or_generate_correlation_id(mock_request)
    assert result == "abc_def-123456"


def test_correlationidmiddleware_extract_or_generate_generates_when_header_invalid():
    """Test that invalid header causes generate_correlation_id to be invoked."""
    middleware = CorrelationIDMiddleware()
    mock_request = SimpleNamespace(headers={CORRELATION_ID_HEADER: "short"})

    with patch.object(middleware, "generate_correlation_id", return_value="gen-expected") as mock_gen:
        result = middleware.extract_or_generate_correlation_id(mock_request)
        mock_gen.assert_called_once()
        assert result == "gen-expected"


def test_correlationidmiddleware_generate_correlation_id_format():
    """Test that generated correlation ID follows the expected timestamp-based format."""
    middleware = CorrelationIDMiddleware()
    fixed_time = 1700000000.123456  # known value to compute expected suffix

    with patch("src.correlation_middleware.time.time", return_value=fixed_time):
        cid = middleware.generate_correlation_id()

    # Expect "1700000000-py-23456"
    assert re.fullmatch(r"1700000000-py-23456", cid) is not None


def test_correlationidmiddleware_is_valid_correlation_id_various():
    """Test is_valid_correlation_id across valid and invalid inputs."""
    middleware = CorrelationIDMiddleware()

    assert middleware.is_valid_correlation_id("abcDEF_123-xyz") is True  # valid chars, length > 10
    assert middleware.is_valid_correlation_id("abcdefghij") is True  # exactly 10 characters
    assert middleware.is_valid_correlation_id("short") is False  # too short
    assert middleware.is_valid_correlation_id("a" * 100) is True  # boundary max length
    assert middleware.is_valid_correlation_id("a" * 101) is False  # too long
    assert middleware.is_valid_correlation_id("invalid id!") is False  # invalid characters
    assert middleware.is_valid_correlation_id(123) is False  # non-string


def test_correlationidmiddleware_after_request_no_correlation_id_sets_nothing(client):
    """Test that when g.correlation_id is missing, no header is added and no trace is stored."""
    resp = client.get("/noci")
    assert resp.status_code == 200
    assert CORRELATION_ID_HEADER not in resp.headers
    assert get_all_traces() == {}


def test_store_trace_and_get_traces_and_cleanup():
    """Test storing traces, retrieving them, and cleaning up old traces beyond 1 hour."""
    now_trace = {
        "timestamp": datetime.now().isoformat(),
        "service": "python-reviewer",
        "method": "GET",
        "path": "/",
        "correlation_id": "cid1",
        "duration_ms": 1.0,
        "status": 200,
    }
    store_trace("cid1", now_trace)
    assert get_traces("cid1") == [now_trace]

    # Insert an old trace older than 1 hour; cleanup should remove it
    old_trace = {
        "timestamp": (datetime.now() - timedelta(hours=2)).isoformat(),
        "service": "python-reviewer",
        "method": "GET",
        "path": "/old",
        "correlation_id": "oldcid",
        "duration_ms": 2.0,
        "status": 200,
    }
    trace_storage["oldcid"] = [old_trace]

    cleanup_old_traces()

    assert "oldcid" not in trace_storage
    assert "cid1" in trace_storage

    # get_all_traces returns copies of lists
    all_traces = get_all_traces()
    assert all_traces["cid1"] is not trace_storage["cid1"]
    # mutating returned list should not affect original
    all_traces["cid1"].append({"dummy": True})
    assert len(all_traces["cid1"]) == 2
    assert len(trace_storage["cid1"]) == 1


def test_cleanup_old_traces_raises_on_bad_timestamp():
    """Test that cleanup_old_traces raises ValueError when encountering malformed timestamps."""
    trace_storage["badcid"] = [{"timestamp": "not-an-iso"}]
    with pytest.raises(ValueError):
        cleanup_old_traces()