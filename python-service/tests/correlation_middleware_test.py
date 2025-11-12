import pytest
from unittest.mock import Mock, patch
from flask import Flask, g, jsonify

from src.correlation_middleware import CorrelationIDMiddleware


@pytest.fixture
def app():
    """Create a Flask app with the CorrelationIDMiddleware registered and test routes."""
    app = Flask(__name__)
    mw = CorrelationIDMiddleware()
    mw.init_app(app)
    app.mw = mw  # Attach for easy access in tests

    @app.route("/echo")
    def echo():
        return jsonify(
            correlation_id=getattr(g, "correlation_id", None),
            has_start_time=isinstance(getattr(g, "request_start_time", None), (int, float)),
        )

    @app.route("/unset")
    def unset():
        # Explicitly clear the correlation id to simulate absence in after_request.
        g.correlation_id = None
        return jsonify(ok=True)

    @app.route("/hello")
    def hello():
        return jsonify(message="hi")

    return app


@pytest.fixture
def client(app):
    """Provide a Flask test client for requests."""
    return app.test_client()


@pytest.fixture
def middleware_instance():
    """Provide a middleware instance for unit tests that do not require Flask."""
    return CorrelationIDMiddleware()


def test_CorrelationIDMiddleware___init___with_app_registers_handlers():
    """Ensure __init__ with app registers request handlers and sets app attribute."""
    class FakeApp:
        def __init__(self):
            self.before_calls = []
            self.after_calls = []

        def before_request(self, func):
            self.before_calls.append(func)

        def after_request(self, func):
            self.after_calls.append(func)

    fake_app = FakeApp()
    CorrelationIDMiddleware(app=fake_app)

    assert len(fake_app.before_calls) == 1
    assert len(fake_app.after_calls) == 1
    assert hasattr(fake_app, "correlation_start_time")
    assert fake_app.correlation_start_time is None


def test_CorrelationIDMiddleware_init_app_sets_properties_and_hooks():
    """Verify init_app registers before/after hooks and app is mutated appropriately."""
    app = Flask(__name__)
    mw = CorrelationIDMiddleware()
    mw.init_app(app)

    # The presence of correlation_start_time indicates init_app was executed.
    assert hasattr(app, "correlation_start_time")
    assert app.correlation_start_time is None


def test_CorrelationIDMiddleware_before_request_sets_g_and_start_time(client):
    """before_request sets g.correlation_id and g.request_start_time."""
    resp = client.get("/echo")
    assert resp.status_code == 200
    body = resp.get_json()
    assert isinstance(body["correlation_id"], str) and body["correlation_id"]
    assert body["has_start_time"] is True
    assert "X-Correlation-ID" in resp.headers
    assert resp.headers["X-Correlation-ID"] == body["correlation_id"]


def test_CorrelationIDMiddleware_before_request_uses_incoming_valid_header(client):
    """Incoming valid header should be used as the correlation ID."""
    valid_id = "valid_id_12345"
    resp = client.get("/echo", headers={"X-Correlation-ID": valid_id})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["correlation_id"] == valid_id
    assert resp.headers["X-Correlation-ID"] == valid_id


def test_CorrelationIDMiddleware_before_request_invalid_header_generates_new(monkeypatch, app, client):
    """Invalid incoming header must be ignored and a new correlation ID generated."""
    mw = app.mw
    monkeypatch.setattr(mw, "generate_correlation_id", lambda: "GEN-ABCDEF123")  # deterministic
    resp = client.get("/echo", headers={"X-Correlation-ID": "bad value"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["correlation_id"] == "GEN-ABCDEF123"
    assert resp.headers["X-Correlation-ID"] == "GEN-ABCDEF123"


def test_CorrelationIDMiddleware_after_request_sets_header_and_calls_store_trace(client):
    """after_request should set the response header and store a trace with expected fields."""
    with patch("src.correlation_middleware.store_trace") as mock_store, \
         patch("src.correlation_middleware.time.time", side_effect=[1000.0, 1000.1234]):
        incoming_id = "incomingGOODID"
        resp = client.get("/hello", headers={"X-Correlation-ID": incoming_id})
        assert resp.status_code == 200
        assert resp.headers["X-Correlation-ID"] == incoming_id

        # Validate store_trace was called with appropriate trace data
        mock_store.assert_called_once()
        args, kwargs = mock_store.call_args
        corr_id_arg, trace_data_arg = args
        assert corr_id_arg == incoming_id
        assert trace_data_arg["service"] == "python-reviewer"
        assert trace_data_arg["method"] == "GET"
        assert trace_data_arg["path"] == "/hello"
        assert trace_data_arg["correlation_id"] == incoming_id
        assert trace_data_arg["status"] == 200
        # Duration should be approximately 123.4 ms based on patched times
        assert trace_data_arg["duration_ms"] == 123.4
        # Timestamp should be an ISO-formatted string
        from datetime import datetime
        datetime.fromisoformat(trace_data_arg["timestamp"])


def test_CorrelationIDMiddleware_after_request_no_correlation_id_no_header_and_no_trace(client):
    """If correlation_id is not present in g, after_request should not set header or store trace."""
    with patch("src.correlation_middleware.store_trace") as mock_store:
        resp = client.get("/unset")
        assert resp.status_code == 200
        assert "X-Correlation-ID" not in resp.headers
        mock_store.assert_not_called()


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_valid_incoming(middleware_instance):
    """extract_or_generate_correlation_id returns valid incoming header value."""
    class DummyRequest:
        def __init__(self, headers):
            self.headers = headers

    req = DummyRequest({"X-Correlation-ID": "valid_id_ABC_123"})
    result = middleware_instance.extract_or_generate_correlation_id(req)
    assert result == "valid_id_ABC_123"


def test_CorrelationIDMiddleware_extract_or_generate_correlation_id_invalid_incoming(middleware_instance):
    """extract_or_generate_correlation_id generates a new value when incoming is invalid."""
    class DummyRequest:
        def __init__(self, headers):
            self.headers = headers

    with patch.object(middleware_instance, "generate_correlation_id", return_value="GEN-NEW-123456"):
        req = DummyRequest({"X-Correlation-ID": "short"})
        result = middleware_instance.extract_or_generate_correlation_id(req)
        assert result == "GEN-NEW-123456"


def test_CorrelationIDMiddleware_generate_correlation_id_deterministic_with_patched_time():
    """generate_correlation_id format aligns with implementation and is valid with patched time."""
    with patch("src.correlation_middleware.time.time", return_value=1700000000.123456):
        cid = CorrelationIDMiddleware.generate_correlation_id()
    # Based on the implementation: f"{int(t)}-py-{int(t*1000000) % 100000}"
    assert cid == "1700000000-py-23456"
    # Ensure it's considered valid by the validator
    assert CorrelationIDMiddleware.is_valid_correlation_id(cid)


def test_CorrelationIDMiddleware_is_valid_correlation_id_various_cases():
    """Validate edge cases for is_valid_correlation_id."""
    assert CorrelationIDMiddleware.is_valid_correlation_id("valid_id-12345")  # length >= 10, allowed chars
    assert not CorrelationIDMiddleware.is_valid_correlation_id(None)  # type: ignore[arg-type]
    assert not CorrelationIDMiddleware.is_valid_correlation_id(123)  # type: ignore[arg-type]
    assert not CorrelationIDMiddleware.is_valid_correlation_id("short_id")  # length < 10
    assert not CorrelationIDMiddleware.is_valid_correlation_id("x" * 101)  # length > 100
    assert not CorrelationIDMiddleware.is_valid_correlation_id("bad value")  # space invalid
    assert not CorrelationIDMiddleware.is_valid_correlation_id("slash/not_allowed")  # slash invalid