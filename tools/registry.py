"""Single-source tool registry with toolset classification.

Step 1.1 of AI native rewrite.  All tools register here via
``@register_tool(toolset="generation")`` and are retrieved via
``get_tools(toolsets=["generation", "platform"])``.

Design:
- Tools are plain async functions decorated with ``@register_tool``.
- Each tool belongs to exactly one toolset.
- NativeAgent calls ``get_tools(toolsets)`` each turn to build
  a PydanticAI ``FunctionToolset`` for ``Agent(toolsets=[...])``.
- Replaces the dual FastMCP + TOOL_REGISTRY registration in ``tools/__init__.py``.
"""

from __future__ import annotations

import inspect
import logging
import time
from functools import wraps
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from pydantic_ai import Tool
from pydantic_ai.toolsets import FunctionToolset

from services.metrics import get_metrics_collector

logger = logging.getLogger(__name__)

# ── Toolset names (frozen after Step 2) ─────────────────────

TOOLSET_BASE_DATA = "base_data"
TOOLSET_ANALYSIS = "analysis"
TOOLSET_GENERATION = "generation"
TOOLSET_ARTIFACT_OPS = "artifact_ops"
TOOLSET_PLATFORM = "platform"

ALL_TOOLSETS = [
    TOOLSET_BASE_DATA,
    TOOLSET_ANALYSIS,
    TOOLSET_GENERATION,
    TOOLSET_ARTIFACT_OPS,
    TOOLSET_PLATFORM,
]

# Always-included toolsets (never excluded by select_toolsets)
ALWAYS_TOOLSETS = [TOOLSET_BASE_DATA, TOOLSET_PLATFORM]


# ── Registry internals ──────────────────────────────────────


@dataclass
class RegisteredTool:
    """Metadata for a registered tool."""

    name: str
    func: Callable[..., Any]
    toolset: str
    description: str = ""


# Module-level registry
_registry: dict[str, RegisteredTool] = {}


def register_tool(
    toolset: str,
    *,
    name: str | None = None,
):
    """Decorator to register a tool function with a toolset.

    Usage::

        @register_tool(toolset="generation")
        async def generate_quiz_questions(
            ctx: RunContext[AgentDeps], topic: str, count: int = 5
        ) -> dict:
            ...
    """
    if toolset not in ALL_TOOLSETS:
        raise ValueError(f"Unknown toolset: {toolset!r}. Must be one of {ALL_TOOLSETS}")

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        tool_name = name or func.__name__
        doc = (func.__doc__ or "").strip().split("\n")[0]
        wrapped = _wrap_with_metrics(func, tool_name)
        _registry[tool_name] = RegisteredTool(
            name=tool_name,
            func=wrapped,
            toolset=toolset,
            description=doc,
        )
        return wrapped

    return decorator


# ── Public API ──────────────────────────────────────────────


def get_tools(toolsets: Sequence[str]) -> FunctionToolset:
    """Return a PydanticAI FunctionToolset containing tools from the given toolsets.

    Args:
        toolsets: List of toolset names to include.

    Returns:
        A ``FunctionToolset`` ready to pass to ``Agent(toolsets=[...])``.
    """
    selected = [
        Tool(rt.func, name=rt.name)
        for rt in _registry.values()
        if rt.toolset in toolsets
    ]
    return FunctionToolset(selected)


def get_all_tools() -> FunctionToolset:
    """Return a FunctionToolset containing ALL registered tools."""
    all_tools = [
        Tool(rt.func, name=rt.name)
        for rt in _registry.values()
    ]
    return FunctionToolset(all_tools)


def get_tool_names(toolsets: Sequence[str] | None = None) -> list[str]:
    """Return tool names, optionally filtered by toolset."""
    if toolsets is None:
        return list(_registry.keys())
    return [
        rt.name for rt in _registry.values()
        if rt.toolset in toolsets
    ]


def get_tool_descriptions() -> list[dict[str, str]]:
    """Return name + description for every registered tool."""
    return [
        {"name": rt.name, "description": rt.description, "toolset": rt.toolset}
        for rt in _registry.values()
    ]


def get_registered_count() -> int:
    """Return the number of registered tools."""
    return len(_registry)


def get_toolset_counts() -> dict[str, int]:
    """Return tool count per toolset."""
    counts: dict[str, int] = {}
    for rt in _registry.values():
        counts[rt.toolset] = counts.get(rt.toolset, 0) + 1
    return counts


def _wrap_with_metrics(func: Callable[..., Any], tool_name: str) -> Callable[..., Any]:
    if not inspect.iscoroutinefunction(func):
        return func

    @wraps(func)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        start = time.monotonic()
        status = "ok"
        turn_id = ""
        conversation_id = ""

        # PydanticAI injects RunContext as first positional arg.
        # Also check kwargs for resilience against future calling convention changes.
        run_ctx = args[0] if args else kwargs.get("ctx") or kwargs.get("run_context")
        deps = getattr(run_ctx, "deps", None)
        if deps is not None:
            turn_id = str(getattr(deps, "turn_id", "") or "")
            conversation_id = str(getattr(deps, "conversation_id", "") or "")

        try:
            result = await func(*args, **kwargs)
            if isinstance(result, dict):
                status = str(result.get("status", "ok"))
            return result
        except Exception:
            status = "error"
            logger.exception("tool %s raised an unhandled exception", tool_name)
            raise
        finally:
            latency_ms = (time.monotonic() - start) * 1000
            get_metrics_collector().record_tool_call(
                tool_name=tool_name,
                status=status,
                latency_ms=latency_ms,
                turn_id=turn_id,
                conversation_id=conversation_id,
            )

    return wrapped
