import pytest
from src.app import app, cache, cache_lock


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with cache_lock:
        cache.clear()
    with app.test_client() as client:
        yield client
    with cache_lock:
        cache.clear()


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "healthy"


def test_review_code(client):
    response = client.post(
        "/review",
        json={"content": 'def hello():\n    print("Hello")', "language": "python"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "score" in data
    assert "issues" in data


def test_review_code_uses_thread_safe_cache(client):
    payload = {"content": 'def hello():\n    print("Hello")', "language": "python"}

    first_response = client.post("/review", json=payload)
    second_response = client.post("/review", json=payload)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.get_json()["cached"] is False
    assert second_response.get_json()["cached"] is True


def test_cache_clear_and_stats_use_cache_lock(client):
    client.post("/review", json={"content": "x = 1", "language": "python"})

    stats_response = client.get("/cache/stats")
    assert stats_response.status_code == 200
    assert stats_response.get_json()["total_entries"] == 1

    clear_response = client.post("/cache/clear")
    assert clear_response.status_code == 200
    assert client.get("/cache/stats").get_json()["total_entries"] == 0


def test_review_code_missing_content(client):
    response = client.post("/review", json={})
    assert response.status_code == 400


def test_review_function(client):
    response = client.post("/review/function", json={"function_code": "def test(a, b): return a + b"})
    assert response.status_code == 200
