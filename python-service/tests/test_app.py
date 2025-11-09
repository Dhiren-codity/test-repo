import pytest
from src.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


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


def test_review_code_missing_content(client):
    response = client.post("/review", json={})
    assert response.status_code == 400


def test_review_function(client):
    response = client.post(
        "/review/function", json={"function_code": "def test(a, b): return a + b"}
    )
    assert response.status_code == 200
