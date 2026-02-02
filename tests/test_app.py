import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_chat_missing_message(client):
    resp = client.post("/chat", json={})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_list_skills(client):
    resp = client.get("/skills")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "skills" in data
    assert isinstance(data["skills"], list)
