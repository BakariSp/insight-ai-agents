"""End-to-end tests — full pipeline from Blueprint to SSE page events.

These tests verify:
1. Blueprint -> ExecutorAgent -> SSE events (using real mock tools, mocked LLM)
2. SSE event format matches sse-protocol.md (Phase 6 BLOCK events)
3. Page content correctness: KPIs from tool calcs, AI text from LLM
4. Java backend degradation: 500/timeout -> mock fallback -> pipeline works
"""

import json
from unittest.mock import AsyncMock, patch, MagicMock

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
        "_generate_block_content",
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

    # Must have BLOCK events for AI content (Phase 6.2)
    block_starts = [e for e in events if e["type"] == "BLOCK_START"]
    assert len(block_starts) == 1
    assert block_starts[0]["blockId"] == "insight"
    assert block_starts[0]["componentType"] == "markdown"

    slot_deltas = [e for e in events if e["type"] == "SLOT_DELTA"]
    assert len(slot_deltas) == 1
    assert slot_deltas[0]["deltaText"] == ai_text

    block_completes = [e for e in events if e["type"] == "BLOCK_COMPLETE"]
    assert len(block_completes) == 1

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
        "_generate_block_content",
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
    # Mock data scores: [58, 85, 72, 91, 65] -> mean=74.2, count=5
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
    """Verify all SSE events match the sse-protocol.md format (Phase 6.2)."""
    bp = Blueprint(**_sample_blueprint_args())
    executor = ExecutorAgent()

    with patch.object(
        ExecutorAgent,
        "_generate_block_content",
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

        elif event["type"] == "BLOCK_START":
            assert "blockId" in event
            assert "componentType" in event
            assert isinstance(event["blockId"], str)
            assert isinstance(event["componentType"], str)

        elif event["type"] == "SLOT_DELTA":
            assert "blockId" in event
            assert "slotKey" in event
            assert "deltaText" in event
            assert isinstance(event["deltaText"], str)

        elif event["type"] == "BLOCK_COMPLETE":
            assert "blockId" in event
            assert isinstance(event["blockId"], str)

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

    # Verify BLOCK event ordering: BLOCK_START before SLOT_DELTA before BLOCK_COMPLETE
    block_events = [e for e in events if e["type"] in ("BLOCK_START", "SLOT_DELTA", "BLOCK_COMPLETE")]
    assert len(block_events) >= 3  # at least one full block cycle
    # Find first block cycle
    assert block_events[0]["type"] == "BLOCK_START"
    assert block_events[1]["type"] == "SLOT_DELTA"
    assert block_events[2]["type"] == "BLOCK_COMPLETE"


# ── E2E: HTTP SSE endpoint ──────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_http_sse_stream(client):
    """Full HTTP test: POST /api/page/generate returns valid SSE stream."""

    ai_text = "HTTP test insight."

    with patch.object(
        ExecutorAgent,
        "_generate_block_content",
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

    # Must have PHASE, TOOL_CALL, TOOL_RESULT, BLOCK events, COMPLETE
    types = {e["type"] for e in events}
    assert "PHASE" in types
    assert "TOOL_CALL" in types
    assert "TOOL_RESULT" in types
    assert "BLOCK_START" in types
    assert "SLOT_DELTA" in types
    assert "BLOCK_COMPLETE" in types
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


# ── E2E: Java backend degradation ─────────────────────────


@pytest.mark.asyncio
async def test_e2e_java_backend_500_falls_back_to_mock():
    """When Java backend returns 500, tools fallback to mock and pipeline completes."""

    # Simulate USE_MOCK_DATA=False but backend raises (as it does with 500/timeout)
    # The tools catch all exceptions and fallback to mock data transparently.
    bp = Blueprint(**_sample_blueprint_args())
    executor = ExecutorAgent()

    ai_text = "Degradation test — data from mock."

    with patch("tools.data_tools._should_use_mock", return_value=False), \
         patch("tools.data_tools._get_client", side_effect=RuntimeError("Java 500")), \
         patch.object(
             ExecutorAgent,
             "_generate_block_content",
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

    types = [e["type"] for e in events]

    # Pipeline must complete successfully despite backend failure
    assert types[-1] == "COMPLETE"
    complete = events[-1]
    assert complete["message"] == "completed"
    assert complete["progress"] == 100

    # Page must contain valid data from mock fallback
    page = complete["result"]["page"]
    assert page is not None
    kpi_block = page["tabs"][0]["blocks"][0]
    assert kpi_block["type"] == "kpi_grid"
    kpi_values = {item["label"]: item["value"] for item in kpi_block["data"]}
    # Mock scores [58, 85, 72, 91, 65] -> mean=74.2
    assert kpi_values["Average"] == "74.2"


@pytest.mark.asyncio
async def test_e2e_java_timeout_falls_back_to_mock(client):
    """HTTP SSE: Java timeout -> tools fallback to mock -> SSE stream completes."""

    ai_text = "Timeout degradation."

    with patch("tools.data_tools._should_use_mock", return_value=False), \
         patch("tools.data_tools._get_client", side_effect=RuntimeError("connect timeout")), \
         patch.object(
             ExecutorAgent,
             "_generate_block_content",
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
    events = _parse_sse_events(resp.text)

    # Stream must include full event sequence
    types = {e["type"] for e in events}
    assert "PHASE" in types
    assert "TOOL_CALL" in types
    assert "TOOL_RESULT" in types
    assert "COMPLETE" in types

    # COMPLETE with valid page (not error)
    complete_events = [e for e in events if e["type"] == "COMPLETE"]
    assert len(complete_events) == 1
    assert complete_events[0]["message"] == "completed"
    assert complete_events[0]["result"]["page"] is not None
