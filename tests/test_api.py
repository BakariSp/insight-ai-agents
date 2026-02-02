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
        return_value=(mock_bp, "dashscope/qwen-max"),
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


# ── Page endpoint ────────────────────────────────────────────


def _parse_sse_events(text: str) -> list[dict]:
    """Parse SSE text into a list of event dicts."""
    import json

    events = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload:
                events.append(json.loads(payload))
    return events


@pytest.mark.asyncio
async def test_page_generate_sse(client):
    """POST /api/page/generate returns SSE stream with COMPLETE event."""

    async def mock_stream(blueprint, context):
        yield {"type": "PHASE", "phase": "data", "message": "Fetching data..."}
        yield {"type": "PHASE", "phase": "compose", "message": "Composing..."}
        yield {
            "type": "COMPLETE",
            "message": "completed",
            "progress": 100,
            "result": {
                "response": "Analysis done.",
                "chatResponse": "Analysis done.",
                "page": {
                    "meta": {"pageTitle": "Test", "generatedAt": "2025-01-01"},
                    "layout": "tabs",
                    "tabs": [],
                },
            },
        }

    with patch("api.page._executor") as mock_executor:
        mock_executor.execute_blueprint_stream = mock_stream
        bp_json = _sample_blueprint_args()
        resp = await client.post(
            "/api/page/generate",
            json={"blueprint": bp_json, "teacherId": "t-001"},
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    events = _parse_sse_events(resp.text)
    assert len(events) >= 1
    complete = [e for e in events if e.get("type") == "COMPLETE"]
    assert len(complete) == 1
    assert complete[0]["result"]["page"]["meta"]["pageTitle"] == "Test"


@pytest.mark.asyncio
async def test_page_generate_missing_blueprint(client):
    """POST /api/page/generate without blueprint returns 422."""
    resp = await client.post("/api/page/generate", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_page_generate_error_stream(client):
    """POST /api/page/generate with failing executor returns error COMPLETE."""

    async def mock_error_stream(blueprint, context):
        yield {
            "type": "COMPLETE",
            "message": "error",
            "progress": 100,
            "result": {
                "response": "",
                "chatResponse": "Page generation failed.",
                "page": None,
            },
        }

    with patch("api.page._executor") as mock_executor:
        mock_executor.execute_blueprint_stream = mock_error_stream
        bp_json = _sample_blueprint_args()
        resp = await client.post(
            "/api/page/generate",
            json={"blueprint": bp_json},
        )

    assert resp.status_code == 200  # SSE always returns 200
    events = _parse_sse_events(resp.text)
    complete = [e for e in events if e.get("type") == "COMPLETE"]
    assert len(complete) == 1
    assert complete[0]["message"] == "error"
    assert complete[0]["result"]["page"] is None
