"""LLM-based toolset planner — replaces keyword heuristics.

Uses a fast LLM call to decide which optional toolsets (analysis, generation,
artifact_ops) should be available for the current turn.  Falls back to keyword
matching on timeout, low confidence, or any error.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

from agents.provider import create_model, get_model_for_tier

logger = logging.getLogger(__name__)

# ── Output Schema ──────────────────────────────────────────

OPTIONAL_TOOLSETS = ("analysis", "generation", "artifact_ops")


class ToolsetPlannerResult(BaseModel):
    """Structured output from the planner LLM call."""

    toolsets: list[Literal["analysis", "generation", "artifact_ops"]] = Field(
        default_factory=list,
        description="Optional toolsets to include for this turn.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Self-assessed confidence in the selection.",
    )


# ── Planner Prompt ─────────────────────────────────────────

TOOLSET_PLANNER_PROMPT = """\
You select which optional tool categories are needed for a user's request.

## Available Optional Toolsets

- analysis: Statistical computations on student grades and scores (mean, compare, weakness, error patterns, mastery).
- generation: Create new content — quiz questions, PPT, documents, interactive HTML.
- artifact_ops: View, patch, or regenerate a previously created artifact.

## Context Fields

- has_artifacts: true if the conversation already contains generated artifacts.
- has_class_id: true if a class context is already set.

## Rules

1. Include a toolset if there is ANY reasonable chance the user needs it. False positives are cheap; false negatives break functionality.
2. If has_artifacts is true, ALWAYS include artifact_ops.
3. If has_class_id is true, ALWAYS include analysis.
4. For greetings or simple chat with no task intent, return an empty toolsets list.
5. Set confidence to how certain you are about the selection (0.0-1.0).

Respond with JSON matching the schema.\
"""

# ── Planner Agent (module-level singleton) ─────────────────


def _build_planner_agent() -> Agent[None, ToolsetPlannerResult]:
    return Agent(
        model=create_model(get_model_for_tier("fast")),
        output_type=ToolsetPlannerResult,
        system_prompt=TOOLSET_PLANNER_PROMPT,
        retries=0,
        defer_model_check=True,
    )


# Lazy singleton — created on first call to avoid import-time side effects.
_planner_agent: Agent[None, ToolsetPlannerResult] | None = None


def _get_planner_agent() -> Agent[None, ToolsetPlannerResult]:
    global _planner_agent
    if _planner_agent is None:
        _planner_agent = _build_planner_agent()
    return _planner_agent


# ── Public API ─────────────────────────────────────────────


async def plan_toolsets(
    message: str,
    *,
    has_artifacts: bool = False,
    has_class_id: bool = False,
) -> ToolsetPlannerResult:
    """Call the fast LLM to select toolsets for *message*.

    Args:
        message: The user's raw message text.
        has_artifacts: Whether the conversation has existing artifacts.
        has_class_id: Whether a class context is set.

    Returns:
        ``ToolsetPlannerResult`` with selected toolsets and confidence.
    """
    user_prompt = (
        f"Message: {message}\n"
        f"has_artifacts: {has_artifacts}\n"
        f"has_class_id: {has_class_id}"
    )

    agent = _get_planner_agent()
    result = await agent.run(
        user_prompt,
        model_settings=ModelSettings(temperature=0.0, max_tokens=256),
    )
    return result.output
