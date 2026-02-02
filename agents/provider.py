"""Agent provider — shared utilities for PydanticAI agents.

Creates LLM model instances and bridges FastMCP tools for in-process execution.
"""

from __future__ import annotations

import inspect
from typing import Any

from config.settings import get_settings
from tools import TOOL_REGISTRY, get_tool_descriptions


def create_model(model_name: str | None = None) -> str:
    """Build a PydanticAI model identifier string.

    PydanticAI v1.x accepts ``"litellm:<model>"`` as a model name,
    delegating to the LiteLLM provider under the hood.

    Args:
        model_name: LiteLLM model identifier (e.g. ``"dashscope/qwen-max"``).
                    Defaults to ``settings.default_model``.

    Returns:
        A ``"litellm:<model>"`` string ready for ``Agent(model=...)``.
    """
    settings = get_settings()
    name = model_name or settings.default_model
    return f"litellm:{name}"


def get_mcp_tool_names() -> list[str]:
    """Get the names of all registered FastMCP tools."""
    return list(TOOL_REGISTRY.keys())


def get_mcp_tool_descriptions() -> list[dict[str, str]]:
    """Get name + description for every registered tool.

    Returns:
        List of ``{"name": ..., "description": ...}`` dicts.
    """
    return get_tool_descriptions()


async def execute_mcp_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Execute a registered FastMCP tool by name.

    Looks up the function in :data:`tools.TOOL_REGISTRY` and calls it
    directly (supports both sync and async tool functions).

    Args:
        name: Tool name as registered in the TOOL_REGISTRY.
        arguments: Keyword arguments forwarded to the tool function.

    Returns:
        The tool's return value.

    Raises:
        ValueError: If the tool name is not found.
    """
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        raise ValueError(f"Tool '{name}' not found in registry")

    if inspect.iscoroutinefunction(fn):
        return await fn(**arguments)
    return fn(**arguments)
