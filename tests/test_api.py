"""FastAPI endpoint tests using httpx.AsyncClient."""

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_chat_missing_message(client):
    resp = await client.post("/chat", json={})
    assert resp.status_code == 422  # FastAPI validation error


@pytest.mark.asyncio
async def test_list_models(client):
    resp = await client.get("/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "default" in data
    assert "examples" in data
    assert isinstance(data["examples"], list)


@pytest.mark.asyncio
async def test_list_skills(client):
    resp = await client.get("/skills")
    assert resp.status_code == 200
    data = resp.json()
    assert "skills" in data
    assert isinstance(data["skills"], list)
