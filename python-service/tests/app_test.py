import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

import src.cachekit as cachekit
from src.cachekit import (
    generate_cache_key,
    cached,
    clear_cache as ck_clear_cache,
    cache_stats as ck_cache_stats,
    health_check as ck_health_check,
)
from src.reviews import review_code, review_function
from src.app import app, get_health, post_review_code, post_review_function, get_cache_stats, post_cache_clear


@pytest.fixture(autouse=True)
def clear_all_caches():
    """Clear all caches before and after each test to ensure isolation."""
    ck_clear_cache()
    yield
    ck_clear_cache()


@pytest.fixture
def client():
    """Provide a FastAPI TestClient for endpoint tests."""
    return TestClient(app)


def test_generate_cache_key_stable_across_equivalent_inputs():
    """generate_cache_key should be stable and order-insensitive for dicts/sets."""
    def foo(a, b):
        return a + b

    args1 = ({"a": 1, "b": 2}, [3, 4])
    kwargs1 = {"x": {1, 2}}
    k1 = generate_cache_key(foo, args1, kwargs1, namespace="ns")

    args2 = ({"b": 2, "a": 1}, [3, 4])
    kwargs2 = {"x": {2, 1}}
    k2 = generate_cache_key(foo, args2, kwargs2, namespace="ns")

    assert k1 == k2
    assert k1.startswith("ns:")


@pytest.mark.parametrize(
    "ns1,ns2",
    [
        ("nsA", "nsB"),
        ("alpha", "beta"),
    ],
)
def test_generate_cache_key_namespace_changes_prefix(ns1, ns2):
    """Different namespaces should yield different cache key prefixes."""
    def foo():
        return 1

    k1 = generate_cache_key(foo, tuple(), {}, namespace=ns1)
    k2 = generate_cache_key(foo, tuple(), {}, namespace=ns2)
    assert k1 != k2
    assert k1.startswith(f"{ns1}:")
    assert k2.startswith(f"{ns2}:")


def test_cached_decorator_caches_and_expires(monkeypatch):
    """cached decorator should return cached results and respect TTL expiry."""
    calls = {"n": 0}

    @cached(ttl=1.0, namespace="test_cached_decorator_caches_and_expires")
    def compute(a, b):
        calls["n"] += 1
        return a + b + calls["n"]

    current = {"t": 1000.0}
    monkeypatch.setattr(cachekit.time, "time", lambda: current["t"])

    # First call: miss and compute
    r1 = compute(2, 3)
    assert r1 == 2 + 3 + 1
    info1 = compute.cache_info()
    assert info1["misses"] == 1
    assert info1["hits"] == 0
    assert info1["size"] == 1

    # Second call same args: hit, no recompute
    r2 = compute(2, 3)
    assert r2 == r1
    info2 = compute.cache_info()
    assert info2["misses"] == 1
    assert info2["hits"] == 1
    assert info2["size"] == 1

    # Advance time beyond TTL -> expire and recompute
    current["t"] = 1002.0
    r3 = compute(2, 3)
    assert r3 != r2
    info3 = compute.cache_info()
    # After expiry: another miss recorded
    assert info3["misses"] == 2
    assert info3["hits"] == 1
    assert info3["size"] == 1  # replaced entry


def test_cached_decorator_helpers_and_wrapper_metadata():
    """cached decorator should attach helper methods and preserve metadata."""
    @cached(ttl=60.0, namespace="test_cached_helpers")
    def foo(x):
        """Docstring"""
        return x * 2

    # Validate wrapper metadata
    assert foo.__name__ == "foo"
    assert foo.__doc__ == "Docstring"

    # Populate cache
    assert foo(10) == 20
    info_before = foo.cache_info()
    assert info_before["size"] == 1
    assert info_before["sets"] == 1

    # Clear via helper
    cleared = foo.cache_clear()
    assert cleared == 1
    info_after = foo.cache_info()
    assert info_after["size"] == 0


def test_clear_cache_by_namespace_and_function():
    """clear_cache should clear by namespace, by function, and all."""
    @cached(ttl=60.0, namespace="ns_a")
    def fa(x):
        return x + 1

    @cached(ttl=60.0, namespace="ns_b")
    def fb(x):
        return x + 2

    # Populate both caches
    fa(1)
    fb(2)
    assert fa.cache_info()["size"] == 1
    assert fb.cache_info()["size"] == 1

    # Clear namespace ns_a
    res_ns = ck_clear_cache(namespace="ns_a")
    assert "ns_a" in res_ns and res_ns["ns_a"] == 1
    assert fa.cache_info()["size"] == 0
    assert fb.cache_info()["size"] == 1

    # Clear by function fb
    res_fn = ck_clear_cache(target=fb)
    assert any(k.endswith("fb") for k in res_fn.keys()) or "ns_b" in res_fn
    assert fb.cache_info()["size"] == 0

    # Repopulate and clear all
    fa(3)
    fb(4)
    res_all = ck_clear_cache()
    # Both namespaces should have been cleared (non-zero in dict)
    assert any(v >= 0 for v in res_all.values())
    assert fa.cache_info()["size"] == 0
    assert fb.cache_info()["size"] == 0


def test_cache_stats_and_health_check_structure():
    """cache_stats and health_check should return expected structure and aggregates."""
    @cached(ttl=60.0, namespace="stats_ns")
    def f(x):
        return x

    # Populate
    f(1)
    f(1)
    stats = ck_cache_stats()
    assert "aggregate" in stats and "by_namespace" in stats
    agg = stats["aggregate"]
    assert agg["namespaces"] >= 1
    assert agg["total_size"] >= 0
    assert agg["total_hits"] >= 1  # second call hit
    assert "stats_ns" in stats["by_namespace"]

    health = ck_health_check()
    assert health["status"] == "ok"
    assert isinstance(health["caches"], int)
    assert isinstance(health["timestamp"], int)


def test_review_code_valid_python_counts_and_caching():
    """review_code should parse valid Python and be cached."""
    code = "def f(x):\n    # TODO: improve\n    return x*2\n"

    res1 = review_code(code)
    assert res1["ok"] is True
    assert res1["functions"] == 1
    assert res1["comments"] == 1
    assert res1["todos"] == 1
    assert "classes" in res1 and "imports" in res1

    # Second call should be cached
    res2 = review_code(code)
    assert res2 == res1
    info = review_code.cache_info()
    assert info["misses"] == 1
    assert info["hits"] == 1


def test_review_code_syntax_error():
    """review_code should report syntax errors."""
    bad_code = "def f(:\n    pass\n"
    res = review_code(bad_code)
    assert res["ok"] is False
    assert " at line " in res["error"]


def test_review_function_default_and_named():
    """review_function should extract default first function and by name."""
    code = """
def a(x, y):
    \"\"\"Doc\"\"\"
    if x > 0:
        return x
    else:
        return y

async def b(z: int) -> int:
    for i in range(z):
        pass
    return z
"""

    # Default picks first function a
    res_a = review_function(code)
    assert res_a["ok"] is True
    assert res_a["name"] == "a"
    assert res_a["args"] == ["x", "y"]
    assert res_a["arity"] == 2
    assert res_a["has_docstring"] is True
    assert res_a["has_return_annotation"] is False
    assert res_a["branches"] >= 1
    assert res_a["decorators"] == 0
    assert res_a["is_async"] is False

    # Named picks b
    res_b = review_function(code, "b")
    assert res_b["ok"] is True
    assert res_b["name"] == "b"
    assert res_b["args"] == ["z"]
    assert res_b["arity"] == 1
    assert res_b["has_docstring"] is False
    assert res_b["has_return_annotation"] is True
    assert res_b["branches"] >= 1
    assert res_b["is_async"] is True


@pytest.mark.parametrize(
    "code,name,err",
    [
        ("def a(:\n    pass\n", None, " at line "),
        ("def a(x):\n    return x\n", "missing", "Function not found"),
    ],
)
def test_review_function_error_cases(code, name, err):
    """review_function should handle syntax errors and missing functions."""
    res = review_function(code, name)
    assert res["ok"] is False
    assert err in res["error"]


def test_app_health_endpoint(client):
    """GET /health should return ok status and cache summary."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert isinstance(data["caches"], int)


def test_app_review_code_endpoint_and_caching(client):
    """POST /review/code should analyze code and leverage caching."""
    code = "def f(x):\n    return x\n"
    resp1 = client.post("/review/code", json={"code": code})
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["ok"] is True
    assert data1["functions"] == 1

    resp2 = client.post("/review/code", json={"code": code})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2 == data1


def test_app_review_function_endpoint(client):
    """POST /review/function should analyze a specific function."""
    code = "def g(a, b):\n    return a + b\n"
    resp = client.post("/review/function", json={"code": code, "name": "g"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["name"] == "g"
    assert data["arity"] == 2


def test_app_cache_stats_endpoint(client):
    """GET /cache/stats should return aggregate stats and namespaces."""
    # Trigger some caching
    client.post("/review/code", json={"code": "def x():\n    pass\n"})
    resp = client.get("/cache/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "aggregate" in data
    assert "by_namespace" in data
    assert "review_code" in data["by_namespace"]
    assert "review_function" in data["by_namespace"]


def test_app_cache_clear_endpoint_success_and_not_found(client):
    """POST /cache/clear should clear requested namespace or return 404."""
    # Populate review_code cache
    client.post("/review/code", json={"code": "def y():\n    pass\n"})
    # Clear existing namespace
    resp_ok = client.post("/cache/clear", json={"namespace": "review_code"})
    assert resp_ok.status_code == 200
    data_ok = resp_ok.json()
    assert "cleared" in data_ok
    assert "review_code" in data_ok["cleared"]
    assert data_ok["cleared"]["review_code"] >= 0

    # Try clearing non-existent namespace
    resp_not_found = client.post("/cache/clear", json={"namespace": "no_such_ns"})
    assert resp_not_found.status_code == 404
    assert resp_not_found.json()["detail"] == "No matching caches"