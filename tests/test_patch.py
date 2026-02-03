"""Tests for Patch mechanism — PatchAgent and Executor.execute_patch()."""

from unittest.mock import AsyncMock, patch

import pytest

from agents.executor import (
    ExecutorAgent,
    _apply_prop_patch,
    _find_slot,
    _find_block_by_id,
)
from agents.patch_agent import (
    analyze_refine,
    _analyze_layout_patch,
    _analyze_compose_patch,
)
from models.blueprint import Blueprint
from models.patch import PatchInstruction, PatchPlan, PatchType, RefineScope
from tests.test_planner import _sample_blueprint_args


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


# ── PatchAgent tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_refine_full_rebuild_returns_empty_plan():
    """Full rebuild scope returns empty PatchPlan."""
    bp = _make_blueprint()

    plan = await analyze_refine(
        message="Add a new section",
        blueprint=bp,
        page=None,
        refine_scope="full_rebuild",
    )

    assert plan.scope == RefineScope.FULL_REBUILD
    assert plan.instructions == []


@pytest.mark.asyncio
async def test_analyze_refine_none_scope_defaults_to_full_rebuild():
    """None scope defaults to FULL_REBUILD."""
    bp = _make_blueprint()

    plan = await analyze_refine(
        message="Some request",
        blueprint=bp,
        page=None,
        refine_scope=None,
    )

    assert plan.scope == RefineScope.FULL_REBUILD


@pytest.mark.asyncio
async def test_analyze_refine_patch_layout():
    """Layout patch returns correct scope."""
    bp = _make_blueprint()

    plan = await analyze_refine(
        message="把图表颜色换成蓝色",
        blueprint=bp,
        page=None,
        refine_scope="patch_layout",
    )

    assert plan.scope == RefineScope.PATCH_LAYOUT


@pytest.mark.asyncio
async def test_analyze_refine_patch_compose():
    """Compose patch targets ai_content_slot blocks."""
    bp = _make_blueprint()

    plan = await analyze_refine(
        message="缩短分析内容",
        blueprint=bp,
        page=None,
        refine_scope="patch_compose",
    )

    assert plan.scope == RefineScope.PATCH_COMPOSE
    assert len(plan.instructions) == 1  # One markdown ai_content_slot
    assert plan.instructions[0].type == PatchType.RECOMPOSE
    assert plan.instructions[0].target_block_id == "insight"
    assert plan.compose_instruction == "缩短分析内容"


def test_analyze_layout_patch_color_detection():
    """_analyze_layout_patch detects color change requests."""
    # Create blueprint with a chart
    bp_args = _sample_blueprint_args()
    bp_args["ui_composition"]["tabs"][0]["slots"].append({
        "id": "chart-1",
        "component_type": "chart",
        "data_binding": "$compute.scoreStats",
        "props": {"variant": "bar"},
    })
    bp = Blueprint(**bp_args)

    plan = _analyze_layout_patch("把颜色换成蓝色", bp, None)

    assert plan.scope == RefineScope.PATCH_LAYOUT
    assert len(plan.instructions) == 1
    assert plan.instructions[0].type == PatchType.UPDATE_PROPS
    assert plan.instructions[0].target_block_id == "chart-1"
    assert plan.instructions[0].changes.get("color") == "蓝色"


def test_analyze_layout_patch_english_color():
    """_analyze_layout_patch detects English color change."""
    bp_args = _sample_blueprint_args()
    bp_args["ui_composition"]["tabs"][0]["slots"].append({
        "id": "chart-1",
        "component_type": "chart",
        "props": {},
    })
    bp = Blueprint(**bp_args)

    plan = _analyze_layout_patch("change color to blue", bp, None)

    assert len(plan.instructions) == 1
    assert plan.instructions[0].changes.get("color") == "blue"


def test_analyze_compose_patch_finds_all_ai_slots():
    """_analyze_compose_patch targets all ai_content_slot blocks."""
    bp_args = _sample_blueprint_args()
    # Add a second AI slot
    bp_args["ui_composition"]["tabs"][0]["slots"].append({
        "id": "suggestions-1",
        "component_type": "suggestion_list",
        "ai_content_slot": True,
        "props": {},
    })
    bp = Blueprint(**bp_args)

    plan = _analyze_compose_patch("Make it shorter", bp, None)

    assert plan.scope == RefineScope.PATCH_COMPOSE
    assert len(plan.instructions) == 2
    assert set(plan.affected_block_ids) == {"insight", "suggestions-1"}


# ── Executor execute_patch tests ──────────────────────────────


@pytest.mark.asyncio
async def test_patch_layout_skips_ai():
    """PATCH_LAYOUT applies changes without LLM calls."""
    bp = _make_blueprint()
    page = _make_sample_page()
    executor = ExecutorAgent()

    plan = PatchPlan(
        scope=RefineScope.PATCH_LAYOUT,
        instructions=[],
        affected_block_ids=[],
    )

    events = []
    async for event in executor.execute_patch(page, bp, plan):
        events.append(event)

    # No BLOCK events (no AI)
    assert not any(e["type"] == "BLOCK_START" for e in events)

    # Should complete successfully
    complete = events[-1]
    assert complete["type"] == "COMPLETE"
    assert complete["message"] == "completed"


@pytest.mark.asyncio
async def test_patch_layout_applies_changes():
    """PATCH_LAYOUT actually modifies page properties."""
    bp = _make_blueprint()
    page = _make_sample_page()
    executor = ExecutorAgent()

    plan = PatchPlan(
        scope=RefineScope.PATCH_LAYOUT,
        instructions=[
            PatchInstruction(
                type=PatchType.UPDATE_PROPS,
                target_block_id="kpi",  # First slot in sample blueprint
                changes={"color": "blue"},
            ),
        ],
        affected_block_ids=["kpi"],
    )

    events = []
    async for event in executor.execute_patch(page, bp, plan):
        events.append(event)

    complete = events[-1]
    result_page = complete["result"]["page"]
    # The block should have the new color
    assert result_page["tabs"][0]["blocks"][0].get("color") == "blue"


@pytest.mark.asyncio
async def test_patch_compose_regenerates_ai_only():
    """PATCH_COMPOSE regenerates only ai_content_slot blocks."""
    bp = _make_blueprint()
    page = _make_sample_page()
    executor = ExecutorAgent()

    plan = PatchPlan(
        scope=RefineScope.PATCH_COMPOSE,
        instructions=[
            PatchInstruction(
                type=PatchType.RECOMPOSE,
                target_block_id="insight",
                changes={"instruction": "Make it shorter"},
            ),
        ],
        affected_block_ids=["insight"],
        compose_instruction="Make it shorter",
    )

    with patch.object(
        ExecutorAgent,
        "_generate_block_content",
        new_callable=AsyncMock,
        return_value="Shorter AI text",
    ):
        events = []
        async for event in executor.execute_patch(page, bp, plan):
            events.append(event)

    # Should have BLOCK events
    assert any(e["type"] == "BLOCK_START" for e in events)
    assert any(e["type"] == "SLOT_DELTA" for e in events)
    assert any(e["type"] == "BLOCK_COMPLETE" for e in events)

    complete = events[-1]
    assert complete["message"] == "completed"


@pytest.mark.asyncio
async def test_patch_compose_preserves_data_blocks():
    """PATCH_COMPOSE doesn't modify non-AI blocks."""
    bp = _make_blueprint()
    page = _make_sample_page()
    original_kpi = page["tabs"][0]["blocks"][0].copy()
    executor = ExecutorAgent()

    plan = PatchPlan(
        scope=RefineScope.PATCH_COMPOSE,
        instructions=[
            PatchInstruction(
                type=PatchType.RECOMPOSE,
                target_block_id="insight",
                changes={},
            ),
        ],
        affected_block_ids=["insight"],
    )

    with patch.object(
        ExecutorAgent,
        "_generate_block_content",
        new_callable=AsyncMock,
        return_value="New AI text",
    ):
        events = []
        async for event in executor.execute_patch(page, bp, plan):
            events.append(event)

    # KPI block should be unchanged
    complete = events[-1]
    result_page = complete["result"]["page"]
    assert result_page["tabs"][0]["blocks"][0] == original_kpi


@pytest.mark.asyncio
async def test_execute_patch_emits_block_events():
    """execute_patch emits proper BLOCK event sequence."""
    bp = _make_blueprint()
    page = _make_sample_page()
    executor = ExecutorAgent()

    plan = PatchPlan(
        scope=RefineScope.PATCH_COMPOSE,
        instructions=[
            PatchInstruction(
                type=PatchType.RECOMPOSE,
                target_block_id="insight",
                changes={},
            ),
        ],
        affected_block_ids=["insight"],
    )

    with patch.object(
        ExecutorAgent,
        "_generate_block_content",
        new_callable=AsyncMock,
        return_value="Patched content",
    ):
        events = []
        async for event in executor.execute_patch(page, bp, plan):
            events.append(event)

    block_events = [
        e for e in events
        if e["type"] in ("BLOCK_START", "SLOT_DELTA", "BLOCK_COMPLETE")
    ]

    assert len(block_events) == 3
    assert block_events[0]["type"] == "BLOCK_START"
    assert block_events[1]["type"] == "SLOT_DELTA"
    assert block_events[2]["type"] == "BLOCK_COMPLETE"


@pytest.mark.asyncio
async def test_execute_patch_full_rebuild_returns_error():
    """execute_patch with FULL_REBUILD returns error."""
    bp = _make_blueprint()
    page = _make_sample_page()
    executor = ExecutorAgent()

    plan = PatchPlan(scope=RefineScope.FULL_REBUILD)

    events = []
    async for event in executor.execute_patch(page, bp, plan):
        events.append(event)

    complete = events[-1]
    assert complete["type"] == "COMPLETE"
    assert complete["message"] == "error"
    assert "Full rebuild required" in complete["result"]["chatResponse"]


# ── Helper function tests ─────────────────────────────────────


def test_apply_prop_patch():
    """_apply_prop_patch modifies block properties."""
    block = {"type": "chart", "color": "red", "title": "Old"}

    _apply_prop_patch(block, {"color": "blue", "title": "New"})

    assert block["color"] == "blue"
    assert block["title"] == "New"


def test_apply_prop_patch_adds_new_props():
    """_apply_prop_patch can add new properties."""
    block = {"type": "chart"}

    _apply_prop_patch(block, {"color": "green"})

    assert block["color"] == "green"


def test_find_slot():
    """_find_slot locates slot by ID."""
    bp = _make_blueprint()

    slot = _find_slot(bp, "insight")
    assert slot is not None
    assert slot.id == "insight"

    missing = _find_slot(bp, "nonexistent")
    assert missing is None


def test_find_block_by_id():
    """_find_block_by_id locates block by slot ID."""
    bp = _make_blueprint()
    page = _make_sample_page()

    # "insight" is the second slot (index 1)
    block = _find_block_by_id(page, bp, "insight")
    assert block is not None
    assert block["type"] == "markdown"

    missing = _find_block_by_id(page, bp, "nonexistent")
    assert missing is None


def test_find_block_by_id_first_slot():
    """_find_block_by_id finds first slot correctly."""
    bp = _make_blueprint()
    page = _make_sample_page()

    # "kpi" is the first slot (index 0)
    block = _find_block_by_id(page, bp, "kpi")
    assert block is not None
    assert block["type"] == "kpi_grid"
