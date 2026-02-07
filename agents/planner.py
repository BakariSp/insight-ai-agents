"""PlannerAgent — converts user natural-language prompts into Blueprints.

Uses PydanticAI with ``output_type=Blueprint`` for validated structured output.
The LLM is guided by a comprehensive system prompt that includes the Blueprint
schema, available tools, registered components, and examples.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from uuid import uuid4

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
    max_tokens=8192,
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

    try:
        result = await _planner_agent.run(run_prompt, **kwargs)
        blueprint = result.output
    except Exception:
        logger.exception("Planner structured output failed, using fallback blueprint")
        blueprint = _build_fallback_blueprint(user_prompt, language)

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


def _build_fallback_blueprint(user_prompt: str, language: str) -> Blueprint:
    """Build a minimal valid Blueprint when structured generation fails."""
    prompt = (user_prompt or "").strip()
    slug = uuid4().hex[:8]

    is_zh = language.lower().startswith("zh")
    quiz_keywords = (
        "quiz", "question", "worksheet", "homework", "assignment",
        "作业", "题", "练习", "试卷", "测验",
    )
    is_quiz = any(k in prompt.lower() for k in quiz_keywords) if prompt else False

    if is_quiz:
        count = _extract_question_count(prompt) or 10
        name = "英语作业" if is_zh else "English Assignment"
        desc = (
            f"自动生成 {count} 题英语练习"
            if is_zh
            else f"Auto-generated English practice with {count} questions"
        )
        tab_label = "作业" if is_zh else "Assignment"
        page_prompt = (
            "你是英语老师助手。请生成清晰、无歧义、难度适中的题目，并给出答案解析。"
            if is_zh
            else "You are an English teaching assistant. Generate clear, medium-difficulty questions with answer explanations."
        )
        return Blueprint(
            id=f"bp-fallback-{slug}",
            name=name,
            description=desc,
            icon="quiz",
            category="quiz",
            source_prompt=user_prompt,
            created_at=datetime.now(timezone.utc).isoformat(),
            data_contract={"inputs": [], "bindings": []},
            compute_graph={"nodes": []},
            ui_composition={
                "layout": "tabs",
                "tabs": [
                    {
                        "id": "quiz",
                        "label": tab_label,
                        "slots": [
                            {
                                "id": "quiz_questions",
                                "component_type": "question_generator",
                                "data_binding": None,
                                "props": {
                                    "title": name,
                                    "count": count,
                                    "types": ["multiple_choice", "short_answer"],
                                    "difficulty": "medium",
                                    "subject": "English",
                                    "topic": "General English",
                                    "knowledgePoint": "English",
                                },
                                "ai_content_slot": True,
                            }
                        ],
                    }
                ],
            },
            page_system_prompt=page_prompt,
        )

    name = "教学分析" if is_zh else "Teaching Analysis"
    tab_label = "分析" if is_zh else "Analysis"
    page_prompt = (
        "你是教学数据分析助手。请基于可用信息给出简洁、可执行的教学建议。"
        if is_zh
        else "You are an educational analysis assistant. Provide concise and actionable insights based on available information."
    )
    return Blueprint(
        id=f"bp-fallback-{slug}",
        name=name,
        description="Fallback blueprint",
        source_prompt=user_prompt,
        created_at=datetime.now(timezone.utc).isoformat(),
        data_contract={"inputs": [], "bindings": []},
        compute_graph={"nodes": []},
        ui_composition={
            "layout": "tabs",
            "tabs": [
                {
                    "id": "overview",
                    "label": tab_label,
                    "slots": [
                        {
                            "id": "analysis_text",
                            "component_type": "markdown",
                            "data_binding": None,
                            "props": {"variant": "insight"},
                            "ai_content_slot": True,
                        }
                    ],
                }
            ],
        },
        page_system_prompt=page_prompt,
    )


def _extract_question_count(prompt: str) -> int | None:
    """Extract desired question count from user prompt."""
    match = re.search(r"(\d{1,2})\s*(?:题|道|questions?|qs?)", prompt, re.IGNORECASE)
    if not match:
        return None
    count = int(match.group(1))
    if count < 1:
        return 1
    if count > 50:
        return 50
    return count
