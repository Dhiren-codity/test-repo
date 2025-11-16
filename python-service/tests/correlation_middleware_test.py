import re
from datetime import datetime, timedelta

import pytest
from flask import Flask, Response
from unittest.mock import Mock, patch

from src.correlation_middleware import (
    CORRELATION_ID_HEADER,
    CorrelationIDMiddleware,
    trace_storage,
    store_trace,
    get_traces,
    get_all_traces,
    cleanup_old_traces,
)


@pytest.fixture(autouse=True)
def clear_trace_store():
    """Ensure trace storage is isolated per test."""
    trace_storage.clear()
    yield
    trace_storage.clear()


@pytest.fixture
def flask_app():
    """Create a Flask application for testing."""
    app = Flask(__name__)
    app.testing = True
    return app


@pytest.fixture
def middleware(flask_app):
    """Initialize middleware with Flask app."""
    m = CorrelationIDMiddleware(flask_app)
    return m


def test_CorrelationIDMiddleware___init___without_app():
    """Middleware can be initialized without an app, deferring init_app."""
    m = CorrelationIDMiddleware()
    assert m.app is None


def test_CorrelationIDMiddleware_init_app_sets_attribute(flask_app):
    """init_app registers hooks and sets app.correlation_start_time to None."""
    m = CorrelationIDMiddleware()
    m.init_app(flask_app)
    assert hasattr(flask_app, "correlation_start_time")
    assert flask_app.correlation_start_time is None


def test_CorrelationIDMiddleware_before_after_valid_header_stores_trace(flask_app, middleware):
    """With a valid incoming header, middleware echoes it back and stores trace with fields."""
    @flask_app.route("/ping")
    def ping():
        return "ok"

    client = flask_app.test_client()
    incoming_id = "valid-abc_12345"
    resp = client.get("/ping", headers={CORRELATION_ID_HEADER: incoming_id})
    assert resp.status_code == 200
    assert resp.headers.get(CORRELATION_ID_HEADER) == incoming_id

    traces = get_traces(incoming_id)
    assert len(traces) == 1
    trace = traces[0]
    assert trace["service"] == "python-reviewer"
    assert trace["method"] == "GET"
    assert trace["path"] == "/ping"
    assert trace["correlation_id"] == incoming_id
    assert isinstance(trace["duration_ms"], float)
    assert trace["status"] == 200
    # timestamp is ISO-8601 parseable
    parsed = datetime.fromisoformat(trace["timestamp"])
    assert isinstance(parsed, datetime)


def test_CorrelationIDMiddleware_before_after_duration_rounding(flask_app, middleware):
    """Request duration is computed and rounded to two decimals."""
    @flask_app.route("/rounding")
    def rounding():
        return "ok"

    client = flask_app.test_client()
    # Ensure no generation is called by supplying a valid header
    incoming_id = "valid-abc_12345"

    with patch("src.correlation_middleware.time.time", side_effect=[1000.0, 1000.123456]):
        resp = client.get("/rounding", headers={CORRELATION_ID_HEADER: incoming_id})
        assert resp.status_code == 200

    traces = get_traces(incoming_id)
    assert len(traces) == 1
    # (1000.123456 - 1000.0) * 1000 = 123.456 -> round(..., 2) = 123.46
    assert traces[0]["duration_ms"] == 123.46


def test_CorrelationIDMiddleware_generates_id_when_header_missing(flask_app, middleware):
    """When no header is provided, middleware generates and sets a new correlation ID."""
    @flask_app.route("/gen")
    def gen():
        return "ok"

    client = flask_app.test_client()
    generated_id = "generated-1234567890"

    with patch("src.correlation_middleware.CorrelationIDMiddleware.generate_correlation_id", return_value=generated_id):
        resp = client.get("/gen")
        assert resp.status_code == 200
        assert resp.headers.get(CORRELATION_ID_HEADER) == generated_id

    traces = get_traces(generated_id)
    assert len(traces) == 1
    assert traces[0]["correlation_id"] == generated_id


def test_CorrelationIDMiddleware_invalid_header_triggers_generation(flask_app, middleware):
    """If the incoming header is invalid, a new correlation ID is generated."""
    @flask_app.route("/invalid")
    def invalid():
        return "ok"

    client = flask_app.test_client()
    invalid_id = "bad id"  # space makes it invalid by regex
    generated_id = "generated-abcdef12345"

    with patch("src.correlation_middleware.CorrelationIDMiddleware.generate_correlation_id", return_value=generated_id):
        resp = client.get("/invalid", headers={CORRELATION_ID_HEADER: invalid_id})
        assert resp.status_code == 200
        assert resp.headers.get(CORRELATION_ID_HEADER) == generated_id

    assert get_traces(invalid_id) == []
    assert len(get_traces(generated_id)) == 1


def test_CorrelationIDMiddleware_is_valid_correlation_id_various():
    """Validate correlation ID rules: type, length, charset."""
    assert CorrelationIDMiddleware.is_valid_correlation_id(123) is False  # non-string
    assert CorrelationIDMiddleware.is_valid_correlation_id("short") is False  # too short (<10)
    assert CorrelationIDMiddleware.is_valid_correlation_id("a" * 101) is False  # too long (>100)
    assert CorrelationIDMiddleware.is_valid_correlation_id("invalid$chars12345") is False  # invalid chars
    assert CorrelationIDMiddleware.is_valid_correlation_id("abc_DEF-1234") is True  # valid


def test_CorrelationIDMiddleware_generate_correlation_id_format_and_validity():
    """Generated correlation ID matches expected pattern and is valid."""
    cid = CorrelationIDMiddleware.generate_correlation_id()
    assert re.match(r"^\d+-py-\d{1,5}$", cid)
    assert CorrelationIDMiddleware.is_valid_correlation_id(cid) is True


def test_CorrelationIDMiddleware_extract_or_generate_uses_existing_when_valid():
    """extract_or_generate_correlation_id returns existing valid header."""
    m = CorrelationIDMiddleware()
    request = type("Req", (), {})()
    request.headers = {CORRELATION_ID_HEADER: "valid-abc_12345"}
    with patch("src.correlation_middleware.CorrelationIDMiddleware.generate_correlation_id", return_value="should-not"):
        result = m.extract_or_generate_correlation_id(request)
    assert result == "valid-abc_12345"


def test_CorrelationIDMiddleware_extract_or_generate_generates_when_invalid_or_missing():
    """extract_or_generate_correlation_id generates new ID when header is invalid or missing."""
    m = CorrelationIDMiddleware()
    generated = "gen-1234567890"

    # Case 1: Invalid (too short)
    request1 = type("Req", (), {})()
    request1.headers = {CORRELATION_ID_HEADER: "short"}
    with patch("src.correlation_middleware.CorrelationIDMiddleware.generate_correlation_id", return_value=generated):
        result1 = m.extract_or_generate_correlation_id(request1)
    assert result1 == generated

    # Case 2: Missing
    request2 = type("Req", (), {})()
    request2.headers = {}
    with patch("src.correlation_middleware.CorrelationIDMiddleware.generate_correlation_id", return_value=generated):
        result2 = m.extract_or_generate_correlation_id(request2)
    assert result2 == generated


def test_CorrelationIDMiddleware_after_request_without_correlation_id_noop(flask_app):
    """after_request is a no-op when no correlation ID is present in g."""
    m = CorrelationIDMiddleware()  # not registered to app hooks

    with flask_app.test_request_context("/noop", method="GET"):
        resp = Response("ok", status=204)
        result = m.after_request(resp)
        assert result is resp
        assert CORRELATION_ID_HEADER not in result.headers
        assert get_all_traces() == {}


def test_store_get_traces_and_get_all_return_copies():
    """get_traces and get_all_traces return copies so mutations don't affect storage."""
    cid = "copy-test-12345"
    trace1 = {"timestamp": datetime.now().isoformat(), "path": "/a", "method": "GET", "status": 200}
    trace2 = {"timestamp": datetime.now().isoformat(), "path": "/b", "method": "POST", "status": 201}
    store_trace(cid, trace1)
    store_trace(cid, trace2)

    # get_traces returns a copy of the list
    traces_copy = get_traces(cid)
    assert traces_copy == [trace1, trace2]
    traces_copy.append({"fake": True})

    # Underlying storage unchanged
    assert get_traces(cid) == [trace1, trace2]

    # get_all_traces returns a dict with copied lists
    all_copy = get_all_traces()
    assert cid in all_copy
    all_copy[cid].clear()
    # Underlying storage still intact
    assert len(get_traces(cid)) == 2


def test_cleanup_old_traces_removes_entries_older_than_one_hour():
    """cleanup_old_traces removes correlation IDs whose oldest trace is older than 1 hour."""
    now = datetime.now()
    old_ts = (now - timedelta(hours=2)).isoformat()
    new_ts = now.isoformat()

    trace_storage["oldcid"] = [
        {"timestamp": old_ts, "path": "/old", "method": "GET", "status": 200},
        {"timestamp": new_ts, "path": "/new", "method": "GET", "status": 200},
    ]
    trace_storage["newcid"] = [
        {"timestamp": new_ts, "path": "/latest", "method": "GET", "status": 200},
    ]

    cleanup_old_traces()
    assert "oldcid" not in trace_storage
    assert "newcid" in trace_storage
    assert len(trace_storage["newcid"]) == 1