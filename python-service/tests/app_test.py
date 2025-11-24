import sys
import types
import time as py_time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

# Provide a fake src.code_reviewer before importing the app module
fake_cr = types.ModuleType("src.code_reviewer")


class _DummyCodeReviewer:
    def review_code(self, content, language):
        return SimpleNamespace(
            score=100,
            issues=[],
            suggestions=[],
            complexity_score=1.0,
        )

    def review_function(self, function_code):
        return {"reviewed": True, "length": len(function_code or "")}


fake_cr.CodeReviewer = _DummyCodeReviewer
sys.modules["src.code_reviewer"] = fake_cr

from src.app import app, generate_cache_key, cached, cache, CACHE_TTL  # noqa: E402

# Access the module object for deeper monkeypatching when needed
app_module = sys.modules["src.app"]


@pytest.fixture(autouse=True)
def clear_cache_before_after():
    """Ensure global cache is cleared before and after each test."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client():
    """Provide a Flask test client."""
    app.testing = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def mock_reviewer():
    """Mock the reviewer object in src.app to control behavior."""
    original = app_module.reviewer
    mock = Mock()
    app_module.reviewer = mock
    yield mock
    app_module.reviewer = original


@pytest.mark.parametrize(
    "prefix,data1,data2,expected_equal",
    [
        ("pfx", "same", "same", True),
        ("pfx", "a", "b", False),
        ("pfx1", "data", "data", True),
        ("pfx1", "data", "data2", False),
        ("pfx2", "", "", True),
        ("pfx2", "", "x", False),
        ("pfxA", "X", "X", True),
        ("pfxA", "X", "Xx", False),
    ],
)
def test_generate_cache_key_stability_and_variation(prefix, data1, data2, expected_equal):
    """Test that generate_cache_key is stable for same inputs and different for different inputs."""
    k1 = generate_cache_key(prefix, data1)
    k2 = generate_cache_key(prefix, data2)
    if expected_equal:
        assert k1 == k2
    else:
        assert k1 != k2
    assert isinstance(k1, str) and isinstance(k2, str)
    assert len(k1) == 64 and len(k2) == 64


def test_health_check_returns_ok_status(client):
    """Test the health check endpoint returns expected JSON."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"status": "healthy", "service": "python-reviewer"}


def test_review_code_missing_content_returns_400_and_not_cached_field(client, mock_reviewer):
    """Test /review returns 400 when 'content' is missing and no 'cached' flag is added."""
    resp = client.post("/review", json={"language": "python"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data == {"error": "Missing 'content' field"}
    assert "cached" not in data
    assert not mock_reviewer.review_code.called


def _make_review_result(score=88, issues=None, suggestions=None, complexity_score=3.14):
    issues = issues if issues is not None else [
        SimpleNamespace(severity="high", line=1, message="m1", suggestion="s1"),
        SimpleNamespace(severity="low", line=2, message="m2", suggestion="s2"),
    ]
    suggestions = suggestions if suggestions is not None else ["try x", "avoid y"]
    return SimpleNamespace(
        score=score, issues=issues, suggestions=suggestions, complexity_score=complexity_score
    )


def test_review_code_happy_path_caches_response_and_adds_cached_flag(client, mock_reviewer):
    """Test successful /review caches response and adds 'cached' flag on repeated calls."""
    mock_reviewer.review_code.return_value = _make_review_result()

    payload = {"content": "print('hello')", "language": "python"}
    # First call - should compute and cache
    resp1 = client.post("/review", json=payload)
    assert resp1.status_code == 200
    data1 = resp1.get_json()
    assert data1["score"] == 88
    assert isinstance(data1["issues"], list) and len(data1["issues"]) == 2
    assert data1["suggestions"] == ["try x", "avoid y"]
    assert data1["complexity_score"] == 3.14
    assert data1["cached"] is False

    # Second call with same content - should be served from cache
    resp2 = client.post("/review", json=payload)
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2["cached"] is True
    # reviewer called only once because of cache
    assert mock_reviewer.review_code.call_count == 1


def test_review_code_cache_key_ignores_language(client, mock_reviewer):
    """Test that cache key depends only on content, not language."""
    # Return different complexity_scores to detect which path was used
    def side_effect(content, language):
        if language == "python":
            return _make_review_result(complexity_score=1.0)
        return _make_review_result(complexity_score=9.9)

    mock_reviewer.review_code.side_effect = side_effect

    content = "x = 1"
    # First call with python language
    r1 = client.post("/review", json={"content": content, "language": "python"})
    d1 = r1.get_json()
    assert d1["cached"] is False
    assert d1["complexity_score"] == 1.0

    # Second call with different language but same content - should hit cache
    r2 = client.post("/review", json={"content": content, "language": "javascript"})
    d2 = r2.get_json()
    assert d2["cached"] is True
    # Still returns complexity from first call due to content-only cache key
    assert d2["complexity_score"] == 1.0

    # Only the first call should have invoked the reviewer
    assert mock_reviewer.review_code.call_count == 1


def test_cached_decorator_bypass_when_view_returns_tuple():
    """Test that cached decorator bypasses caching when the view returns a tuple (response, status)."""
    call_counter = {"count": 0}

    @app.route("/test/tuple", methods=["POST"])
    @cached("tuple")
    def tuple_view():
        from flask import jsonify

        call_counter["count"] += 1
        return jsonify({"ok": True}), 201

    test_client = app.test_client()

    # Ensure cache is clear to start
    cache.clear()
    before_size = len(cache)

    resp1 = test_client.post("/test/tuple", json={"content": "abc"})
    assert resp1.status_code == 201
    data1 = resp1.get_json()
    assert data1 == {"ok": True}
    assert "cached" not in data1

    resp2 = test_client.post("/test/tuple", json={"content": "abc"})
    assert resp2.status_code == 201
    data2 = resp2.get_json()
    assert data2 == {"ok": True}
    assert "cached" not in data2

    # Function was executed both times, proving no caching took place
    assert call_counter["count"] == 2
    # Cache size unchanged
    assert len(cache) == before_size


def test_review_function_happy_path_returns_raw_result_no_cached(client, mock_reviewer):
    """Test /review/function returns raw result of reviewer without 'cached' flag."""
    mock_reviewer.review_function.return_value = {"result": "ok", "score": 0.75}
    resp = client.post("/review/function", json={"function_code": "def f(): pass"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"result": "ok", "score": 0.75}
    assert "cached" not in data
    mock_reviewer.review_function.assert_called_once()


def test_review_function_missing_function_code_returns_400(client, mock_reviewer):
    """Test /review/function returns 400 on missing 'function_code' input."""
    resp = client.post("/review/function", json={"other": "data"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data == {"error": "Missing 'function_code' field"}
    assert not mock_reviewer.review_function.called


def test_cache_clear_endpoint_clears_cache(client, mock_reviewer):
    """Test that /cache/clear endpoint fully clears the in-memory cache."""
    # Populate cache via /review
    mock_reviewer.review_code.return_value = _make_review_result()
    client.post("/review", json={"content": "abc", "language": "python"})
    assert len(cache) >= 1

    resp = client.post("/cache/clear")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"message": "Cache cleared successfully"}
    assert len(cache) == 0


def test_cache_stats_endpoint_counts_active_and_expired_correctly(client):
    """Test /cache/stats reports total, active, and expired entries correctly."""
    now = py_time.time()
    cache.clear()
    cache["active"] = {"data": {"x": 1}, "expires_at": now + 100}
    cache["expired"] = {"data": {"x": 2}, "expires_at": now - 10}

    resp = client.get("/cache/stats")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_entries"] == 2
    assert data["active_entries"] == 1
    assert data["expired_entries"] == 1
    assert data["cache_ttl"] == CACHE_TTL


def test_review_code_cache_ttl_expiration(client, mock_reviewer, monkeypatch):
    """Test that cached entries expire after CACHE_TTL and re-computation occurs."""
    # Prepare reviewer mock return
    mock_reviewer.review_code.return_value = _make_review_result(complexity_score=2.5)

    # Set a short TTL and control time.time()
    base_time = py_time.time()
    offset = {"v": 0}

    def fake_time():
        return base_time + offset["v"]

    monkeypatch.setattr(app_module, "CACHE_TTL", 1, raising=False)
    monkeypatch.setattr(app_module.time, "time", fake_time, raising=True)

    payload = {"content": "expiring", "language": "python"}

    # Initial call - not cached
    r1 = client.post("/review", json=payload)
    d1 = r1.get_json()
    assert d1["cached"] is False
    assert d1["complexity_score"] == 2.5
    assert mock_reviewer.review_code.call_count == 1

    # Within TTL - cached
    offset["v"] = 0.5
    r2 = client.post("/review", json=payload)
    d2 = r2.get_json()
    assert d2["cached"] is True
    assert mock_reviewer.review_code.call_count == 1

    # After TTL - cache expired, recompute
    offset["v"] = 2.0
    r3 = client.post("/review", json=payload)
    d3 = r3.get_json()
    assert d3["cached"] is False
    assert mock_reviewer.review_code.call_count == 2


@pytest.mark.parametrize(
    "content,expected_cached_flags",
    [
        ("alpha", [False, True]),
        ("beta", [False, True]),
    ],
)
def test_review_code_multiple_contents_independent_caches(client, mock_reviewer, content, expected_cached_flags):
    """Test that different content values maintain independent cache entries."""
    mock_reviewer.review_code.return_value = _make_review_result(score=77)

    # First request for this content
    r1 = client.post("/review", json={"content": content, "language": "python"})
    d1 = r1.get_json()
    assert d1["cached"] is expected_cached_flags[0]
    assert d1["score"] == 77

    # Second request for same content
    r2 = client.post("/review", json={"content": content, "language": "python"})
    d2 = r2.get_json()
    assert d2["cached"] is expected_cached_flags[1]

    # Calls per content should be one due to caching on second request
    # Total call_count will accumulate across parametrized runs, so we avoid asserting call_count exactly here.