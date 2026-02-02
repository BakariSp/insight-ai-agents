"""End-to-end tests — full pipeline from Blueprint to SSE page events.

These tests verify:
1. Blueprint → ExecutorAgent → SSE events (using real mock tools, mocked LLM)
2. SSE event format matches sse-protocol.md
3. Page content correctness: KPIs from tool calcs, AI text from LLM
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agents.executor import ExecutorAgent
from main import app
from models.blueprint import Blueprint
from tests.test_planner import _sample_blueprint_args


# ── Helpers ──────────────────────────────────────────────────


def _parse_sse_events(text: str) -> list[dict]:
    """Parse SSE event stream into list of event dicts."""
    events = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload:
                events.append(json.loads(payload))
    return events


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── E2E: ExecutorAgent with real tools ───────────────────────


@pytest.mark.asyncio
async def test_e2e_executor_with_real_tools():
    """Full executor pipeline using actual mock data tools + mocked LLM."""
    bp = Blueprint(**_sample_blueprint_args())
    executor = ExecutorAgent()

    ai_text = "**Key Findings**: The class average is 74.2 with a standard deviation of 12.93."

    with patch.object(
        ExecutorAgent,
        "_generate_ai_narrative",
        new_callable=AsyncMock,
        return_value=ai_text,
    ):
        events = []
        async for event in executor.execute_blueprint_stream(
            bp,
            context={
                "teacherId": "t-001",
                "input": {"assignment": "a-001"},
            },
        ):
            events.append(event)

    # ── Verify event sequence ──
    types = [e["type"] for e in events]

    # Must start with PHASE data
    assert types[0] == "PHASE"
    assert events[0]["phase"] == "data"

    # Must have tool calls for data fetching
    tool_calls = [e for e in events if e["type"] == "TOOL_CALL"]
    assert len(tool_calls) >= 1
    assert tool_calls[0]["tool"] == "get_assignment_submissions"

    # Must have tool results
    tool_results = [e for e in events if e["type"] == "TOOL_RESULT"]
    assert len(tool_results) >= 1

    # Must have compute phase
    compute_phases = [e for e in events if e["type"] == "PHASE" and e.get("phase") == "compute"]
    assert len(compute_phases) == 1

    # Must have compute tool calls (calculate_stats)
    compute_tools = [
        e for e in events
        if e["type"] == "TOOL_CALL" and e["tool"] == "calculate_stats"
    ]
    assert len(compute_tools) == 1

    # Must have compose phase
    compose_phases = [e for e in events if e["type"] == "PHASE" and e.get("phase") == "compose"]
    assert len(compose_phases) == 1

    # Must have MESSAGE with AI text
    messages = [e for e in events if e["type"] == "MESSAGE"]
    assert len(messages) == 1
    assert messages[0]["content"] == ai_text

    # Must end with COMPLETE
    assert types[-1] == "COMPLETE"
    complete = events[-1]
    assert complete["message"] == "completed"
    assert complete["progress"] == 100


@pytest.mark.asyncio
async def test_e2e_page_content_from_real_tools():
    """Verify page content uses actual tool-computed data (not hallucinated)."""
    bp = Blueprint(**_sample_blueprint_args())
    executor = ExecutorAgent()

    ai_text = "Analysis complete."

    with patch.object(
        ExecutorAgent,
        "_generate_ai_narrative",
        new_callable=AsyncMock,
        return_value=ai_text,
    ):
        events = []
        async for event in executor.execute_blueprint_stream(
            bp,
            context={
                "teacherId": "t-001",
                "input": {"assignment": "a-001"},
            },
        ):
            events.append(event)

    complete = events[-1]
    page = complete["result"]["page"]

    # Page meta
    assert page["meta"]["pageTitle"] == "Test Analysis"
    assert page["layout"] == "tabs"

    # Tab structure
    assert len(page["tabs"]) == 1
    tab = page["tabs"][0]
    assert tab["id"] == "overview"
    assert tab["label"] == "Overview"

    # KPI block — values should come from calculate_stats on real mock scores
    kpi_block = tab["blocks"][0]
    assert kpi_block["type"] == "kpi_grid"
    kpi_values = {item["label"]: item["value"] for item in kpi_block["data"]}
    # Mock data scores: [58, 85, 72, 91, 65] → mean=74.2, count=5
    # numpy returns floats, so values are like "74.2", "91.0"
    assert kpi_values["Average"] == "74.2"
    assert kpi_values["Total Students"] == "5"
    assert float(kpi_values["Highest Score"]) == 91.0
    assert float(kpi_values["Lowest Score"]) == 58.0

    # Markdown block — should contain AI text
    md_block = tab["blocks"][1]
    assert md_block["type"] == "markdown"
    assert md_block["content"] == ai_text
    assert md_block["variant"] == "insight"


# ── E2E: SSE protocol compliance ────────────────────────────


@pytest.mark.asyncio
async def test_e2e_sse_event_format():
    """Verify all SSE events match the sse-protocol.md format."""
    bp = Blueprint(**_sample_blueprint_args())
    executor = ExecutorAgent()

    with patch.object(
        ExecutorAgent,
        "_generate_ai_narrative",
        new_callable=AsyncMock,
        return_value="Test insight.",
    ):
        events = []
        async for event in executor.execute_blueprint_stream(
            bp,
            context={"teacherId": "t-001", "input": {"assignment": "a-001"}},
        ):
            events.append(event)

    for event in events:
        assert "type" in event, f"Event missing 'type': {event}"

        if event["type"] == "PHASE":
            assert "phase" in event
            assert event["phase"] in ("data", "compute", "compose")
            assert "message" in event

        elif event["type"] == "TOOL_CALL":
            assert "tool" in event
            assert "args" in event

        elif event["type"] == "TOOL_RESULT":
            assert "tool" in event
            assert "status" in event
            assert event["status"] in ("success", "error")

        elif event["type"] == "MESSAGE":
            assert "content" in event
            assert isinstance(event["content"], str)

        elif event["type"] == "COMPLETE":
            assert "message" in event
            assert "progress" in event
            assert "result" in event
            result = event["result"]
            assert "response" in result
            assert "chatResponse" in result
            assert "page" in result
            if result["page"] is not None:
                page = result["page"]
                assert "meta" in page
                assert "pageTitle" in page["meta"]
                assert "layout" in page
                assert "tabs" in page


# ── E2E: HTTP SSE endpoint ──────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_http_sse_stream(client):
    """Full HTTP test: POST /api/page/generate returns valid SSE stream."""

    ai_text = "HTTP test insight."

    with patch.object(
        ExecutorAgent,
        "_generate_ai_narrative",
        new_callable=AsyncMock,
        return_value=ai_text,
    ):
        bp_json = _sample_blueprint_args()
        resp = await client.post(
            "/api/page/generate",
            json={
                "blueprint": bp_json,
                "teacherId": "t-001",
                "context": {
                    "teacherId": "t-001",
                    "input": {"assignment": "a-001"},
                },
            },
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")

    events = _parse_sse_events(resp.text)

    # Must have PHASE, TOOL_CALL, TOOL_RESULT, MESSAGE, COMPLETE
    types = {e["type"] for e in events}
    assert "PHASE" in types
    assert "TOOL_CALL" in types
    assert "TOOL_RESULT" in types
    assert "MESSAGE" in types
    assert "COMPLETE" in types

    # COMPLETE must have page
    complete_events = [e for e in events if e["type"] == "COMPLETE"]
    assert len(complete_events) == 1
    page = complete_events[0]["result"]["page"]
    assert page is not None
    assert page["meta"]["pageTitle"] == "Test Analysis"
    assert page["tabs"][0]["blocks"][0]["type"] == "kpi_grid"


@pytest.mark.asyncio
async def test_e2e_http_sse_tool_failure(client):
    """HTTP SSE returns error COMPLETE when a required tool fails."""

    with patch(
        "agents.executor.execute_mcp_tool",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Java backend timeout"),
    ):
        bp_json = _sample_blueprint_args()
        resp = await client.post(
            "/api/page/generate",
            json={
                "blueprint": bp_json,
                "teacherId": "t-001",
                "context": {
                    "teacherId": "t-001",
                    "input": {"assignment": "a-001"},
                },
            },
        )

    assert resp.status_code == 200  # SSE always 200
    events = _parse_sse_events(resp.text)

    complete = [e for e in events if e["type"] == "COMPLETE"]
    assert len(complete) == 1
    assert complete[0]["message"] == "error"
    assert complete[0]["result"]["page"] is None
