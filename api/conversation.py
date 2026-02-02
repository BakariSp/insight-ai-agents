"""Conversation API — unified entry point for all user interactions.

Routes requests through the RouterAgent to determine intent, then dispatches
to the appropriate agent (ChatAgent, PlannerAgent, PageChatAgent) based on
the classified intent and confidence level.

Supports two modes:
- **Initial mode** (no blueprint): chat / build / clarify
- **Follow-up mode** (with blueprint): chat / refine / rebuild
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from agents.chat import generate_response as chat_response
from agents.page_chat import generate_response as page_chat_response
from agents.planner import generate_blueprint
from agents.router import classify_intent
from models.conversation import (
    ClarifyChoice,
    ClarifyOptions,
    ConversationRequest,
    ConversationResponse,
    IntentType,
)
from services.clarify_builder import build_clarify_options
from services.entity_resolver import resolve_classes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["conversation"])


@router.post("/conversation", response_model=ConversationResponse)
async def conversation(req: ConversationRequest):
    """Unified conversation endpoint — single entry point for all interactions.

    Detects mode (initial vs follow-up), classifies intent via RouterAgent,
    then dispatches to the appropriate handler.
    """
    try:
        is_followup = req.blueprint is not None

        # ── Step 1: Classify intent ──
        router_result = await classify_intent(
            req.message,
            blueprint=req.blueprint,
            page_context=req.page_context,
        )

        intent = router_result.intent

        # ── Step 2: Dispatch based on mode + intent ──

        if is_followup:
            return await _handle_followup(req, intent, router_result)
        return await _handle_initial(req, intent, router_result)

    except Exception as e:
        logger.exception("Conversation processing failed")
        raise HTTPException(
            status_code=502,
            detail=f"Conversation processing failed: {e}",
        ) from e


async def _handle_initial(
    req: ConversationRequest,
    intent: str,
    router_result,
) -> ConversationResponse:
    """Handle initial-mode intents (no existing blueprint)."""

    if intent in (IntentType.CHAT_SMALLTALK.value, IntentType.CHAT_QA.value):
        # Chat — friendly response
        text = await chat_response(
            req.message,
            intent_type=intent,
            language=req.language,
        )
        return ConversationResponse(
            action=intent,
            chat_response=text,
            conversation_id=req.conversation_id,
        )

    if intent == IntentType.BUILD_WORKFLOW.value:
        # Skip entity resolution if class already provided in context
        if req.context and req.context.get("classId"):
            blueprint, _model = await generate_blueprint(
                user_prompt=req.message,
                language=req.language,
            )
            return ConversationResponse(
                action="build_workflow",
                blueprint=blueprint,
                chat_response=f"Generated analysis: {blueprint.name}",
                conversation_id=req.conversation_id,
            )

        # ── Entity resolution (before Blueprint generation) ──
        resolve_result = await resolve_classes(
            teacher_id=req.teacher_id,
            query_text=req.message,
        )

        if resolve_result.scope_mode == "none":
            # No class mentioned — proceed normally (backward compatible)
            blueprint, _model = await generate_blueprint(
                user_prompt=req.message,
                language=req.language,
            )
            return ConversationResponse(
                action="build_workflow",
                blueprint=blueprint,
                chat_response=f"Generated analysis: {blueprint.name}",
                conversation_id=req.conversation_id,
            )

        if resolve_result.is_ambiguous:
            # Ambiguous — downgrade to clarify with matched options
            clarify_choices = [
                ClarifyChoice(
                    label=m.display_name,
                    value=m.class_id,
                    description=f"Matched via {m.match_type} "
                    f"(confidence: {m.confidence:.0%})",
                )
                for m in resolve_result.matches
            ]
            if not clarify_choices:
                clarify_options = await build_clarify_options(
                    "needClassId", teacher_id=req.teacher_id,
                )
            else:
                clarify_options = ClarifyOptions(
                    type="single_select",
                    choices=clarify_choices,
                    allow_custom_input=True,
                )
            return ConversationResponse(
                action="clarify",
                chat_response="Could you confirm which class you'd like to analyze?",
                clarify_options=clarify_options,
                resolved_entities=resolve_result.matches or None,
                conversation_id=req.conversation_id,
            )

        # High-confidence match — auto-inject into context
        resolved_entities = resolve_result.matches
        enriched_context = dict(req.context or {})

        if resolve_result.scope_mode == "single":
            enriched_context["classId"] = resolved_entities[0].class_id
            enhanced_prompt = (
                f"{req.message}\n\n"
                f"[Resolved context: classId={enriched_context['classId']}]"
            )
        else:
            # Multi or grade — inject classIds list
            enriched_context["classIds"] = [
                m.class_id for m in resolved_entities
            ]
            class_names = ", ".join(m.display_name for m in resolved_entities)
            enhanced_prompt = (
                f"{req.message}\n\n"
                f"[Resolved context: classIds={enriched_context['classIds']}, "
                f"classes: {class_names}]"
            )

        blueprint, _model = await generate_blueprint(
            user_prompt=enhanced_prompt,
            language=req.language,
        )
        return ConversationResponse(
            action="build_workflow",
            blueprint=blueprint,
            chat_response=f"Generated analysis: {blueprint.name}",
            resolved_entities=resolved_entities,
            conversation_id=req.conversation_id,
        )

    if intent == IntentType.CLARIFY.value:
        # Clarify — build interactive options
        clarify_options = await build_clarify_options(
            router_result.route_hint,
            teacher_id=req.teacher_id,
        )
        return ConversationResponse(
            action="clarify",
            chat_response=router_result.clarifying_question
            or "Could you provide more details?",
            clarify_options=clarify_options,
            conversation_id=req.conversation_id,
        )

    # Fallback — treat as smalltalk
    text = await chat_response(req.message, language=req.language)
    return ConversationResponse(
        action="chat_smalltalk",
        chat_response=text,
        conversation_id=req.conversation_id,
    )


async def _handle_followup(
    req: ConversationRequest,
    intent: str,
    router_result,
) -> ConversationResponse:
    """Handle follow-up-mode intents (existing blueprint context)."""

    if intent == "chat":
        # Page chat — answer about existing data
        text = await page_chat_response(
            req.message,
            blueprint=req.blueprint,
            page_context=req.page_context,
            language=req.language,
        )
        return ConversationResponse(
            action="chat",
            chat_response=text,
            conversation_id=req.conversation_id,
        )

    if intent == "refine":
        # Refine — PlannerAgent adjusts existing Blueprint
        refine_prompt = (
            f"Refine the existing analysis '{req.blueprint.name}': {req.message}\n\n"
            f"Original blueprint description: {req.blueprint.description}"
        )
        blueprint, _model = await generate_blueprint(
            user_prompt=refine_prompt,
            language=req.language,
        )
        return ConversationResponse(
            action="refine",
            blueprint=blueprint,
            chat_response=f"Updated analysis: {blueprint.name}",
            conversation_id=req.conversation_id,
        )

    if intent == "rebuild":
        # Rebuild — PlannerAgent creates a new Blueprint
        rebuild_prompt = (
            f"Rebuild the analysis based on new requirements: {req.message}\n\n"
            f"Previous analysis was: {req.blueprint.name} — {req.blueprint.description}"
        )
        blueprint, _model = await generate_blueprint(
            user_prompt=rebuild_prompt,
            language=req.language,
        )
        return ConversationResponse(
            action="rebuild",
            blueprint=blueprint,
            chat_response=f"Rebuilt analysis: {blueprint.name}",
            conversation_id=req.conversation_id,
        )

    # Fallback — treat as page chat
    text = await page_chat_response(
        req.message,
        blueprint=req.blueprint,
        page_context=req.page_context,
        language=req.language,
    )
    return ConversationResponse(
        action="chat",
        chat_response=text,
        conversation_id=req.conversation_id,
    )
