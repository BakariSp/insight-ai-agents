"""FastAPI endpoint tests using httpx.AsyncClient."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from tests.test_planner import _sample_blueprint_args


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


# ── Workflow endpoint ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_workflow_generate(client):
    """POST /api/workflow/generate returns a valid Blueprint."""
    from models.blueprint import Blueprint

    mock_bp = Blueprint(**_sample_blueprint_args())

    with patch(
        "api.workflow.generate_blueprint",
        new_callable=AsyncMock,
        return_value=mock_bp,
    ):
        resp = await client.post(
            "/api/workflow/generate",
            json={"userPrompt": "Analyze class performance", "language": "en"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "blueprint" in data
    bp = data["blueprint"]
    assert bp["id"] == "bp-test-planner"
    assert "dataContract" in bp
    assert "computeGraph" in bp
    assert "uiComposition" in bp


@pytest.mark.asyncio
async def test_workflow_generate_missing_prompt(client):
    """POST /api/workflow/generate without userPrompt returns 422."""
    resp = await client.post("/api/workflow/generate", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_workflow_generate_llm_error(client):
    """POST /api/workflow/generate returns 502 when LLM fails."""
    with patch(
        "api.workflow.generate_blueprint",
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM timeout"),
    ):
        resp = await client.post(
            "/api/workflow/generate",
            json={"userPrompt": "Analyze performance"},
        )
    assert resp.status_code == 502
    assert "Blueprint generation failed" in resp.json()["detail"]
