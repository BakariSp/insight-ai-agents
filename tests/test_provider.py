"""Tests for agents/provider.py — model creation and MCP tool bridge."""

import pytest
from pydantic_ai.models.openai import OpenAIChatModel

from agents.provider import (
    create_model,
    execute_mcp_tool,
    get_model_chain_for_tier,
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


# ── Fallback chain ───────────────────────────────────────────


def test_get_model_chain_strong():
    """Strong tier chain has primary + fallback."""
    chain = get_model_chain_for_tier("strong")
    assert len(chain) >= 2
    assert chain[0] == get_model_for_tier("strong")  # primary first


def test_get_model_chain_fast():
    """Fast tier chain starts with router_model."""
    chain = get_model_chain_for_tier("fast")
    assert chain[0] == get_model_for_tier("fast")


def test_get_model_chain_no_duplicates():
    """Chain should not contain duplicates."""
    for tier in ("fast", "standard", "strong", "vision"):
        chain = get_model_chain_for_tier(tier)
        assert len(chain) == len(set(chain)), f"Duplicates in {tier} chain: {chain}"


def test_get_model_chain_default_model_last_resort():
    """default_model is always in the chain as last resort."""
    from config.settings import get_settings
    settings = get_settings()
    for tier in ("fast", "standard", "strong", "vision"):
        chain = get_model_chain_for_tier(tier)
        assert settings.default_model in chain


def test_override_model_in_create_teacher_agent():
    """_override_model bypasses tier mapping."""
    from agents.teacher_agent import create_teacher_agent
    agent = create_teacher_agent(
        teacher_context={"teacher_id": "t1", "classes": []},
        model_tier="strong",
        _override_model="dashscope/qwen-turbo-latest",
    )
    assert agent is not None


def test_is_provider_error():
    """_is_provider_error correctly identifies provider/model errors."""
    from api.conversation import _is_provider_error

    # Known message patterns should trigger fallback
    assert _is_provider_error(Exception("connection error")) is True
    assert _is_provider_error(Exception("rate limit exceeded")) is True
    assert _is_provider_error(Exception("Status 429")) is True
    # Normal errors should not trigger fallback
    assert _is_provider_error(ConnectionError("Connection refused")) is False
    assert _is_provider_error(ValueError("invalid input")) is False


def test_is_provider_error_unexpected_model_behavior():
    """UnexpectedModelBehavior (tool retry exhaustion) triggers fallback."""
    from api.conversation import _is_provider_error
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    err = UnexpectedModelBehavior("Tool 'generate_interactive_html' exceeded max retries count of 2")
    assert _is_provider_error(err) is True
