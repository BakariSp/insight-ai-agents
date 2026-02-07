"""Conversation API — unified entry point for all user interactions.

Routes requests through the RouterAgent to determine intent, then dispatches
to the appropriate agent (ChatAgent, PlannerAgent, PageChatAgent) based on
the classified intent and confidence level.

Supports two modes:
- **Initial mode** (no blueprint): chat / build / clarify
- **Follow-up mode** (with blueprint): chat / refine / rebuild

Endpoints:
- ``POST /api/conversation``         — JSON response (legacy, backward-compat)
- ``POST /api/conversation/stream``  — SSE Data Stream Protocol (Activity Stream)
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from agents.chat import generate_response as chat_response
from agents.executor import ExecutorAgent
from agents.page_chat import generate_response as page_chat_response
from agents.patch_agent import analyze_refine
from agents.planner import generate_blueprint
from agents.router import classify_intent
from models.conversation import (
    ClarifyChoice,
    ClarifyOptions,
    ConversationRequest,
    ConversationResponse,
    IntentType,
)
from models.entity import EntityType
from services.clarify_builder import build_clarify_options
from services.datastream import DataStreamEncoder, map_executor_event
from services.entity_resolver import resolve_entities

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["conversation"])

# Module-level executor — reused across requests.
_executor = ExecutorAgent()


def _normalize_teacher_id(raw: str | None) -> str:
    """Normalize teacher_id from request/context to avoid null-like values."""
    if raw is None:
        return ""
    value = str(raw).strip()
    if not value:
        return ""
    if value.lower() in {"none", "null", "undefined"}:
        return ""
    return value


def _verify_source_prompt(blueprint, expected_prompt: str) -> None:
    """Defence-in-depth check that sourcePrompt was not altered."""
    if blueprint.source_prompt != expected_prompt:
        logger.error(
            "sourcePrompt mismatch — expected %r but got %r; forcing overwrite",
            expected_prompt[:80],
            blueprint.source_prompt[:80],
        )
        blueprint.source_prompt = expected_prompt


@router.post("/conversation", response_model=ConversationResponse)
async def conversation(req: ConversationRequest):
    """Unified conversation endpoint — single entry point for all interactions.

    Detects mode (initial vs follow-up), classifies intent via RouterAgent,
    then dispatches to the appropriate handler.
    """
    try:
        req.teacher_id = _normalize_teacher_id(req.teacher_id)
        if req.context:
            req.context["teacherId"] = _normalize_teacher_id(
                req.context.get("teacherId")
            ) or req.teacher_id

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


# ── SSE streaming endpoint (Data Stream Protocol) ───────────────


@router.post("/conversation/stream")
async def conversation_stream(req: ConversationRequest):
    """Unified SSE conversation endpoint — Activity Stream.

    Returns the full conversation pipeline as a Vercel AI SDK Data Stream
    Protocol SSE stream.  Intent classification, entity resolution, Blueprint
    generation, and (for ``build`` actions) executor execution all happen
    within a single streamed response.

    Required frontend: ``useChat`` with ``x-vercel-ai-ui-message-stream: v1``.
    """
    return StreamingResponse(
        _conversation_stream_generator(req),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


async def _conversation_stream_generator(
    req: ConversationRequest,
) -> AsyncGenerator[str, None]:
    """Generate the full conversation as a Data Stream Protocol SSE stream."""
    enc = DataStreamEncoder()

    try:
        yield enc.start()

        # ── Normalize ──
        req.teacher_id = _normalize_teacher_id(req.teacher_id)
        if req.context:
            req.context["teacherId"] = _normalize_teacher_id(
                req.context.get("teacherId")
            ) or req.teacher_id

        is_followup = req.blueprint is not None

        # ── Step 1: Intent classification (Reasoning) ──
        yield enc.start_step()
        yield enc.reasoning_start("intent")
        yield enc.reasoning_delta("intent", "Analyzing your request...")

        router_result = await classify_intent(
            req.message,
            blueprint=req.blueprint,
            page_context=req.page_context,
        )
        intent = router_result.intent

        yield enc.reasoning_delta(
            "intent",
            f"\nIdentified as: {intent} (confidence {router_result.confidence:.0%})",
        )
        yield enc.reasoning_end("intent")
        yield enc.finish_step()

        # ── Step 2: Dispatch ──
        if is_followup:
            async for line in _stream_followup(enc, req, intent, router_result):
                yield line
        else:
            async for line in _stream_initial(enc, req, intent, router_result):
                yield line

    except Exception as e:
        logger.exception("Conversation stream failed")
        yield enc.error(f"Conversation processing failed: {e}")

    yield enc.finish()


async def _stream_initial(
    enc: DataStreamEncoder,
    req: ConversationRequest,
    intent: str,
    router_result,
) -> AsyncGenerator[str, None]:
    """Stream initial-mode intents via Data Stream Protocol."""

    # ── Chat ──
    if intent in (IntentType.CHAT_SMALLTALK.value, IntentType.CHAT_QA.value):
        kind = "smalltalk" if intent == IntentType.CHAT_SMALLTALK.value else "qa"
        yield enc.data("action", {"action": "chat", "chatKind": kind})

        text = await chat_response(
            req.message, intent_type=intent, language=req.language
        )
        tid = enc._id()
        yield enc.text_start(tid)
        yield enc.text_delta(tid, text)
        yield enc.text_end(tid)
        return

    # ── Build ──
    if intent == IntentType.BUILD_WORKFLOW.value:
        # Gateway-first guard: missing class context
        if (
            not (req.context and req.context.get("classId"))
            and router_result.route_hint == "needClassId"
        ):
            for _line in _emit_clarify(
                enc,
                req,
                router_result.clarifying_question
                or "Which class would you like to look at?",
                hint="needClassId",
            ):
                yield _line
            return

        # Context already specified — skip entity resolution
        if req.context and req.context.get("classId"):
            async for line in _stream_build(enc, req, req.message):
                yield line
            return

        # Entity resolution
        yield enc.start_step()
        yield enc.reasoning_start("entity")
        yield enc.reasoning_delta("entity", "Resolving entities...")

        resolve_result = await resolve_entities(
            teacher_id=req.teacher_id,
            query_text=req.message,
            context=req.context,
        )

        # Emit resolved entities as tool events
        for entity in resolve_result.entities or []:
            call_id = enc._id()
            yield enc.tool_input_start(call_id, "resolve_entity")
            yield enc.tool_input_available(
                call_id, "resolve_entity", {"query": entity.display_name}
            )
            yield enc.tool_output_available(
                call_id,
                {
                    "entityId": entity.entity_id,
                    "displayName": entity.display_name,
                    "confidence": entity.confidence,
                    "matchType": entity.match_type,
                },
            )

        yield enc.reasoning_end("entity")
        yield enc.finish_step()

        # Missing context → clarify
        if resolve_result.missing_context:
            for _line in _emit_clarify(
                enc, req, "Which class would you like to look at?", hint="needClassId"
            ):
                yield _line
            return

        # No entities → proceed without enrichment
        if resolve_result.scope_mode == "none":
            async for line in _stream_build(enc, req, req.message):
                yield line
            return

        # Ambiguous → clarify
        if resolve_result.is_ambiguous:
            clarify_choices = [
                {
                    "label": m.display_name,
                    "value": m.entity_id,
                    "description": f"Matched via {m.match_type} "
                    f"(confidence: {m.confidence:.0%})",
                }
                for m in resolve_result.entities
            ]
            yield enc.data("action", {"action": "clarify"})
            yield enc.data(
                "clarify",
                {
                    "type": "single_select",
                    "choices": clarify_choices or [],
                    "allowCustomInput": True,
                },
            )
            tid = enc._id()
            yield enc.text_start(tid)
            yield enc.text_delta(tid, "Could you confirm which you'd like to analyze?")
            yield enc.text_end(tid)
            return

        # High-confidence match — enrich context
        enriched_context = dict(req.context or {})
        context_parts: list[str] = []
        enriched_context.setdefault("input", {})

        for entity in resolve_result.entities:
            if entity.entity_type == EntityType.CLASS:
                if "classIds" not in enriched_context:
                    enriched_context.setdefault("classIds", [])
                enriched_context["classIds"].append(entity.entity_id)
                enriched_context["input"]["class"] = entity.entity_id
                context_parts.append(f"classId={entity.entity_id}")
            elif entity.entity_type == EntityType.STUDENT:
                enriched_context["studentId"] = entity.entity_id
                enriched_context["input"]["student"] = entity.entity_id
                context_parts.append(
                    f"studentId={entity.entity_id} ({entity.display_name})"
                )
            elif entity.entity_type == EntityType.ASSIGNMENT:
                enriched_context["assignmentId"] = entity.entity_id
                enriched_context["input"]["assignment"] = entity.entity_id
                context_parts.append(
                    f"assignmentId={entity.entity_id} ({entity.display_name})"
                )

        class_ids = enriched_context.pop("classIds", [])
        if len(class_ids) == 1:
            enriched_context["classId"] = class_ids[0]
        elif class_ids:
            enriched_context["classIds"] = class_ids

        enhanced_prompt = (
            f"{req.message}\n\n"
            f"[Resolved context: {', '.join(context_parts)}]"
        )
        req.context = enriched_context

        async for line in _stream_build(enc, req, enhanced_prompt):
            yield line
        return

    # ── Clarify ──
    if intent == IntentType.CLARIFY.value:
        for _line in _emit_clarify(
            enc,
            req,
            router_result.clarifying_question or "Could you provide more details?",
            hint=router_result.route_hint,
        ):
            yield _line
        return

    # ── Fallback → chat ──
    yield enc.data("action", {"action": "chat", "chatKind": "smalltalk"})
    text = await chat_response(req.message, language=req.language)
    tid = enc._id()
    yield enc.text_start(tid)
    yield enc.text_delta(tid, text)
    yield enc.text_end(tid)


async def _stream_followup(
    enc: DataStreamEncoder,
    req: ConversationRequest,
    intent: str,
    router_result,
) -> AsyncGenerator[str, None]:
    """Stream follow-up-mode intents via Data Stream Protocol."""

    if intent == "chat":
        yield enc.data("action", {"action": "chat", "chatKind": "page"})
        text = await page_chat_response(
            req.message,
            blueprint=req.blueprint,
            page_context=req.page_context,
            language=req.language,
        )
        tid = enc._id()
        yield enc.text_start(tid)
        yield enc.text_delta(tid, text)
        yield enc.text_end(tid)
        return

    if intent == "refine":
        refine_scope = router_result.refine_scope

        if refine_scope and refine_scope != "full_rebuild":
            yield enc.start_step()
            yield enc.reasoning_start("patch")
            yield enc.reasoning_delta("patch", f"Analyzing refinement scope: {refine_scope}")

            patch_plan = await analyze_refine(
                message=req.message,
                blueprint=req.blueprint,
                page=req.page_context,
                refine_scope=refine_scope,
            )

            yield enc.reasoning_delta("patch", f"\nPatch ready: {patch_plan.scope.value}")
            yield enc.reasoning_end("patch")
            yield enc.finish_step()

            yield enc.data("action", {"action": "refine"})
            yield enc.data("patch-plan", patch_plan.model_dump(by_alias=True))

            tid = enc._id()
            yield enc.text_start(tid)
            yield enc.text_delta(tid, f"Prepared patch: {patch_plan.scope.value}")
            yield enc.text_end(tid)
            return

        # Full rebuild path
        refine_prompt = (
            f"Refine the existing analysis '{req.blueprint.name}': {req.message}\n\n"
            f"Original blueprint description: {req.blueprint.description}"
        )
        async for line in _stream_build(enc, req, refine_prompt, action="refine"):
            yield line
        return

    if intent == "rebuild":
        rebuild_prompt = (
            f"Rebuild the analysis based on new requirements: {req.message}\n\n"
            f"Previous analysis was: {req.blueprint.name} — {req.blueprint.description}"
        )
        async for line in _stream_build(enc, req, rebuild_prompt, action="rebuild"):
            yield line
        return

    # Fallback → page chat
    yield enc.data("action", {"action": "chat", "chatKind": "page"})
    text = await page_chat_response(
        req.message,
        blueprint=req.blueprint,
        page_context=req.page_context,
        language=req.language,
    )
    tid = enc._id()
    yield enc.text_start(tid)
    yield enc.text_delta(tid, text)
    yield enc.text_end(tid)


async def _stream_build(
    enc: DataStreamEncoder,
    req: ConversationRequest,
    prompt: str,
    *,
    action: str = "build",
) -> AsyncGenerator[str, None]:
    """Generate Blueprint + execute it, streaming all events."""

    # ── Blueprint generation (Reasoning) ──
    yield enc.start_step()
    yield enc.reasoning_start("planning")
    yield enc.reasoning_delta("planning", "Planning page structure...")

    blueprint, _model = await generate_blueprint(
        user_prompt=prompt,
        language=req.language,
    )
    _verify_source_prompt(blueprint, prompt)

    bp_summary = (
        f"\nBlueprint ready: {len(blueprint.data_contract.bindings)} data source(s), "
        f"{len(blueprint.compute_graph.nodes)} compute node(s), "
        f"{len(blueprint.ui_composition.tabs)} tab(s)"
    )
    yield enc.reasoning_delta("planning", bp_summary)
    yield enc.reasoning_end("planning")

    yield enc.data("blueprint", blueprint.model_dump(by_alias=True))
    yield enc.data("action", {"action": action, "mode": "entry" if action == "build" else "followup"})
    yield enc.finish_step()

    # ── Blueprint execution (Tool + Data events) ──
    context = dict(req.context or {})
    context.setdefault("teacherId", req.teacher_id)

    # Open a step for the executor phases (the executor's PHASE events
    # will close/open steps via map_executor_event)
    yield enc.start_step()

    last_call_id = None
    async for event in _executor.execute_blueprint_stream(blueprint, context):
        lines, last_call_id = map_executor_event(
            enc, event, last_call_id=last_call_id
        )
        for line in lines:
            yield line

    yield enc.finish_step()

    # ── Completion text ──
    tid = enc._id()
    yield enc.text_start(tid)
    yield enc.text_delta(tid, f"Done! Generated: {blueprint.name}")
    yield enc.text_end(tid)


def _emit_clarify(
    enc: DataStreamEncoder,
    req: ConversationRequest,
    message: str,
    *,
    hint: str | None = None,
) -> list[str]:
    """Build clarify events (sync — returns list to use with ``yield from``)."""
    lines: list[str] = []
    lines.append(enc.data("action", {"action": "clarify"}))

    # Build clarify options inline (cannot await in yield-from context,
    # so the caller should pre-build if async options are needed).
    # For the common case we emit the hint so the frontend can fetch options.
    if hint:
        lines.append(enc.data("clarify", {"hint": hint}))

    tid = enc._id()
    lines.append(enc.text_start(tid))
    lines.append(enc.text_delta(tid, message))
    lines.append(enc.text_end(tid))
    return lines


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
        kind = "smalltalk" if intent == IntentType.CHAT_SMALLTALK.value else "qa"
        return ConversationResponse(
            mode="entry",
            action="chat",
            chat_kind=kind,
            chat_response=text,
            conversation_id=req.conversation_id,
        )

    if intent == IntentType.BUILD_WORKFLOW.value:
        # Gateway-first guard: when class context is required but missing, always clarify.
        if not (req.context and req.context.get("classId")) and router_result.route_hint == "needClassId":
            clarify_options = await build_clarify_options(
                "needClassId",
                teacher_id=req.teacher_id,
            )
            return ConversationResponse(
                mode="entry",
                action="clarify",
                chat_response=router_result.clarifying_question
                or "Which class would you like to look at?",
                clarify_options=clarify_options,
                conversation_id=req.conversation_id,
            )

        # Skip entity resolution if context already fully specified
        if req.context and req.context.get("classId"):
            blueprint, _model = await generate_blueprint(
                user_prompt=req.message,
                language=req.language,
            )
            _verify_source_prompt(blueprint, req.message)
            return ConversationResponse(
                mode="entry",
                action="build",
                blueprint=blueprint,
                chat_response=f"Generated analysis: {blueprint.name}",
                conversation_id=req.conversation_id,
            )

        # ── General entity resolution (before Blueprint generation) ──
        resolve_result = await resolve_entities(
            teacher_id=req.teacher_id,
            query_text=req.message,
            context=req.context,
        )

        # Missing dependent context → clarify
        if resolve_result.missing_context:
            hint = "needClassId"
            clarify_options = await build_clarify_options(
                hint, teacher_id=req.teacher_id,
            )
            return ConversationResponse(
                mode="entry",
                action="clarify",
                chat_response="Which class would you like to look at?",
                clarify_options=clarify_options,
                resolved_entities=resolve_result.entities or None,
                conversation_id=req.conversation_id,
            )

        if resolve_result.scope_mode == "none":
            # No entities mentioned — proceed normally
            blueprint, _model = await generate_blueprint(
                user_prompt=req.message,
                language=req.language,
            )
            _verify_source_prompt(blueprint, req.message)
            return ConversationResponse(
                mode="entry",
                action="build",
                blueprint=blueprint,
                chat_response=f"Generated analysis: {blueprint.name}",
                conversation_id=req.conversation_id,
            )

        if resolve_result.is_ambiguous:
            # Ambiguous — downgrade to clarify with matched options
            clarify_choices = [
                ClarifyChoice(
                    label=m.display_name,
                    value=m.entity_id,
                    description=f"Matched via {m.match_type} "
                    f"(confidence: {m.confidence:.0%})",
                )
                for m in resolve_result.entities
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
                mode="entry",
                action="clarify",
                chat_response="Could you confirm which you'd like to analyze?",
                clarify_options=clarify_options,
                resolved_entities=resolve_result.entities or None,
                conversation_id=req.conversation_id,
            )

        # High-confidence match — auto-inject into context
        resolved_entities = resolve_result.entities
        enriched_context = dict(req.context or {})
        context_parts: list[str] = []

        # Initialize input dict for Blueprint $input.* references
        enriched_context.setdefault("input", {})

        for entity in resolved_entities:
            if entity.entity_type == EntityType.CLASS:
                if "classIds" not in enriched_context:
                    enriched_context.setdefault("classIds", [])
                enriched_context["classIds"].append(entity.entity_id)
                # Also populate input.class for Blueprint compatibility
                enriched_context["input"]["class"] = entity.entity_id
                context_parts.append(f"classId={entity.entity_id}")
            elif entity.entity_type == EntityType.STUDENT:
                enriched_context["studentId"] = entity.entity_id
                enriched_context["input"]["student"] = entity.entity_id
                context_parts.append(
                    f"studentId={entity.entity_id} ({entity.display_name})"
                )
            elif entity.entity_type == EntityType.ASSIGNMENT:
                enriched_context["assignmentId"] = entity.entity_id
                enriched_context["input"]["assignment"] = entity.entity_id
                context_parts.append(
                    f"assignmentId={entity.entity_id} ({entity.display_name})"
                )

        # Promote single classIds to classId for backward compat
        class_ids = enriched_context.pop("classIds", [])
        if len(class_ids) == 1:
            enriched_context["classId"] = class_ids[0]
        elif class_ids:
            enriched_context["classIds"] = class_ids

        enhanced_prompt = (
            f"{req.message}\n\n"
            f"[Resolved context: {', '.join(context_parts)}]"
        )

        blueprint, _model = await generate_blueprint(
            user_prompt=enhanced_prompt,
            language=req.language,
        )
        _verify_source_prompt(blueprint, enhanced_prompt)
        return ConversationResponse(
            mode="entry",
            action="build",
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
            mode="entry",
            action="clarify",
            chat_response=router_result.clarifying_question
            or "Could you provide more details?",
            clarify_options=clarify_options,
            conversation_id=req.conversation_id,
        )

    # Fallback — treat as smalltalk
    text = await chat_response(req.message, language=req.language)
    return ConversationResponse(
        mode="entry",
        action="chat",
        chat_kind="smalltalk",
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
            mode="followup",
            action="chat",
            chat_kind="page",
            chat_response=text,
            conversation_id=req.conversation_id,
        )

    if intent == "refine":
        refine_scope = router_result.refine_scope

        # Check if we can use Patch mechanism
        if refine_scope and refine_scope != "full_rebuild":
            # Generate PatchPlan instead of new Blueprint
            patch_plan = await analyze_refine(
                message=req.message,
                blueprint=req.blueprint,
                page=req.page_context,
                refine_scope=refine_scope,
            )
            return ConversationResponse(
                mode="followup",
                action="refine",
                chat_response=f"Prepared patch: {patch_plan.scope.value}",
                patch_plan=patch_plan,
                conversation_id=req.conversation_id,
            )

        # Full rebuild path (original behavior)
        refine_prompt = (
            f"Refine the existing analysis '{req.blueprint.name}': {req.message}\n\n"
            f"Original blueprint description: {req.blueprint.description}"
        )
        blueprint, _model = await generate_blueprint(
            user_prompt=refine_prompt,
            language=req.language,
        )
        _verify_source_prompt(blueprint, refine_prompt)
        return ConversationResponse(
            mode="followup",
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
        _verify_source_prompt(blueprint, rebuild_prompt)
        return ConversationResponse(
            mode="followup",
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
        mode="followup",
        action="chat",
        chat_kind="page",
        chat_response=text,
        conversation_id=req.conversation_id,
    )
