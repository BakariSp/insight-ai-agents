"""Tests for Patch models — camelCase serialization and enum values."""

import pytest

from models.patch import (
    PatchType,
    RefineScope,
    PatchInstruction,
    PatchPlan,
)


# ── Enum tests ────────────────────────────────────────────────


def test_patch_type_values():
    """PatchType enum has expected values."""
    assert PatchType.UPDATE_PROPS.value == "update_props"
    assert PatchType.REORDER.value == "reorder"
    assert PatchType.ADD_BLOCK.value == "add_block"
    assert PatchType.REMOVE_BLOCK.value == "remove_block"
    assert PatchType.RECOMPOSE.value == "recompose"


def test_refine_scope_values():
    """RefineScope enum has expected values."""
    assert RefineScope.PATCH_LAYOUT.value == "patch_layout"
    assert RefineScope.PATCH_COMPOSE.value == "patch_compose"
    assert RefineScope.FULL_REBUILD.value == "full_rebuild"


# ── PatchInstruction tests ────────────────────────────────────


def test_patch_instruction_camel_case():
    """PatchInstruction serializes to camelCase."""
    instruction = PatchInstruction(
        type=PatchType.UPDATE_PROPS,
        target_block_id="block-123",
        changes={"color": "blue"},
    )

    data = instruction.model_dump(by_alias=True)

    assert "targetBlockId" in data
    assert data["targetBlockId"] == "block-123"
    assert data["type"] == "update_props"


def test_patch_instruction_default_changes():
    """PatchInstruction.changes defaults to empty dict."""
    instruction = PatchInstruction(
        type=PatchType.REMOVE_BLOCK,
        target_block_id="block-456",
    )

    assert instruction.changes == {}


def test_patch_instruction_from_dict():
    """PatchInstruction can be created from camelCase dict."""
    data = {
        "type": "recompose",
        "targetBlockId": "insight-1",
        "changes": {"instruction": "Make it shorter"},
    }

    instruction = PatchInstruction.model_validate(data)

    assert instruction.type == PatchType.RECOMPOSE
    assert instruction.target_block_id == "insight-1"
    assert instruction.changes["instruction"] == "Make it shorter"


# ── PatchPlan tests ───────────────────────────────────────────


def test_patch_plan_camel_case():
    """PatchPlan serializes to camelCase."""
    plan = PatchPlan(
        scope=RefineScope.PATCH_LAYOUT,
        instructions=[
            PatchInstruction(
                type=PatchType.UPDATE_PROPS,
                target_block_id="kpi-1",
                changes={"title": "New Title"},
            ),
        ],
        affected_block_ids=["kpi-1"],
    )

    data = plan.model_dump(by_alias=True)

    assert data["scope"] == "patch_layout"
    assert "affectedBlockIds" in data
    assert data["affectedBlockIds"] == ["kpi-1"]
    assert len(data["instructions"]) == 1
    assert data["instructions"][0]["targetBlockId"] == "kpi-1"


def test_patch_plan_compose_instruction():
    """PatchPlan can include compose_instruction for AI guidance."""
    plan = PatchPlan(
        scope=RefineScope.PATCH_COMPOSE,
        instructions=[
            PatchInstruction(
                type=PatchType.RECOMPOSE,
                target_block_id="insight-1",
                changes={"instruction": "Make it shorter"},
            ),
        ],
        affected_block_ids=["insight-1"],
        compose_instruction="Shorten the analysis to under 100 words",
    )

    data = plan.model_dump(by_alias=True)

    assert "composeInstruction" in data
    assert data["composeInstruction"] == "Shorten the analysis to under 100 words"


def test_patch_plan_defaults():
    """PatchPlan has sensible defaults."""
    plan = PatchPlan(scope=RefineScope.FULL_REBUILD)

    assert plan.instructions == []
    assert plan.affected_block_ids == []
    assert plan.compose_instruction is None


def test_patch_plan_from_dict():
    """PatchPlan can be created from camelCase dict."""
    data = {
        "scope": "patch_compose",
        "instructions": [
            {
                "type": "recompose",
                "targetBlockId": "md-1",
                "changes": {},
            }
        ],
        "affectedBlockIds": ["md-1"],
        "composeInstruction": "Be more concise",
    }

    plan = PatchPlan.model_validate(data)

    assert plan.scope == RefineScope.PATCH_COMPOSE
    assert len(plan.instructions) == 1
    assert plan.instructions[0].target_block_id == "md-1"
    assert plan.compose_instruction == "Be more concise"


def test_patch_plan_multiple_instructions():
    """PatchPlan can hold multiple instructions."""
    plan = PatchPlan(
        scope=RefineScope.PATCH_LAYOUT,
        instructions=[
            PatchInstruction(
                type=PatchType.UPDATE_PROPS,
                target_block_id="chart-1",
                changes={"color": "blue"},
            ),
            PatchInstruction(
                type=PatchType.UPDATE_PROPS,
                target_block_id="chart-2",
                changes={"color": "green"},
            ),
        ],
        affected_block_ids=["chart-1", "chart-2"],
    )

    assert len(plan.instructions) == 2
    assert len(plan.affected_block_ids) == 2
