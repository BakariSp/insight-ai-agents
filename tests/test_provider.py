"""Tests for agents/provider.py — model creation and MCP tool bridge."""

import pytest
from pydantic_ai.models.openai import OpenAIChatModel

from agents.provider import (
    create_model,
    execute_mcp_tool,
    get_model_for_tier,
    get_mcp_tool_descriptions,
    get_mcp_tool_names,
)


# ── create_model ──────────────────────────────────────────────


def test_create_model_default():
    model = create_model()
    assert isinstance(model, OpenAIChatModel)
    assert "qwen" in model.model_name  # default_model contains "qwen"


def test_create_model_custom():
    model = create_model("openai/gpt-4o")
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "gpt-4o"


# ── get_mcp_tool_names ────────────────────────────────────────


def test_get_mcp_tool_names():
    names = get_mcp_tool_names()
    assert isinstance(names, list)
    # Core tools should always be present
    assert "get_teacher_classes" in names
    assert "calculate_stats" in names
    assert "compare_performance" in names
    # Phase 7 tools should also be present
    assert "analyze_student_weakness" in names
    assert "get_rubric" in names


# ── get_mcp_tool_descriptions ─────────────────────────────────


def test_get_mcp_tool_descriptions():
    descs = get_mcp_tool_descriptions()
    assert isinstance(descs, list)
    assert len(descs) >= 6  # At least core tools, more with Phase 7
    for item in descs:
        assert "name" in item
        assert "description" in item
        assert len(item["description"]) > 0


# ── execute_mcp_tool ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_mcp_tool_success():
    result = await execute_mcp_tool(
        "get_teacher_classes", {"teacher_id": "t-001"}
    )
    assert result["teacher_id"] == "t-001"
    assert len(result["classes"]) == 2


@pytest.mark.asyncio
async def test_execute_mcp_tool_stats():
    result = await execute_mcp_tool(
        "calculate_stats", {"data": [10, 20, 30]}
    )
    assert result["mean"] == 20.0


@pytest.mark.asyncio
async def test_execute_mcp_tool_not_found():
    with pytest.raises(ValueError, match="not found"):
        await execute_mcp_tool("nonexistent_tool", {})


# ── create_model with Anthropic ──────────────────────────────────


def test_create_model_anthropic():
    """Anthropic prefix creates AnthropicModel."""
    from pydantic_ai.models.anthropic import AnthropicModel
    model = create_model("anthropic/claude-opus-4-6")
    assert isinstance(model, AnthropicModel)


def test_create_model_dashscope():
    """Dashscope prefix creates OpenAIChatModel."""
    model = create_model("dashscope/qwen-turbo-latest")
    assert isinstance(model, OpenAIChatModel)


# ── get_model_for_tier ───────────────────────────────────────────


def test_get_model_for_tier_fast():
    model = get_model_for_tier("fast")
    assert isinstance(model, str)
    assert len(model) > 0


def test_get_model_for_tier_standard():
    model = get_model_for_tier("standard")
    assert isinstance(model, str)
    assert "/" in model


def test_get_model_for_tier_strong():
    model = get_model_for_tier("strong")
    assert isinstance(model, str)
    assert "/" in model


def test_get_model_for_tier_vision():
    model = get_model_for_tier("vision")
    assert isinstance(model, str)
    assert "/" in model


def test_get_model_for_tier_unknown_falls_back():
    """Unknown tier falls back to standard (agent_model)."""
    standard = get_model_for_tier("standard")
    unknown = get_model_for_tier("nonexistent_tier")
    assert unknown == standard


def test_tier_to_model_creates_valid_model():
    """End-to-end: tier → model name → PydanticAI model instance."""
    for tier in ("fast", "standard", "strong", "vision"):
        model_name = get_model_for_tier(tier)
        model = create_model(model_name)
        assert model is not None
