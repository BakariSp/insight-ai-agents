"""RouterAgent — unified intent classifier for the conversation gateway.

Automatically detects initial vs follow-up mode based on whether a blueprint
is provided, and applies confidence-based routing:
- confidence >= 0.7  ->  direct action (build / quiz_generate / content_create)
- 0.4 <= confidence < 0.7  ->  force clarify
- confidence < 0.4  ->  treat as chat

Uses the fast ``router_model`` (qwen-turbo, ~200ms) for initial classification.
Quiz-related intents route to ``quiz_generate`` (Skill fast path);
data-analysis intents route to ``build_workflow`` (Blueprint path);
content generation intents route to ``content_create`` (Agent Path).
"""

from __future__ import annotations

import logging
import re

from pydantic_ai import Agent

from agents.provider import create_model
from config.llm_config import LLMConfig
from config.prompts.router import build_router_prompt
from config.settings import get_settings
from models.blueprint import Blueprint
from models.conversation import IntentType, RouterResult
from models.skill_config import SkillConfig

logger = logging.getLogger(__name__)

# Light, fast classification — low temperature for consistency
ROUTER_LLM_CONFIG = LLMConfig(
    temperature=0.1,
    response_format="json_object",
)


def _get_router_model_name() -> str:
    """Get the fast router model name from settings."""
    return get_settings().router_model


def _build_initial_agent() -> Agent[None, RouterResult]:
    """Create the initial-mode router agent (module-level singleton)."""
    return Agent(
        model=create_model(_get_router_model_name()),
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
    conversation_history: str = "",
    skill_config: SkillConfig | None = None,
) -> RouterResult:
    """Classify user intent, with confidence-based routing adjustments.

    Args:
        message: The user's message.
        blueprint: If provided, switches to follow-up mode.
        page_context: Page summary dict for follow-up context.
        conversation_history: Formatted recent turns for context.
        skill_config: Skill toggles from the frontend (RAG, file context).

    Returns:
        A :class:`RouterResult` with adjusted intent and confidence.
    """
    router_model = _get_router_model_name()
    is_followup = blueprint is not None

    if is_followup:
        page_summary = ""
        if page_context:
            page_summary = str(page_context)[:500]

        followup_agent = Agent(
            model=create_model(router_model),
            output_type=RouterResult,
            system_prompt=build_router_prompt(
                blueprint_name=blueprint.name,
                blueprint_description=blueprint.description,
                page_summary=page_summary,
                conversation_history=conversation_history,
            ),
            retries=1,
            defer_model_check=True,
        )
        result = await followup_agent.run(
            message,
            model_settings=ROUTER_LLM_CONFIG.to_litellm_kwargs(),
        )
        router_result = _normalize_router_fields(result.output)
        router_result.expected_mode = _infer_expected_mode(router_result.intent)
        logger.info(
            "Router (followup): intent=%s confidence=%.2f",
            router_result.intent,
            router_result.confidence,
        )
        return router_result

    # ── Initial mode with confidence-based routing ──
    if conversation_history:
        history_agent = Agent(
            model=create_model(router_model),
            output_type=RouterResult,
            system_prompt=build_router_prompt(
                conversation_history=conversation_history,
            ),
            retries=1,
            defer_model_check=True,
        )
        result = await history_agent.run(
            message,
            model_settings=ROUTER_LLM_CONFIG.to_litellm_kwargs(),
        )
    else:
        result = await _initial_agent.run(
            message,
            model_settings=ROUTER_LLM_CONFIG.to_litellm_kwargs(),
        )
    router_result = _normalize_router_fields(result.output)

    # Apply confidence-based routing overrides
    router_result = _apply_confidence_routing(router_result)

    # Apply keyword-based quiz hints (without hard intent rewrite)
    router_result = _apply_quiz_keyword_correction(router_result, message)

    # Assign execution path based on intent
    router_result.path = _assign_path(router_result)
    router_result.expected_mode = _infer_expected_mode(router_result.intent)

    # Apply skill_config overrides (e.g. file upload auto-enables RAG)
    if skill_config:
        if skill_config.uploaded_file_content:
            router_result.enable_rag = True
        if skill_config.enable_rag_search:
            router_result.enable_rag = True

    logger.info(
        "Router (initial): intent=%s confidence=%.2f path=%s should_build=%s strategy=%s",
        router_result.intent,
        router_result.confidence,
        router_result.path,
        router_result.should_build,
        router_result.strategy,
    )
    return router_result


def _assign_path(result: RouterResult) -> str:
    """Assign execution path based on classified intent.

    Returns one of: "skill", "blueprint", "agent", "chat".
    """
    intent = result.intent

    if intent == IntentType.QUIZ_GENERATE.value:
        return "skill"

    if intent == IntentType.BUILD_WORKFLOW.value:
        return "blueprint"

    if intent == IntentType.CONTENT_CREATE.value:
        return "agent"

    if intent in (IntentType.CHAT_SMALLTALK.value, IntentType.CHAT_QA.value):
        return "chat"

    if intent == IntentType.CLARIFY.value:
        return "chat"

    # Fallback: unknown intents go to agent (not degraded to chat)
    return "agent"


def _infer_expected_mode(intent: str) -> str:
    """Infer expected terminal mode for unified-agent validation."""
    if intent == IntentType.CLARIFY.value:
        return "clarify"
    if intent in (IntentType.QUIZ_GENERATE.value, IntentType.CONTENT_CREATE.value):
        return "artifact"
    return "answer"


def _normalize_router_fields(result: RouterResult) -> RouterResult:
    """Keep candidate_tools and suggested_tools synchronized."""
    if result.candidate_tools and not result.suggested_tools:
        result.suggested_tools = list(result.candidate_tools)
    elif result.suggested_tools and not result.candidate_tools:
        result.candidate_tools = list(result.suggested_tools)
    return result


# ---------------------------------------------------------------------------
# Keyword-based quiz hints
# ---------------------------------------------------------------------------

# Survey/form keywords
_QUIZ_FORM_KEYWORDS = re.compile(
    r"问卷|调查|调研|评估表|反馈表|出成题",
    re.UNICODE,
)
# Quiz-specific keywords
_QUIZ_QUESTION_KEYWORDS = re.compile(
    r"出[成]?题|测验题|练习题|选择题|填空题",
    re.UNICODE,
)


def _apply_quiz_keyword_correction(r: RouterResult, message: str) -> RouterResult:
    """Attach quiz tool hints using keywords, without force-changing intent."""
    if not message:
        return r

    is_quiz_like = bool(
        _QUIZ_FORM_KEYWORDS.search(message)
        or _QUIZ_QUESTION_KEYWORDS.search(message)
    )
    if not is_quiz_like:
        return r

    if "generate_quiz_questions" not in r.candidate_tools:
        r.candidate_tools.append("generate_quiz_questions")
    if "generate_quiz_questions" not in r.suggested_tools:
        r.suggested_tools.append("generate_quiz_questions")
        logger.info(
            "Quiz keyword hint: intent=%s confidence=%.2f add suggested tool generate_quiz_questions",
            r.intent,
            r.confidence,
        )

    return r


def _apply_confidence_routing(r: RouterResult) -> RouterResult:
    """Apply confidence thresholds to adjust routing decisions.

    - confidence >= 0.7 and intent is actionable -> allow action
    - 0.4 <= confidence < 0.7 -> force clarify
    - confidence < 0.4 -> treat as chat
    """
    confidence = r.confidence
    actionable_intents = {
        IntentType.BUILD_WORKFLOW.value,
        IntentType.QUIZ_GENERATE.value,
        IntentType.CONTENT_CREATE.value,
    }

    if confidence >= 0.7 and r.intent in actionable_intents:
        r.should_build = r.intent == IntentType.BUILD_WORKFLOW.value
        return r

    if 0.4 <= confidence < 0.7:
        if r.intent in actionable_intents or r.intent == IntentType.CLARIFY.value:
            r.intent = IntentType.CLARIFY.value
            r.should_build = False
            r.strategy = "ask_one_question"
            if not r.clarifying_question:
                r.clarifying_question = "Could you provide more details?"
            return r

    if confidence < 0.4:
        if r.intent not in (
            IntentType.CHAT_SMALLTALK.value,
            IntentType.CHAT_QA.value,
        ):
            r.intent = IntentType.CHAT_SMALLTALK.value
            r.should_build = False
            return r

    r.should_build = r.intent == IntentType.BUILD_WORKFLOW.value
    return r
