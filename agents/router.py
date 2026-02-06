"""RouterAgent — unified intent classifier for the conversation gateway.

Automatically detects initial vs follow-up mode based on whether a blueprint
is provided, and applies confidence-based routing:
- confidence ≥ 0.7  →  direct build
- 0.4 ≤ confidence < 0.7  →  force clarify
- confidence < 0.4  →  treat as chat

Phase 1 V1 capability guard:
- Only quiz_generation / analysis_to_quiz intents may trigger build
- Non-quiz build intents degrade to chat with friendly message
"""

from __future__ import annotations

import logging
import re

from pydantic_ai import Agent

from agents.provider import create_model
from config.llm_config import LLMConfig
from config.prompts.router import build_router_prompt
from models.blueprint import Blueprint
from models.conversation import IntentType, RouterResult

logger = logging.getLogger(__name__)

# ── V1 Capability Guard ──────────────────────────────────────

# Intent categories recognized from user messages (route_hint or detected)
V1_QUIZ_KEYWORDS = re.compile(
    r"(出题|生成.*题|练习|quiz|question|MCQ|选择题|填空题|判断题|简答题"
    r"|exercise|practice|test\s*paper|assessment|考试|测验|题目)",
    re.IGNORECASE,
)

V1_NON_QUIZ_HINTS = {
    "lesson_plan", "grading", "ppt_generation", "report_generation",
    "attendance", "scheduling",
}

V1_DEGRADATION_MESSAGE = (
    "当前版本聚焦于题目生成功能。该功能将在后续版本支持。\n"
    "你可以试试：「帮我出10道语法选择题」或「Generate 5 MCQs on Unit 5 grammar」"
)

V1_DEGRADATION_MESSAGE_EN = (
    "The current version focuses on quiz generation. This feature will be available in future versions.\n"
    "Try: 'Generate 10 grammar MCQs' or 'Create a Unit 5 practice quiz'"
)

# Light, fast classification — low temperature for consistency
ROUTER_LLM_CONFIG = LLMConfig(
    temperature=0.1,
    response_format="json_object",
)


def _build_initial_agent() -> Agent[None, RouterResult]:
    """Create the initial-mode router agent (module-level singleton)."""
    return Agent(
        model=create_model(),
        output_type=RouterResult,
        system_prompt=build_router_prompt(),
        retries=1,
        defer_model_check=True,
    )


_initial_agent = _build_initial_agent()


async def classify_intent(
    message: str,
    *,
    blueprint: Blueprint | None = None,
    page_context: dict | None = None,
) -> RouterResult:
    """Classify user intent, with confidence-based routing adjustments.

    Args:
        message: The user's message.
        blueprint: If provided, switches to follow-up mode.
        page_context: Page summary dict for follow-up context.

    Returns:
        A :class:`RouterResult` with adjusted intent and confidence.
    """
    is_followup = blueprint is not None

    if is_followup:
        # Build a per-request agent with follow-up context in the prompt
        page_summary = ""
        if page_context:
            page_summary = str(page_context)[:500]

        followup_agent = Agent(
            model=create_model(),
            output_type=RouterResult,
            system_prompt=build_router_prompt(
                blueprint_name=blueprint.name,
                blueprint_description=blueprint.description,
                page_summary=page_summary,
            ),
            retries=1,
            defer_model_check=True,
        )
        result = await followup_agent.run(
            message,
            model_settings=ROUTER_LLM_CONFIG.to_litellm_kwargs(),
        )
        router_result = result.output
        logger.info(
            "Router (followup): intent=%s confidence=%.2f",
            router_result.intent,
            router_result.confidence,
        )
        return router_result

    # ── Initial mode with confidence-based routing ──
    result = await _initial_agent.run(
        message,
        model_settings=ROUTER_LLM_CONFIG.to_litellm_kwargs(),
    )
    router_result = result.output

    # Apply confidence-based routing overrides
    router_result = _apply_confidence_routing(router_result)

    # Apply V1 capability guard
    router_result = _apply_v1_guard(router_result, message)

    logger.info(
        "Router (initial): intent=%s confidence=%.2f should_build=%s",
        router_result.intent,
        router_result.confidence,
        router_result.should_build,
    )
    return router_result


def _apply_confidence_routing(r: RouterResult) -> RouterResult:
    """Apply confidence thresholds to adjust routing decisions.

    - confidence ≥ 0.7 and intent is build_workflow → allow build
    - 0.4 ≤ confidence < 0.7 → force clarify
    - confidence < 0.4 → treat as chat
    """
    confidence = r.confidence

    if confidence >= 0.7 and r.intent == IntentType.BUILD_WORKFLOW.value:
        r.should_build = True
        return r

    if 0.4 <= confidence < 0.7:
        # Force clarify — the intent might be build but we need more info
        if r.intent in (IntentType.BUILD_WORKFLOW.value, IntentType.CLARIFY.value):
            r.intent = IntentType.CLARIFY.value
            r.should_build = False
            if not r.clarifying_question:
                r.clarifying_question = "Could you provide more details?"
            return r

    if confidence < 0.4:
        # Too vague — treat as chat
        if r.intent not in (
            IntentType.CHAT_SMALLTALK.value,
            IntentType.CHAT_QA.value,
        ):
            r.intent = IntentType.CHAT_SMALLTALK.value
            r.should_build = False
            return r

    r.should_build = r.intent == IntentType.BUILD_WORKFLOW.value
    return r


def _apply_v1_guard(r: RouterResult, message: str) -> RouterResult:
    """Apply V1 capability guard — only quiz-related intents may trigger build.

    If the router classified the message as build_workflow but the message
    does NOT look like a quiz/question generation request, degrade to chat
    with a friendly message suggesting quiz-related alternatives.
    """
    if not r.should_build:
        return r

    # Check if the route_hint suggests a non-quiz intent
    if r.route_hint and r.route_hint.lower() in V1_NON_QUIZ_HINTS:
        return _degrade_to_chat(r, message)

    # Check if the user message contains quiz-related keywords
    if V1_QUIZ_KEYWORDS.search(message):
        return r  # Allow — this is a quiz-related build

    # No quiz keywords found — if confidence is borderline, degrade
    # High-confidence build requests from the LLM are trusted
    # (the LLM classified it as build_workflow for a reason)
    # But if route_hint is explicitly non-quiz, we already caught that above
    return r


def _degrade_to_chat(r: RouterResult, message: str) -> RouterResult:
    """Degrade a build intent to chat with a V1 capability message."""
    logger.info("V1 guard: degrading non-quiz build intent to chat")
    r.intent = IntentType.CHAT_QA.value
    r.should_build = False

    # Detect language from message
    has_chinese = any("\u4e00" <= ch <= "\u9fff" for ch in message[:50])
    r.clarifying_question = (
        V1_DEGRADATION_MESSAGE if has_chinese else V1_DEGRADATION_MESSAGE_EN
    )
    return r
