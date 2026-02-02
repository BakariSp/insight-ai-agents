"""Tests for PlannerAgent — Blueprint generation with mocked LLM."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.models.test import TestModel

from agents.planner import _planner_agent, generate_blueprint
from models.blueprint import (
    Blueprint,
    CapabilityLevel,
    ComponentType,
    ComputeNodeType,
    DataSourceType,
)


def _sample_blueprint_args() -> dict:
    """Return a valid Blueprint dict suitable for TestModel.custom_output_args."""
    return {
        "id": "bp-test-planner",
        "name": "Test Analysis",
        "description": "A test blueprint from planner",
        "icon": "chart",
        "category": "analytics",
        "capability_level": 1,
        "source_prompt": "Analyze class performance",
        "created_at": "2025-01-01T00:00:00Z",
        "data_contract": {
            "inputs": [
                {"id": "class", "type": "class", "label": "Class", "required": True},
            ],
            "bindings": [
                {
                    "id": "submissions",
                    "source_type": "tool",
                    "tool_name": "get_assignment_submissions",
                    "param_mapping": {
                        "teacher_id": "$context.teacherId",
                        "assignment_id": "$input.assignment",
                    },
                    "description": "Fetch submissions",
                },
            ],
        },
        "compute_graph": {
            "nodes": [
                {
                    "id": "stats",
                    "type": "tool",
                    "tool_name": "calculate_stats",
                    "tool_args": {"data": "$data.submissions.scores"},
                    "depends_on": [],
                    "output_key": "scoreStats",
                },
            ],
        },
        "ui_composition": {
            "layout": "tabs",
            "tabs": [
                {
                    "id": "overview",
                    "label": "Overview",
                    "slots": [
                        {
                            "id": "kpi",
                            "component_type": "kpi_grid",
                            "data_binding": "$compute.scoreStats",
                            "props": {},
                        },
                        {
                            "id": "insight",
                            "component_type": "markdown",
                            "props": {"variant": "insight"},
                            "ai_content_slot": True,
                        },
                    ],
                },
            ],
        },
        "page_system_prompt": "Analyze the scores and provide insights.",
    }


@pytest.mark.asyncio
async def test_generate_blueprint_structure():
    """Test that generate_blueprint returns a valid Blueprint via TestModel."""
    test_model = TestModel(custom_output_args=_sample_blueprint_args())

    result = await _planner_agent.run(
        "Analyze class performance",
        model=test_model,
    )
    bp = result.output
    assert isinstance(bp, Blueprint)
    assert bp.id == "bp-test-planner"
    assert bp.name == "Test Analysis"


@pytest.mark.asyncio
async def test_generate_blueprint_three_layers():
    """Verify all three Blueprint layers are present and valid."""
    test_model = TestModel(custom_output_args=_sample_blueprint_args())

    result = await _planner_agent.run(
        "Analyze class performance",
        model=test_model,
    )
    bp = result.output

    # Layer A: DataContract
    assert len(bp.data_contract.inputs) == 1
    assert bp.data_contract.inputs[0].id == "class"
    assert len(bp.data_contract.bindings) == 1
    assert bp.data_contract.bindings[0].source_type == DataSourceType.TOOL
    assert bp.data_contract.bindings[0].tool_name == "get_assignment_submissions"

    # Layer B: ComputeGraph
    assert len(bp.compute_graph.nodes) == 1
    node = bp.compute_graph.nodes[0]
    assert node.type == ComputeNodeType.TOOL
    assert node.tool_name == "calculate_stats"
    assert node.output_key == "scoreStats"

    # Layer C: UIComposition
    assert bp.ui_composition.layout == "tabs"
    assert len(bp.ui_composition.tabs) == 1
    tab = bp.ui_composition.tabs[0]
    assert len(tab.slots) == 2
    assert tab.slots[0].component_type == ComponentType.KPI_GRID
    assert tab.slots[1].component_type == ComponentType.MARKDOWN
    assert tab.slots[1].ai_content_slot is True


@pytest.mark.asyncio
async def test_generate_blueprint_metadata():
    """Verify top-level metadata fields."""
    test_model = TestModel(custom_output_args=_sample_blueprint_args())

    result = await _planner_agent.run(
        "Analyze class performance",
        model=test_model,
    )
    bp = result.output

    assert bp.capability_level == CapabilityLevel.LEVEL_1
    assert bp.category == "analytics"
    assert bp.page_system_prompt != ""


@pytest.mark.asyncio
async def test_generate_blueprint_camel_case_output():
    """Verify the Blueprint serializes to camelCase for API output."""
    test_model = TestModel(custom_output_args=_sample_blueprint_args())

    result = await _planner_agent.run(
        "Analyze class performance",
        model=test_model,
    )
    bp = result.output
    data = bp.model_dump(by_alias=True)

    assert "dataContract" in data
    assert "computeGraph" in data
    assert "uiComposition" in data
    assert "capabilityLevel" in data
    assert "sourcePrompt" in data
    assert "pageSystemPrompt" in data


@pytest.mark.asyncio
async def test_generate_blueprint_with_language():
    """Test Blueprint generation with language parameter via TestModel."""
    test_model = TestModel(custom_output_args=_sample_blueprint_args())

    result = await _planner_agent.run(
        "[Language: zh-CN]\n\nUser request: 分析 Form 1A 的考试成绩",
        model=test_model,
    )
    bp = result.output
    assert isinstance(bp, Blueprint)
    assert bp.id == "bp-test-planner"
    # Verify the Blueprint is fully valid
    data = bp.model_dump(by_alias=True)
    assert "dataContract" in data
    assert "computeGraph" in data
    assert "uiComposition" in data


# ── sourcePrompt consistency (Phase 4.5.2) ─────────────────


def _mock_agent_run(bp_args: dict):
    """Create a mock for _planner_agent.run that returns a Blueprint."""
    mock_bp = Blueprint(**bp_args)
    mock_result = MagicMock()
    mock_result.output = mock_bp
    return AsyncMock(return_value=mock_result)


@pytest.mark.asyncio
async def test_source_prompt_always_equals_user_prompt():
    """sourcePrompt is force-overwritten to user_prompt regardless of LLM output."""
    user_prompt = "Show me the math scores for 1B班"

    with patch.object(_planner_agent, "run", _mock_agent_run(_sample_blueprint_args())):
        bp, _ = await generate_blueprint(user_prompt)

    assert bp.source_prompt == user_prompt


@pytest.mark.asyncio
async def test_source_prompt_overwrite_when_llm_rewrites():
    """Even when LLM sets a different sourcePrompt, force-overwrite applies."""
    args = _sample_blueprint_args()
    args["source_prompt"] = "LLM rewritten prompt that differs"

    user_prompt = "分析 1A 班英语成绩"

    with patch.object(_planner_agent, "run", _mock_agent_run(args)):
        bp, _ = await generate_blueprint(user_prompt)

    assert bp.source_prompt == user_prompt
    assert bp.source_prompt != "LLM rewritten prompt that differs"


@pytest.mark.asyncio
async def test_source_prompt_set_when_llm_omits():
    """When LLM omits sourcePrompt, it is populated from user_prompt."""
    args = _sample_blueprint_args()
    args["source_prompt"] = ""

    user_prompt = "Generate a report for Form 2A"

    with patch.object(_planner_agent, "run", _mock_agent_run(args)):
        bp, _ = await generate_blueprint(user_prompt)

    assert bp.source_prompt == user_prompt
