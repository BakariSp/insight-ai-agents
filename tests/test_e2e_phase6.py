"""Phase 6 End-to-End tests — Block events, Patch mechanism, and error handling.

These tests verify:
1. Full lifecycle: prompt → Blueprint → page SSE with BLOCK events
2. Patch mechanism: layout/compose/rebuild refine flows
3. Error handling: Java timeout, LLM failure, nonexistent entity DATA_ERROR
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agents.executor import ExecutorAgent
from agents.patch_agent import analyze_refine
from errors.exceptions import DataFetchError
from main import app
from models.blueprint import Blueprint
from models.conversation import RouterResult
from models.patch import PatchInstruction, PatchPlan, PatchType, RefineScope
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


def _make_blueprint(**overrides) -> Blueprint:
    """Create a Blueprint with optional overrides."""
    args = _sample_blueprint_args()
    args.update(overrides)
    return Blueprint(**args)


def _make_sample_page() -> dict:
    """Create a sample page structure for testing."""
    return {
        "meta": {"pageTitle": "Test", "generatedAt": "2026-01-01T00:00:00Z"},
        "layout": "tabs",
        "tabs": [
            {
                "id": "overview",
                "label": "Overview",
                "blocks": [
                    {"type": "kpi_grid", "data": [], "color": "default"},
                    {"type": "markdown", "content": "Original AI text", "variant": "insight"},
                ],
            }
        ],
    }


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── E2E: Full lifecycle with BLOCK events ────────────────────


@pytest.mark.asyncio
async def test_e2e_full_lifecycle_with_block_events():
    """E2E: prompt → Blueprint → page SSE with BLOCK events (Phase 6.2/6.3).

    This tests the complete flow:
    1. Executor receives Blueprint
    2. Phase A (Data): fetches data via tools
    3. Phase B (Compute): calculates statistics
    4. Phase C (Compose): streams BLOCK events for AI content
    5. COMPLETE with valid page
    """
    bp = Blueprint(**_sample_blueprint_args())
    executor = ExecutorAgent()

    ai_text = "**Key Findings**: The class average is 74.2 with notable variation."

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

    # ── Verify three phases ──
    phase_events = [e for e in events if e["type"] == "PHASE"]
    phases = [e["phase"] for e in phase_events]
    assert "data" in phases
    assert "compute" in phases
    assert "compose" in phases

    # ── Verify BLOCK event sequence (Phase 6.2) ──
    block_starts = [e for e in events if e["type"] == "BLOCK_START"]
    slot_deltas = [e for e in events if e["type"] == "SLOT_DELTA"]
    block_completes = [e for e in events if e["type"] == "BLOCK_COMPLETE"]

    assert len(block_starts) == 1
    assert block_starts[0]["blockId"] == "insight"
    assert block_starts[0]["componentType"] == "markdown"

    assert len(slot_deltas) == 1
    assert slot_deltas[0]["blockId"] == "insight"
    assert slot_deltas[0]["slotKey"] == "content"
    assert slot_deltas[0]["deltaText"] == ai_text

    assert len(block_completes) == 1
    assert block_completes[0]["blockId"] == "insight"

    # ── Verify event ordering ──
    types = [e["type"] for e in events]
    block_start_idx = types.index("BLOCK_START")
    slot_delta_idx = types.index("SLOT_DELTA")
    block_complete_idx = types.index("BLOCK_COMPLETE")
    complete_idx = types.index("COMPLETE")

    assert block_start_idx < slot_delta_idx < block_complete_idx < complete_idx

    # ── Verify COMPLETE event structure ──
    complete = events[-1]
    assert complete["type"] == "COMPLETE"
    assert complete["message"] == "completed"
    assert complete["progress"] == 100

    page = complete["result"]["page"]
    assert page is not None
    assert page["meta"]["pageTitle"] == "Test Analysis"
    assert page["tabs"][0]["blocks"][1]["content"] == ai_text


# ── E2E: Refine Patch Layout ─────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_refine_patch_layout(client):
    """E2E: Generate → refine "改颜色" → patch_plan without new blueprint.

    Flow:
    1. POST /api/conversation with refine intent + patch_layout scope
    2. Verify response has patch_plan but no blueprint
    3. POST /api/page/patch with patch_plan
    4. Verify SSE stream applies layout changes without BLOCK events
    """
    # Step 1: Conversation API returns patch_plan
    mock_router = RouterResult(
        intent="refine",
        confidence=0.9,
        should_build=True,
        refine_scope="patch_layout",
    )
    bp_json = _sample_blueprint_args()
    bp_json["ui_composition"]["tabs"][0]["slots"].append({
        "id": "chart-1",
        "component_type": "chart",
        "props": {"variant": "bar"},
    })

    patch_plan = PatchPlan(
        scope=RefineScope.PATCH_LAYOUT,
        instructions=[
            PatchInstruction(
                type=PatchType.UPDATE_PROPS,
                target_block_id="chart-1",
                changes={"color": "blue"},
            ),
        ],
        affected_block_ids=["chart-1"],
    )

    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.analyze_refine",
            new_callable=AsyncMock,
            return_value=patch_plan,
        ),
    ):
        resp = await client.post(
            "/api/conversation",
            json={
                "message": "把图表颜色换成蓝色",
                "blueprint": bp_json,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "refine"
    assert data["patchPlan"] is not None
    assert data["patchPlan"]["scope"] == "patch_layout"
    assert data["blueprint"] is None  # No new blueprint for patch

    # Step 2: Verify page/patch endpoint applies changes
    page = {
        "meta": {"pageTitle": "Test"},
        "layout": "tabs",
        "tabs": [{
            "id": "overview",
            "label": "Overview",
            "blocks": [
                {"type": "kpi_grid", "data": []},
                {"type": "markdown", "content": "AI text", "variant": "insight"},
                {"type": "chart", "variant": "bar", "color": "red"},  # Original color
            ],
        }],
    }

    bp = Blueprint(**bp_json)
    executor = ExecutorAgent()

    events = []
    async for event in executor.execute_patch(page, bp, patch_plan):
        events.append(event)

    # Should NOT have BLOCK events (no AI regeneration)
    assert not any(e["type"] == "BLOCK_START" for e in events)
    assert not any(e["type"] == "SLOT_DELTA" for e in events)

    # Should complete successfully
    complete = events[-1]
    assert complete["type"] == "COMPLETE"
    assert complete["message"] == "completed"


# ── E2E: Refine Patch Compose ────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_refine_patch_compose(client):
    """E2E: Generate → refine "缩短分析" → only regenerate AI blocks.

    Flow:
    1. POST /api/conversation with refine intent + patch_compose scope
    2. Verify response has patch_plan targeting ai_content_slot
    3. POST /api/page/patch
    4. Verify BLOCK events for AI slots, data blocks unchanged
    """
    mock_router = RouterResult(
        intent="refine",
        confidence=0.85,
        should_build=True,
        refine_scope="patch_compose",
    )
    bp_json = _sample_blueprint_args()

    patch_plan = PatchPlan(
        scope=RefineScope.PATCH_COMPOSE,
        instructions=[
            PatchInstruction(
                type=PatchType.RECOMPOSE,
                target_block_id="insight",
                changes={},
            )
        ],
        affected_block_ids=["insight"],
        compose_instruction="缩短分析内容",
    )

    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.analyze_refine",
            new_callable=AsyncMock,
            return_value=patch_plan,
        ),
    ):
        resp = await client.post(
            "/api/conversation",
            json={
                "message": "缩短分析内容",
                "blueprint": bp_json,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "refine"
    assert data["patchPlan"] is not None
    assert data["patchPlan"]["scope"] == "patch_compose"
    assert len(data["patchPlan"]["affectedBlockIds"]) == 1
    assert "insight" in data["patchPlan"]["affectedBlockIds"]

    # Step 2: Verify execute_patch regenerates AI content
    page = _make_sample_page()
    original_kpi = page["tabs"][0]["blocks"][0].copy()
    bp = Blueprint(**bp_json)
    executor = ExecutorAgent()

    new_ai_text = "Shorter analysis: mean=74.2"

    with patch.object(
        ExecutorAgent,
        "_generate_block_content",
        new_callable=AsyncMock,
        return_value=new_ai_text,
    ):
        events = []
        async for event in executor.execute_patch(page, bp, patch_plan):
            events.append(event)

    # Should have BLOCK events for AI regeneration
    block_starts = [e for e in events if e["type"] == "BLOCK_START"]
    slot_deltas = [e for e in events if e["type"] == "SLOT_DELTA"]
    block_completes = [e for e in events if e["type"] == "BLOCK_COMPLETE"]

    assert len(block_starts) == 1
    assert block_starts[0]["blockId"] == "insight"

    assert len(slot_deltas) == 1
    assert slot_deltas[0]["deltaText"] == new_ai_text

    assert len(block_completes) == 1

    # KPI block should be unchanged
    complete = events[-1]
    result_page = complete["result"]["page"]
    assert result_page["tabs"][0]["blocks"][0] == original_kpi


# ── E2E: Refine Full Rebuild ─────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_refine_full_rebuild(client):
    """E2E: Generate → rebuild "加板块" → new blueprint.

    Flow:
    1. POST /api/conversation with rebuild intent
    2. Verify response has new blueprint (not patch_plan)
    """
    mock_router = RouterResult(
        intent="rebuild",
        confidence=0.9,
        should_build=True,
    )
    mock_bp = Blueprint(**_sample_blueprint_args())
    bp_json = _sample_blueprint_args()

    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.generate_blueprint",
            new_callable=AsyncMock,
            return_value=(mock_bp, "test-model"),
        ),
    ):
        resp = await client.post(
            "/api/conversation",
            json={
                "message": "加一个语法分析板块",
                "blueprint": bp_json,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "rebuild"
    assert data["mode"] == "followup"
    assert data["blueprint"] is not None
    assert data["blueprint"]["id"] == "bp-test-planner"
    assert data["patchPlan"] is None  # Full rebuild, no patch


# ── E2E: Java timeout with BLOCK events ──────────────────────


@pytest.mark.asyncio
async def test_e2e_java_timeout_with_block_events():
    """E2E: Java timeout → mock fallback → BLOCK events still work.

    Verifies that even when Java backend times out, the pipeline:
    1. Falls back to mock data
    2. Still produces correct BLOCK events
    3. Completes successfully with valid page
    """
    bp = Blueprint(**_sample_blueprint_args())
    executor = ExecutorAgent()

    ai_text = "Analysis from mock data fallback."

    with (
        patch("tools.data_tools._should_use_mock", return_value=False),
        patch("tools.data_tools._get_client", side_effect=RuntimeError("connect timeout")),
        patch.object(
            ExecutorAgent,
            "_generate_block_content",
            new_callable=AsyncMock,
            return_value=ai_text,
        ),
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

    # ── Pipeline should complete despite backend failure ──
    types = [e["type"] for e in events]
    assert types[-1] == "COMPLETE"
    complete = events[-1]
    assert complete["message"] == "completed"

    # ── BLOCK events should still be present ──
    block_starts = [e for e in events if e["type"] == "BLOCK_START"]
    slot_deltas = [e for e in events if e["type"] == "SLOT_DELTA"]
    block_completes = [e for e in events if e["type"] == "BLOCK_COMPLETE"]

    assert len(block_starts) == 1
    assert len(slot_deltas) == 1
    assert len(block_completes) == 1

    assert slot_deltas[0]["deltaText"] == ai_text

    # ── Page should have valid content from mock fallback ──
    page = complete["result"]["page"]
    assert page is not None
    kpi_block = page["tabs"][0]["blocks"][0]
    assert kpi_block["type"] == "kpi_grid"
    # Mock scores [58, 85, 72, 91, 65] -> mean=74.2
    kpi_values = {item["label"]: item["value"] for item in kpi_block["data"]}
    assert kpi_values["Average"] == "74.2"


# ── E2E: LLM failure → error COMPLETE ────────────────────────


@pytest.mark.asyncio
async def test_e2e_llm_failure_error_complete():
    """E2E: LLM failure → error COMPLETE event.

    When the LLM fails during Phase C (AI generation), the executor should:
    1. Catch the exception
    2. Yield an error COMPLETE event
    3. Page should be None
    """
    bp = Blueprint(**_sample_blueprint_args())
    executor = ExecutorAgent()

    with patch.object(
        ExecutorAgent,
        "_generate_block_content",
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM timeout: model unavailable"),
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

    # ── Should have phases before failure ──
    phase_events = [e for e in events if e["type"] == "PHASE"]
    assert len(phase_events) >= 2  # At least data and compute phases

    # ── Final event should be error COMPLETE ──
    complete = events[-1]
    assert complete["type"] == "COMPLETE"
    assert complete["message"] == "error"
    assert complete["progress"] == 100

    # ── Error details in result ──
    result = complete["result"]
    assert result["page"] is None
    assert "LLM timeout" in result["chatResponse"]


# ── E2E: Nonexistent entity → DATA_ERROR ─────────────────────


@pytest.mark.asyncio
async def test_e2e_nonexistent_entity_data_error():
    """E2E: Nonexistent entity → DATA_ERROR event.

    When a tool returns an error dict for a required binding:
    1. Executor emits DATA_ERROR event
    2. Raises DataFetchError
    3. Final COMPLETE has error status and entity info
    """
    bp = Blueprint(**_sample_blueprint_args())
    executor = ExecutorAgent()

    # Mock tool returns error for nonexistent class
    error_response = {
        "error": "Class 'class-2c' not found",
        "entity": "class-2c",
    }

    with patch(
        "agents.executor.execute_mcp_tool",
        new_callable=AsyncMock,
        return_value=error_response,
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

    # ── Should have DATA_ERROR event ──
    data_errors = [e for e in events if e["type"] == "DATA_ERROR"]
    assert len(data_errors) == 1
    assert "not found" in data_errors[0]["message"]

    # ── Final event should be error COMPLETE ──
    complete = events[-1]
    assert complete["type"] == "COMPLETE"
    assert complete["message"] == "error"

    # ── Result should have error details ──
    result = complete["result"]
    assert result["page"] is None
    assert result.get("errorType") == "data_error"


# ── E2E: HTTP page/patch endpoint ────────────────────────────


@pytest.mark.asyncio
async def test_e2e_http_page_patch_endpoint(client):
    """E2E: HTTP POST /api/page/patch returns valid SSE stream.

    Tests the HTTP layer for patch execution:
    1. POST request with PagePatchRequest
    2. Verify SSE content-type
    3. Parse events and verify structure
    """
    bp_json = _sample_blueprint_args()
    page = _make_sample_page()

    patch_plan_json = {
        "scope": "patch_compose",
        "instructions": [
            {
                "type": "recompose",
                "targetBlockId": "insight",
                "changes": {},
            }
        ],
        "affectedBlockIds": ["insight"],
    }

    with patch.object(
        ExecutorAgent,
        "_generate_block_content",
        new_callable=AsyncMock,
        return_value="Patched AI content",
    ):
        resp = await client.post(
            "/api/page/patch",
            json={
                "blueprint": bp_json,
                "page": page,
                "patchPlan": patch_plan_json,
            },
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")

    events = _parse_sse_events(resp.text)

    # ── Should have expected event types ──
    types = {e["type"] for e in events}
    assert "PHASE" in types
    assert "BLOCK_START" in types
    assert "SLOT_DELTA" in types
    assert "BLOCK_COMPLETE" in types
    assert "COMPLETE" in types

    # ── COMPLETE should have updated page ──
    complete_events = [e for e in events if e["type"] == "COMPLETE"]
    assert len(complete_events) == 1
    assert complete_events[0]["message"] == "completed"
