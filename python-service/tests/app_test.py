import sys
import types
import pytest
from unittest.mock import Mock
from flask import jsonify


@pytest.fixture
def app_objects(monkeypatch):
    """Provide imported objects from src.app with a fake CodeReviewer for isolation."""
    # Inject a fake src.code_reviewer module before importing src.app
    fake_mod = types.ModuleType("src.code_reviewer")

    class DummyResult:
        def __init__(self, score=0, issues=None, suggestions=None, complexity_score=0):
            self.score = score
            self.issues = issues or []
            self.suggestions = suggestions or []
            self.complexity_score = complexity_score

    class CodeReviewer:
        def review_code(self, content, language):
            return DummyResult(score=5, issues=[], suggestions=[], complexity_score=1.0)

        def review_function(self, function_code):
            return {"ok": True, "echo": function_code}

    fake_mod.CodeReviewer = CodeReviewer
    sys.modules["src.code_reviewer"] = fake_mod

    # Import the app and utilities under test
    from src.app import app, generate_cache_key, cached, cache, CACHE_TTL, reviewer, health_check  # noqa: E402

    # Ensure a clean cache before and after
    cache.clear()
    yield {
        "app": app,
        "generate_cache_key": generate_cache_key,
        "cached": cached,
        "cache": cache,
        "CACHE_TTL": CACHE_TTL,
        "reviewer": reviewer,
        "health_check": health_check,
    }
    cache.clear()


@pytest.fixture
def client(app_objects):
    """Return a Flask test client."""
    app = app_objects["app"]
    with app.test_client() as c:
        yield c


@pytest.mark.parametrize(
    "prefix,data1,data2",
    [
        ("p1", "abc", "abc"),  # same data
        ("p1", "abc", "def"),  # different data
        ("p2", "abc", "abc"),  # same data different prefix
    ],
)
def test_generate_cache_key_deterministic(app_objects, prefix, data1, data2):
    """generate_cache_key should be deterministic and change with prefix or data."""
    generate_cache_key = app_objects["generate_cache_key"]

    k1 = generate_cache_key(prefix, data1)
    k2 = generate_cache_key(prefix, data1)
    assert k1 == k2

    if data1 != data2:
        k3 = generate_cache_key(prefix, data2)
        assert k1 != k3

    if prefix == "p2":
        # Different prefix from earlier case should yield different key
        k_old = generate_cache_key("p1", data1)
        assert k_old != k1


def test_cached_wrapper_caches_by_content_and_sets_cached_flag(app_objects):
    """cached decorator should cache responses based on request JSON 'content' and set cached flag."""
    app = app_objects["app"]
    cached = app_objects["cached"]

    calls = {"n": 0}

    @cached("unit")
    def my_view():
        calls["n"] += 1
        return jsonify({"count": calls["n"]})

    with app.test_request_context("/unit", method="POST", json={"content": "same"}):
        resp1 = my_view()
        data1 = resp1.get_json()
        assert data1["count"] == 1
        assert data1["cached"] is False

    with app.test_request_context("/unit", method="POST", json={"content": "same"}):
        resp2 = my_view()
        data2 = resp2.get_json()
        assert data2["count"] == 1  # should come from cache, not incremented
        assert data2["cached"] is True

    with app.test_request_context("/unit", method="POST", json={"content": "different"}):
        resp3 = my_view()
        data3 = resp3.get_json()
        assert data3["count"] == 2  # new content -> miss
        assert data3["cached"] is False


def test_cached_wrapper_no_cache_on_error_tuple(app_objects):
    """cached decorator should not cache when the view returns a (response, status) tuple."""
    app = app_objects["app"]
    cached = app_objects["cached"]
    cache = app_objects["cache"]
    generate_cache_key = app_objects["generate_cache_key"]

    @cached("uniterr")
    def error_view():
        return jsonify({"error": "bad"}), 400

    with app.test_request_context("/uniterr", method="POST", json={"content": "oops"}):
        resp = error_view()
        assert isinstance(resp, tuple)
        response, status = resp
        assert status == 400
        assert response.get_json()["error"] == "bad"

    with app.test_request_context("/uniterr", method="POST", json={"content": "oops"}):
        resp = error_view()
        assert isinstance(resp, tuple)
        response, status = resp
        assert status == 400

    # Ensure nothing was cached for this key
    key = generate_cache_key("uniterr", "oops")
    assert key not in cache


def test_health_check_function_response(app_objects):
    """health_check view should return a healthy status JSON."""
    app = app_objects["app"]
    health_check = app_objects["health_check"]

    with app.app_context():
        resp = health_check()
        data = resp.get_json()
        assert data["status"] == "healthy"
        assert data["service"] == "python-reviewer"


def test_review_code_endpoint_success_and_cache(client, app_objects, monkeypatch):
    """POST /review returns structured response and uses caching on repeated content."""
    reviewer = app_objects["reviewer"]
    call_count = {"n": 0}

    class Issue:
        def __init__(self, severity, line, message, suggestion):
            self.severity = severity
            self.line = line
            self.message = message
            self.suggestion = suggestion

    def fake_review_code(content, language):
        call_count["n"] += 1
        result = types.SimpleNamespace()
        result.score = 90
        result.issues = [Issue("low", 1, "msg", "sug")]
        result.suggestions = ["do X"]
        result.complexity_score = 2.5
        return result

    monkeypatch.setattr(reviewer, "review_code", fake_review_code)

    payload = {"content": "print(1)", "language": "python"}
    r1 = client.post("/review", json=payload)
    assert r1.status_code == 200
    d1 = r1.get_json()
    assert d1["score"] == 90
    assert isinstance(d1["issues"], list)
    assert d1["issues"][0]["severity"] == "low"
    assert d1["cached"] is False

    r2 = client.post("/review", json=payload)
    assert r2.status_code == 200
    d2 = r2.get_json()
    assert d2["cached"] is True
    assert call_count["n"] == 1  # underlying review called only once due to cache


def test_review_code_endpoint_missing_content_returns_400_and_no_cache(client, app_objects):
    """POST /review without 'content' should 400 and not be cached."""
    cache = app_objects["cache"]
    cache.clear()

    r1 = client.post("/review", json={"language": "python"})
    assert r1.status_code == 400
    data1 = r1.get_json()
    assert "error" in data1
    assert "cached" not in data1

    r2 = client.post("/review", json={"language": "python"})
    assert r2.status_code == 400
    data2 = r2.get_json()
    assert "cached" not in data2

    assert len(cache) == 0


def test_review_function_endpoint_success(client, app_objects, monkeypatch):
    """POST /review/function returns whatever reviewer.review_function returns."""
    reviewer = app_objects["reviewer"]

    def fake_review_function(function_code):
        return {"ok": True, "received": function_code}

    monkeypatch.setattr(reviewer, "review_function", fake_review_function)

    code = "def f(x):\n    return x*2\n"
    r = client.post("/review/function", json={"function_code": code})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    assert d["received"] == code


def test_clear_cache_endpoint_resets_cache(client, app_objects, monkeypatch):
    """POST /cache/clear should remove all cached entries."""
    reviewer = app_objects["reviewer"]

    def fake_review_code(content, language):
        result = types.SimpleNamespace()
        result.score = 1
        result.issues = []
        result.suggestions = []
        result.complexity_score = 0.1
        return result

    monkeypatch.setattr(reviewer, "review_code", fake_review_code)

    # Prime cache
    payload = {"content": "to-cache", "language": "python"}
    r1 = client.post("/review", json=payload)
    assert r1.get_json()["cached"] is False

    # Assert that a second call is cached
    r2 = client.post("/review", json=payload)
    assert r2.get_json()["cached"] is True

    # Clear cache
    rc = client.post("/cache/clear")
    assert rc.status_code == 200
    assert rc.get_json()["message"] == "Cache cleared successfully"

    # Stats should show zero entries immediately after clearing
    stats = client.get("/cache/stats").get_json()
    assert stats["total_entries"] == 0
    assert stats["active_entries"] == 0
    assert stats["expired_entries"] == 0

    # Next call should be a cache miss again
    r3 = client.post("/review", json=payload)
    assert r3.get_json()["cached"] is False


def test_cache_stats_counts_active_and_expired(client, app_objects, monkeypatch):
    """GET /cache/stats returns correct active and expired counts."""
    cache = app_objects["cache"]
    CACHE_TTL = app_objects["CACHE_TTL"]

    # Fix time to a known value to compute expires_at reliably
    now_holder = {"t": 1000.0}
    monkeypatch.setattr("src.app.time.time", lambda: now_holder["t"])

    cache.clear()
    cache["active"] = {"data": {"v": 1}, "expires_at": now_holder["t"] + CACHE_TTL}
    cache["expired"] = {"data": {"v": 2}, "expires_at": now_holder["t"] - 5}

    stats = client.get("/cache/stats").get_json()
    assert stats["total_entries"] == 2
    assert stats["active_entries"] == 1
    assert stats["expired_entries"] == 1
    assert stats["cache_ttl"] == CACHE_TTL


def test_cached_ttl_expiry_causes_recompute(app_objects, monkeypatch):
    """cached decorator should evict on TTL expiry and recompute on next call."""
    app = app_objects["app"]
    cached = app_objects["cached"]
    CACHE_TTL = app_objects["CACHE_TTL"]

    # Control time
    t = {"val": 1000.0}
    monkeypatch.setattr("src.app.time.time", lambda: t["val"])

    calls = {"n": 0}

    @cached("ttltest")
    def view():
        calls["n"] += 1
        return jsonify({"n": calls["n"]})

    # First call at t0
    with app.test_request_context("/ttl", method="POST", json={"content": "X"}):
        r1 = view().get_json()
        assert r1["n"] == 1
        assert r1["cached"] is False

    # Within TTL (should hit cache)
    t["val"] = 1000.0 + CACHE_TTL - 1
    with app.test_request_context("/ttl", method="POST", json={"content": "X"}):
        r2 = view().get_json()
        assert r2["n"] == 1
        assert r2["cached"] is True

    # After TTL expiry (should recompute)
    t["val"] = 1000.0 + CACHE_TTL + 1
    with app.test_request_context("/ttl", method="POST", json={"content": "X"}):
        r3 = view().get_json()
        assert r3["n"] == 2
        assert r3["cached"] is False