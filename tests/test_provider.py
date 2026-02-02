"""Tests for agents/provider.py — model creation and MCP tool bridge."""

import pytest

from agents.provider import (
    create_model,
    execute_mcp_tool,
    get_mcp_tool_descriptions,
    get_mcp_tool_names,
)


# ── create_model ──────────────────────────────────────────────


def test_create_model_default():
    model = create_model()
    assert model.startswith("litellm:")
    assert "qwen" in model  # default_model contains "qwen"


def test_create_model_custom():
    model = create_model("openai/gpt-4o")
    assert model == "litellm:openai/gpt-4o"


# ── get_mcp_tool_names ────────────────────────────────────────


def test_get_mcp_tool_names():
    names = get_mcp_tool_names()
    assert isinstance(names, list)
    assert len(names) == 6
    assert "get_teacher_classes" in names
    assert "calculate_stats" in names
    assert "compare_performance" in names


# ── get_mcp_tool_descriptions ─────────────────────────────────


def test_get_mcp_tool_descriptions():
    descs = get_mcp_tool_descriptions()
    assert isinstance(descs, list)
    assert len(descs) == 6
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
