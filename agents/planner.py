"""PlannerAgent — converts user natural-language prompts into Blueprints.

Uses PydanticAI with ``output_type=Blueprint`` for validated structured output.
The LLM is guided by a comprehensive system prompt that includes the Blueprint
schema, available tools, registered components, and examples.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from pydantic_ai import Agent

from agents.provider import create_model
from config.llm_config import LLMConfig
from config.prompts.planner import build_planner_prompt
from config.settings import get_settings
from models.blueprint import Blueprint

logger = logging.getLogger(__name__)

# Agent-level LLM tuning — structured output, low temperature
PLANNER_LLM_CONFIG = LLMConfig(
    temperature=0.2,
    response_format="json_object",
)

# Module-level agent — reused across requests.
# The model can be overridden per-run via generate_blueprint(model=...).
_planner_agent = Agent(
    model=create_model(),
    output_type=Blueprint,
    system_prompt=build_planner_prompt(),
    retries=2,
    defer_model_check=True,
)


async def generate_blueprint(
    user_prompt: str,
    language: str = "en",
    model: str | None = None,
) -> tuple[Blueprint, str]:
    """Generate a Blueprint from a user's natural-language request.

    Args:
        user_prompt: The teacher's analysis request in natural language.
        language: Language code for user-facing text in the Blueprint
                  (e.g. ``"en"``, ``"zh-CN"``).
        model: Optional model override (provider/model identifier).

    Returns:
        A ``(blueprint, model_name)`` tuple.
    """
    model_name = model or get_settings().default_model

    run_prompt = (
        f"[Language: {language}]\n\n"
        f"User request: {user_prompt}"
    )

    kwargs: dict = {
        "model_settings": PLANNER_LLM_CONFIG.to_litellm_kwargs(),
    }
    if model:
        kwargs["model"] = create_model(model)

    logger.info("Generating blueprint for prompt: %s", user_prompt[:80])

    result = await _planner_agent.run(run_prompt, **kwargs)
    blueprint = result.output

    # Force-overwrite sourcePrompt — never trust LLM to preserve the original.
    if blueprint.source_prompt and blueprint.source_prompt != user_prompt:
        logger.warning(
            "LLM rewrote sourcePrompt: %r → forcing original: %r",
            blueprint.source_prompt[:80],
            user_prompt[:80],
        )
    blueprint.source_prompt = user_prompt

    if not blueprint.created_at:
        blueprint.created_at = datetime.now(timezone.utc).isoformat()

    logger.info("Blueprint generated: %s (id=%s)", blueprint.name, blueprint.id)
    return blueprint, model_name
