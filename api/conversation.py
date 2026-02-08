"""Conversation API — unified entry point for all user interactions.

Routes requests through the RouterAgent to determine intent, then dispatches
to the appropriate agent (ChatAgent, PlannerAgent, PageChatAgent, TeacherAgent)
based on the classified intent and confidence level.

Supports two modes:
- **Initial mode** (no blueprint): chat / quiz_generate / build / content_create / clarify
- **Follow-up mode** (with blueprint): chat / refine / rebuild

Three execution paths:
- **Unified Agent Path**: quiz_generate + content_create → agent tool orchestration
- **Blueprint Path**: build_workflow → Blueprint + Executor pipeline (~100s)
- **Legacy fallback paths**: quiz skill / content agent retained for safety rollback

Endpoints:
- ``POST /api/conversation``         — JSON response (legacy, backward-compat)
- ``POST /api/conversation/stream``  — SSE Data Stream Protocol (Activity Stream)
"""

from __future__ import annotations

import json
import logging
import time
from typing import AsyncGenerator

_SSE_HEARTBEAT_INTERVAL = 15  # seconds
_ROUTER_HISTORY_MAX_TURNS = 40
_MESSAGE_HISTORY_MAX_TURNS = 40

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
    RouterResult,
)
from models.agent_output import FinalResult
from models.entity import EntityType
from services.clarify_builder import build_clarify_options
from pydantic_ai.messages import ModelMessage
from services.conversation_store import (
    ConversationSession,
    generate_conversation_id,
    get_conversation_store,
)
from config.settings import get_settings
from services.agent_validation import (
    RetryNeeded,
    SoftRetryNeeded,
    validate_terminal_state,
)
from services.datastream import DataStreamEncoder, map_executor_event
from services.entity_resolver import resolve_entities
from skills.quiz_skill import build_quiz_intro, generate_quiz

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


# ── Session helpers ─────────────────────────────────────────


async def _load_session(
    store, req: ConversationRequest
) -> tuple[ConversationSession, str, list[ModelMessage]]:
    """Load or create a conversation session, inject accumulated context.

    Returns:
        (session, history_text, message_history) — session object, formatted
        history text for router prompts, and structured PydanticAI message
        history for agent ``message_history`` parameter.
    """
    had_conversation_id = bool(req.conversation_id)
    if not req.conversation_id:
        req.conversation_id = generate_conversation_id()

    session = await store.get(req.conversation_id)
    is_new_session = session is None
    if session is None:
        session = ConversationSession(conversation_id=req.conversation_id)

    # ── Defense-in-depth: restore history from recentHistory fallback ──
    # If we created a new session (no existing turns) but the frontend sent
    # recentHistory, populate the session with those messages.  This handles
    # the race condition where conversationId was lost between turns.
    if is_new_session and req.recent_history and len(session.turns) == 0:
        logger.warning(
            "[Session] New session but recentHistory provided (%d items) — "
            "restoring context from frontend fallback. conv_id=%s",
            len(req.recent_history),
            req.conversation_id,
        )
        for item in req.recent_history:
            if item.role == "user":
                session.add_user_turn(item.content)
            elif item.role == "assistant":
                session.add_assistant_turn(item.content)

    logger.info(
        "[Session] conv_id=%s had_id=%s new_session=%s existing_turns=%d message=%.60s",
        req.conversation_id,
        had_conversation_id,
        is_new_session,
        len(session.turns),
        req.message,
    )

    # Inject accumulated context from previous turns (current request takes priority)
    if session.accumulated_context:
        merged = dict(session.accumulated_context)
        if req.context:
            merged.update(req.context)
        req.context = merged

    # Record current user turn
    session.add_user_turn(req.message, attachment_count=len(req.attachments))

    history_text = session.format_history_for_prompt(
        max_turns=_ROUTER_HISTORY_MAX_TURNS
    )
    message_history = session.to_pydantic_messages(
        max_turns=_MESSAGE_HISTORY_MAX_TURNS
    )

    if history_text:
        logger.info(
            "[Session] history_text length=%d message_history_turns=%d preview=%.200s",
            len(history_text),
            len(message_history),
            history_text[:200],
        )
    else:
        logger.info("[Session] No conversation history (first turn)")

    return session, history_text, message_history


async def _save_session(
    store,
    session: ConversationSession,
    req: ConversationRequest,
    response: ConversationResponse,
    intent: str,
) -> None:
    """Save the conversation session after a response is built."""
    response_summary = response.chat_response or f"[{response.action}]"
    session.add_assistant_turn(response_summary, action=response.legacy_action)
    session.last_intent = intent
    session.last_action = response.legacy_action
    if req.context:
        session.merge_context(req.context)
    await store.save(session)
    response.conversation_id = req.conversation_id


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

        # ── Session: load ──
        store = get_conversation_store()
        session, history_text, message_history = await _load_session(store, req)

        is_followup = req.blueprint is not None

        # ── Step 1: Classify intent ──
        router_result = await classify_intent(
            req.message,
            blueprint=req.blueprint,
            page_context=req.page_context,
            conversation_history=history_text,
            skill_config=req.skill_config,
        )

        intent = router_result.intent

        # ── Step 2: Dispatch based on mode + intent ──

        if is_followup:
            response = await _handle_followup(req, intent, router_result, history_text, message_history)
        else:
            response = await _handle_initial(req, intent, router_result, history_text, message_history)

        # ── Session: save ──
        await _save_session(store, session, req, response, intent)

        return response

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
    streamed_text_parts: list[str] = []
    enc = DataStreamEncoder(text_sink=streamed_text_parts)
    session: ConversationSession | None = None
    intent = "unknown"

    try:
        yield enc.start()

        # ── Normalize ──
        req.teacher_id = _normalize_teacher_id(req.teacher_id)
        if req.context:
            req.context["teacherId"] = _normalize_teacher_id(
                req.context.get("teacherId")
            ) or req.teacher_id

        # ── Session: load ──
        store = get_conversation_store()
        session, history_text, message_history = await _load_session(store, req)
        yield enc.data("conversation", {"conversationId": req.conversation_id})

        is_followup = req.blueprint is not None or req.artifact_type is not None

        # Build artifact summary from session context for router prompt
        _artifact_summary = ""
        if req.artifact_type and session:
            ctx = session.accumulated_context or {}
            _artifact_summary = (
                ctx.get("last_artifact_summary")
                or f"Current artifact type: {ctx.get('last_artifact_type', req.artifact_type)}"
            )

        # ── Step 1: Intent classification (Reasoning) ──
        yield enc.start_step()
        yield enc.reasoning_start("intent")
        yield enc.reasoning_delta("intent", "Analyzing your request...")

        router_result = await classify_intent(
            req.message,
            blueprint=req.blueprint,
            page_context=req.page_context,
            conversation_history=history_text,
            skill_config=req.skill_config,
            artifact_type=req.artifact_type,
            artifact_summary=_artifact_summary,
        )
        intent = router_result.intent

        tier_label = router_result.model_tier
        if hasattr(tier_label, "value"):
            tier_label = tier_label.value
        yield enc.reasoning_delta(
            "intent",
            f"\nIdentified as: {intent} (confidence {router_result.confidence:.0%}, model: {tier_label})",
        )
        yield enc.reasoning_end("intent")
        yield enc.finish_step()

        # ── Step 2: Dispatch ──
        if is_followup and req.blueprint is not None:
            async for line in _stream_followup(enc, req, intent, router_result, history_text, message_history):
                yield line
        elif is_followup and req.artifact_type is not None:
            async for line in _stream_followup_artifact(
                enc, req, intent, router_result, history_text, message_history, session
            ):
                yield line
        else:
            async for line in _stream_initial(
                enc,
                req,
                intent,
                router_result,
                history_text,
                message_history,
                session=session,
            ):
                yield line

    except Exception as e:
        logger.exception("Conversation stream failed")
        yield enc.error(f"Conversation processing failed: {e}")

    # ── Session: save (after stream completes) ──
    if session is not None:
        streamed_text = "".join(streamed_text_parts).strip()
        response_summary = streamed_text or f"[streamed: {intent}]"
        # Detect agent-path clarify: if the agent returned clarify_needed,
        # override stored action so _compose_content_request_after_clarify fires
        # on the next user turn.
        effective_action = intent
        if intent in (IntentType.CONTENT_CREATE.value, IntentType.QUIZ_GENERATE.value):
            lower_text = streamed_text.lower()[:300]
            if "clarify_needed" in lower_text or "clarify" in lower_text:
                effective_action = "clarify_needed"
        session.add_assistant_turn(response_summary, action=effective_action)
        session.last_intent = intent
        session.last_action = effective_action
        if req.context:
            session.merge_context(req.context)
        # Record last artifact type for follow-up context detection
        _artifact_type = _detect_artifact_type_from_intent(intent, streamed_text)
        if _artifact_type:
            session.merge_context({
                "last_artifact_type": _artifact_type,
                "last_artifact_summary": response_summary[:1200],
            })
        try:
            await get_conversation_store().save(session)
            logger.info(
                "[Session] Saved conv_id=%s total_turns=%d summary_len=%d intent=%s",
                session.conversation_id,
                len(session.turns),
                len(response_summary),
                intent,
            )
        except Exception:
            logger.exception("Failed to save conversation session")

    yield enc.finish()


async def _stream_initial(
    enc: DataStreamEncoder,
    req: ConversationRequest,
    intent: str,
    router_result,
    history_text: str = "",
    message_history: list[ModelMessage] | None = None,
    session: ConversationSession | None = None,
) -> AsyncGenerator[str, None]:
    """Stream initial-mode intents via Data Stream Protocol."""

    # ── Chat ──
    if intent in (IntentType.CHAT_SMALLTALK.value, IntentType.CHAT_QA.value):
        kind = "smalltalk" if intent == IntentType.CHAT_SMALLTALK.value else "qa"
        yield enc.data("action", {"action": "chat", "chatKind": kind})

        text = await chat_response(
            req.message, intent_type=intent, language=req.language,
            conversation_history=history_text,
            attachments=req.attachments,
            message_history=message_history,
        )
        tid = enc._id()
        yield enc.text_start(tid)
        yield enc.text_delta(tid, text)
        yield enc.text_end(tid)
        return

    # ── Unified Agent entry (quiz + content_create) ──
    if intent in (
        IntentType.QUIZ_GENERATE.value,
        IntentType.CONTENT_CREATE.value,
    ):
        async for line in _stream_unified_agent_mode(
            enc=enc,
            req=req,
            router_result=router_result,
            intent=intent,
            session=session,
            history_text=history_text,
            message_history=message_history,
        ):
            yield line
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
            history_text=history_text,
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

        # Missing context → clarify (class takes priority since assignment depends on it)
        if resolve_result.missing_context:
            if "class" in resolve_result.missing_context:
                for _line in _emit_clarify(
                    enc, req, "Which class would you like to look at?", hint="needClassId"
                ):
                    yield _line
                return

            if "assignment" in resolve_result.missing_context:
                if resolve_result.clarify_options:
                    yield enc.data("action", {"action": "clarify"})
                    yield enc.data(
                        "clarify",
                        {
                            "type": "single_select",
                            "choices": resolve_result.clarify_options,
                            "hint": "needAssignmentId",
                        },
                    )
                    tid = enc._id()
                    yield enc.text_start(tid)
                    yield enc.text_delta(
                        tid, "Which assignment would you like to analyze?"
                    )
                    yield enc.text_end(tid)
                else:
                    for _line in _emit_clarify(
                        enc,
                        req,
                        "Which assignment would you like to analyze?",
                        hint="needAssignmentId",
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
    text = await chat_response(
        req.message, language=req.language,
        conversation_history=history_text,
        attachments=req.attachments,
        message_history=message_history,
    )
    tid = enc._id()
    yield enc.text_start(tid)
    yield enc.text_delta(tid, text)
    yield enc.text_end(tid)


async def _stream_followup(
    enc: DataStreamEncoder,
    req: ConversationRequest,
    intent: str,
    router_result,
    history_text: str = "",
    message_history: list[ModelMessage] | None = None,
) -> AsyncGenerator[str, None]:
    """Stream follow-up-mode intents via Data Stream Protocol."""

    if intent == "chat":
        yield enc.data("action", {"action": "chat", "chatKind": "page"})
        text = await page_chat_response(
            req.message,
            blueprint=req.blueprint,
            page_context=req.page_context,
            language=req.language,
            attachments=req.attachments,
            message_history=message_history,
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
        attachments=req.attachments,
        message_history=message_history,
    )
    tid = enc._id()
    yield enc.text_start(tid)
    yield enc.text_delta(tid, text)
    yield enc.text_end(tid)


async def _stream_followup_artifact(
    enc: DataStreamEncoder,
    req: ConversationRequest,
    intent: str,
    router_result,
    history_text: str = "",
    message_history: list | None = None,
    session=None,
) -> AsyncGenerator[str, None]:
    """Stream follow-up for non-blueprint artifact types (interactive, quiz, pptx, document)."""

    artifact_type = req.artifact_type or ""
    artifacts = req.artifacts or {}

    if intent == "chat":
        # Answer questions about the artifact using chat
        yield enc.data("action", {"action": "chat", "chatKind": "page"})
        text = await _artifact_chat_response(
            req.message,
            artifact_type=artifact_type,
            artifacts=artifacts,
            language=req.language,
            message_history=message_history,
        )
        tid = enc._id()
        yield enc.text_start(tid)
        yield enc.text_delta(tid, text)
        yield enc.text_end(tid)
        return

    if intent == "rebuild":
        # Full regeneration — re-enter initial mode
        yield enc.data("action", {"action": "rebuild"})
        async for line in _stream_initial(
            enc, req, "content_create", router_result, history_text, message_history,
            session=session,
        ):
            yield line
        return

    # intent == "refine" — incremental modification when supported
    # For unsupported types in phase-1, fallback to rebuild action + full regeneration.
    if artifact_type not in ("interactive", "quiz"):
        yield enc.data("action", {"action": "rebuild"})
    else:
        yield enc.data("action", {"action": "refine"})

    if artifact_type == "interactive":
        async for line in _stream_modify_interactive(enc, req, artifacts):
            yield line
    elif artifact_type == "quiz":
        async for line in _stream_modify_quiz(enc, req, artifacts):
            yield line
    elif artifact_type == "pptx":
        # PPT modification — for now, rebuild (Phase 2 TODO)
        async for line in _stream_initial(
            enc, req, "content_create", router_result, history_text, message_history,
            session=session,
        ):
            yield line
    elif artifact_type == "document":
        # Document modification — for now, rebuild (Phase 2 TODO)
        async for line in _stream_initial(
            enc, req, "content_create", router_result, history_text, message_history,
            session=session,
        ):
            yield line
    else:
        # Unknown artifact type — fallback to rebuild
        async for line in _stream_initial(
            enc, req, "content_create", router_result, history_text, message_history,
            session=session,
        ):
            yield line


async def _stream_modify_interactive(
    enc: DataStreamEncoder,
    req: ConversationRequest,
    artifacts: dict,
) -> AsyncGenerator[str, None]:
    """Incrementally modify interactive HTML content."""
    from skills.interactive_modify_skill import modify_interactive_stream

    interactive = artifacts.get("interactive", {})
    current_html = interactive.get("html", "")
    current_css = interactive.get("css", "")
    current_js = interactive.get("js", "")
    title = interactive.get("title", "Interactive Content")

    if not current_html and not current_css and not current_js:
        # No existing content to modify — fall back to text response
        tid = enc._id()
        yield enc.text_start(tid)
        yield enc.text_delta(tid, "No existing interactive content found to modify.")
        yield enc.text_end(tid)
        return

    async for event in modify_interactive_stream(
        current_html=current_html,
        current_css=current_css,
        current_js=current_js,
        modification_request=req.message,
        title=title,
    ):
        if event["type"] == "start":
            line = enc.data("interactive-content-start", event)
        elif event["type"] == "complete":
            line = enc.data(
                "interactive-content",
                {
                    "html": event.get("html", ""),
                    "css": event.get("css", ""),
                    "js": event.get("js", ""),
                    "title": event.get("title", "Interactive Content"),
                    "description": event.get("description", ""),
                    "preferredHeight": event.get("preferredHeight", 500),
                },
            )
            enc.append_to_sink(
                f"\n[已修改互动内容: {event.get('title', '')}]\n"
                f"修改: {req.message[:200]}\n"
                f"变更: {', '.join(event.get('changed', []))}"
            )
        else:
            continue
        yield line

    # Emit a text summary
    tid = enc._id()
    yield enc.text_start(tid)
    yield enc.text_delta(tid, f"已根据您的要求修改了互动内容。")
    yield enc.text_end(tid)


async def _stream_modify_quiz(
    enc: DataStreamEncoder,
    req: ConversationRequest,
    artifacts: dict,
) -> AsyncGenerator[str, None]:
    """Incrementally modify quiz questions."""
    import re
    from skills.quiz_skill import regenerate_question
    from models.quiz_output import QuizQuestionV1

    quiz_data = artifacts.get("quiz", {})
    questions = quiz_data.get("questions", [])
    modification = req.message

    if not questions:
        tid = enc._id()
        yield enc.text_start(tid)
        yield enc.text_delta(tid, "No existing quiz questions found to modify.")
        yield enc.text_end(tid)
        return

    # Detect single question replacement: "第3题...", "question 3..."
    index_match = re.search(r"第\s*(\d+)\s*[题道]|question\s*(\d+)", modification, re.IGNORECASE)
    if index_match:
        idx_str = index_match.group(1) or index_match.group(2)
        target_index = int(idx_str) - 1  # 0-based
        if 0 <= target_index < len(questions):
            try:
                original = QuizQuestionV1(**questions[target_index])
                new_q = await regenerate_question(original, feedback=modification)
                yield enc.data("quiz-replace", {
                    "index": target_index,
                    "question": new_q.model_dump(by_alias=True),
                    "status": "replaced",
                })
                enc.append_to_sink(
                    f"\n[已替换第{target_index + 1}题: {new_q.question[:80]}]"
                )
                tid = enc._id()
                yield enc.text_start(tid)
                yield enc.text_delta(tid, f"已替换第{target_index + 1}题。")
                yield enc.text_end(tid)
                return
            except Exception as e:
                logger.exception("Quiz question replacement failed: %s", e)

    # Fallback: can't parse specific modification — inform user
    tid = enc._id()
    yield enc.text_start(tid)
    yield enc.text_delta(
        tid,
        "请指定要修改的题目编号，例如「第3题太简单了，换一道」。"
        "或者说「重新出题」来全部重新生成。",
    )
    yield enc.text_end(tid)


async def _artifact_chat_response(
    message: str,
    *,
    artifact_type: str,
    artifacts: dict,
    language: str = "zh",
    message_history: list | None = None,  # noqa: ARG001 — reserved for future use
) -> str:
    """Generate a chat response about the current artifact."""
    from pydantic_ai import Agent as PydanticAgent
    from agents.provider import create_model, get_model_for_tier

    model_name = get_model_for_tier("fast")
    model = create_model(model_name)

    # Build artifact context summary
    artifact_desc = f"Current artifact type: {artifact_type}"
    artifact_data = artifacts.get(artifact_type, {})
    if artifact_type == "interactive":
        artifact_desc += f"\nTitle: {artifact_data.get('title', '')}"
        artifact_desc += f"\nDescription: {artifact_data.get('description', '')}"
    elif artifact_type == "quiz":
        qs = artifact_data.get("questions", [])
        artifact_desc += f"\nTotal questions: {len(qs)}"
        for i, q in enumerate(qs[:3]):
            artifact_desc += f"\nQ{i+1}: {str(q.get('question', ''))[:100]}"
    elif artifact_type == "pptx":
        artifact_desc += f"\nTitle: {artifact_data.get('title', '')}"
        artifact_desc += f"\nSlides: {artifact_data.get('totalSlides', 0)}"

    agent = PydanticAgent(
        model=model,
        output_type=str,
        system_prompt=(
            "You are a helpful educational AI assistant. The teacher has generated "
            f"content and is asking about it.\n\n{artifact_desc}\n\n"
            f"Answer in {'Chinese' if language == 'zh' else 'English'}."
        ),
        retries=1,
        defer_model_check=True,
    )
    result = await agent.run(message)
    return result.output


def _is_unified_quiz_enabled() -> bool:
    """Feature flag for Phase-1 quiz convergence."""
    settings = get_settings()
    return bool(settings.agent_unified_enabled and settings.agent_unified_quiz_enabled)


def _build_unified_quiz_agent_prompt(
    req: ConversationRequest,
    router_result: RouterResult,
) -> str:
    """Compose a strict prompt for unified quiz tool orchestration."""
    params = router_result.extracted_params or {}
    topic = str(params.get("topic", "") or "")
    count = int(params.get("count", 10) or 10)
    difficulty = str(params.get("difficulty", "medium") or "medium")
    subject = str(params.get("subject", "") or "")
    grade = str(params.get("grade", "") or "")
    types = params.get("types") or ["SINGLE_CHOICE", "FILL_IN_BLANK"]
    weakness_focus = params.get("weakness_focus") or []
    return (
        f"{req.message}\n\n"
        "This is a quiz generation task. You must call tool `generate_quiz_questions` exactly once.\n"
        "Never answer with plain text only. Return concise confirmation after tool call.\n\n"
        f"topic={topic}\n"
        f"count={count}\n"
        f"difficulty={difficulty}\n"
        f"subject={subject}\n"
        f"grade={grade}\n"
        f"types={types}\n"
        f"weakness_focus={weakness_focus}\n"
    )


def _get_unified_quiz_model_chain() -> list[str]:
    """Resolve model chain for unified quiz tool-calling."""
    settings = get_settings()
    chain = [settings.executor_model]
    if settings.agent_model and settings.agent_model != settings.executor_model:
        chain.append(settings.agent_model)
    if settings.agent_model_fallback:
        chain.append(settings.agent_model_fallback)

    override_model = (settings.agent_unified_quiz_model or "").strip()
    if override_model:
        chain = [override_model, *chain]

    deduped: list[str] = []
    for model_name in chain:
        if model_name and model_name not in deduped:
            deduped.append(model_name)
    return deduped


def _extract_quiz_artifact_from_agent_messages(
    agent_messages: list[ModelMessage],
) -> dict | None:
    """Extract generate_quiz_questions tool result from agent message graph."""
    for call in agent_messages:
        if not hasattr(call, "parts"):
            continue
        for part in call.parts:
            if hasattr(part, "tool_name") and hasattr(part, "content"):
                if part.tool_name == "generate_quiz_questions" and isinstance(part.content, dict):
                    return part.content
    return None


async def _run_unified_quiz_agent(
    prompt: str,
    model_name: str,
    message_history: list[ModelMessage] | None,
) -> tuple[dict | None, str]:
    """Run unified quiz tool-calling agent once with a specific model."""
    from pydantic_ai import Agent

    from agents.provider import create_model
    from tools.quiz_tools import generate_quiz_questions

    agent = Agent(
        model=create_model(model_name),
        system_prompt=(
            "You are a quiz tool orchestrator.\n"
            "You have exactly one tool: generate_quiz_questions.\n"
            "Always call that tool for quiz requests."
        ),
        retries=1,
        defer_model_check=True,
    )
    agent.tool_plain()(generate_quiz_questions)

    try:
        async with agent.run_stream(
            prompt,
            message_history=message_history or [],
            model_settings={
                "max_tokens": 4096,
                "tool_choice": "required",
            },
        ) as result:
            async for _ in result.stream_text(delta=True):
                pass
            messages = result.all_messages()
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"

    quiz_artifact = _extract_quiz_artifact_from_agent_messages(messages)
    if isinstance(quiz_artifact, dict):
        return quiz_artifact, ""
    return None, "tool_not_called"


async def _run_unified_quiz_direct_tool(
    req: ConversationRequest,
    router_result: RouterResult,
) -> dict:
    """Run unified quiz via deterministic direct tool execution."""
    from tools.quiz_tools import generate_quiz_questions

    params = router_result.extracted_params or {}
    settings = get_settings()
    selected_model = (settings.agent_unified_quiz_model or "").strip()
    return await generate_quiz_questions(
        topic=str(params.get("topic", "") or ""),
        count=int(params.get("count", 10) or 10),
        difficulty=str(params.get("difficulty", "medium") or "medium"),
        types=params.get("types"),
        subject=str(params.get("subject", "") or ""),
        grade=str(params.get("grade", "") or ""),
        context="",
        weakness_focus=params.get("weakness_focus"),
        model_name=selected_model,
    )


async def _stream_quiz_with_unified_fallback(
    enc: DataStreamEncoder,
    req: ConversationRequest,
    router_result: RouterResult,
    history_text: str = "",
    message_history: list[ModelMessage] | None = None,
) -> AsyncGenerator[str, None]:
    """Phase-1: prefer unified agent for quiz, keep legacy skill as fallback."""
    if not _is_unified_quiz_enabled():
        async for line in _stream_quiz_generate(enc, req, router_result):
            yield line
        return

    # Ensure quiz tool hint is present for this turn.
    if "generate_quiz_questions" not in router_result.candidate_tools:
        router_result.candidate_tools.append("generate_quiz_questions")
    if "generate_quiz_questions" not in router_result.suggested_tools:
        router_result.suggested_tools.append("generate_quiz_questions")

    prompt = _build_unified_quiz_agent_prompt(req, router_result)
    model_chain = _get_unified_quiz_model_chain()
    yield enc.data("action", {
        "action": "quiz_generate",
        "mode": "entry",
        "orchestrator": "unified_agent",
        "modelCandidates": model_chain,
    })

    # Deterministic unified mode: direct tool call (fast + stable).
    settings = get_settings()
    if settings.agent_unified_quiz_force_tool:
        try:
            artifact = await _run_unified_quiz_direct_tool(req, router_result)
            questions = artifact.get("questions", [])
            tid = enc._id()
            yield enc.text_start(tid)
            yield enc.text_delta(tid, "已通过 Unified Agent 入口生成题目。")
            yield enc.text_end(tid)
            if isinstance(questions, list):
                for idx, question in enumerate(questions):
                    yield enc.data("quiz-question", {
                        "index": idx,
                        "question": question if isinstance(question, dict) else {},
                        "status": "generated",
                    })
                yield enc.data("quiz-complete", {
                    "total": len(questions),
                    "message": f"{len(questions)} questions generated",
                })
                return
        except Exception as exc:  # noqa: BLE001
            logger.warning("[UnifiedQuiz] direct tool execution failed: %s", exc)

    chosen_model = ""
    artifact: dict | None = None
    last_error = ""
    for model_name in model_chain:
        chosen_model = model_name
        artifact, last_error = await _run_unified_quiz_agent(
            prompt,
            model_name,
            message_history,
        )
        if artifact is not None:
            break
        logger.warning("[UnifiedQuiz] model=%s did not produce tool artifact: %s", model_name, last_error)

    if artifact is not None:
        questions = artifact.get("questions", [])
        if isinstance(questions, list):
            tid = enc._id()
            yield enc.text_start(tid)
            yield enc.text_delta(
                tid,
                f"已通过 Unified Agent 生成题目（model={chosen_model}）。",
            )
            yield enc.text_end(tid)
            for idx, question in enumerate(questions):
                yield enc.data("quiz-question", {
                    "index": idx,
                    "question": question if isinstance(question, dict) else {},
                    "status": "generated",
                })
            yield enc.data("quiz-complete", {
                "total": len(questions),
                "message": f"{len(questions)} questions generated",
            })
            return

    logger.warning(
        "[UnifiedQuiz] No quiz artifact from unified agent models (%s). Last error=%s; fallback to legacy quiz skill path.",
        model_chain,
        last_error,
    )
    async for line in _stream_quiz_generate(enc, req, router_result):
        yield line


async def _stream_quiz_generate(
    enc: DataStreamEncoder,
    req: ConversationRequest,
    router_result: RouterResult,
) -> AsyncGenerator[str, None]:
    """Quiz generation fast path — single LLM call, streaming questions.

    Bypasses the Blueprint pipeline entirely.  Each question is pushed as a
    ``data-quiz-question`` SSE event the moment it is parsed from the LLM
    stream, giving the teacher near-instant feedback (~3-5s to first question).
    """
    params = router_result.extracted_params
    language = req.language

    # Determine optional RAG / file context + direct attachments
    context_parts: list[str] = []
    if router_result.enable_rag and req.skill_config:
        if req.skill_config.uploaded_file_content:
            context_parts.append(f"教师上传材料:\n{req.skill_config.uploaded_file_content}")

    # Extract text from direct chat attachments (documents)
    if req.attachments:
        from services.multimodal import build_user_content, has_attachments
        if has_attachments(req.attachments):
            enriched = await build_user_content("", req.attachments)
            # build_user_content returns str when only docs (no images)
            if isinstance(enriched, str) and enriched.strip():
                context_parts.append(enriched.strip())

    combined_context = "\n\n".join(context_parts)

    # Emit reasoning/thinking animation before generation starts
    rid = enc._id()
    yield enc.reasoning_start(rid)
    topic = params.get("topic", "")
    count = params.get("count", 10)
    yield enc.reasoning_delta(rid, f"Analyzing quiz requirements: {count} questions on '{topic}'...")
    yield enc.reasoning_delta(rid, "\nSelecting question types and difficulty distribution...")
    yield enc.reasoning_delta(rid, "\nPreparing generation with LaTeX math formatting...")
    yield enc.reasoning_end(rid)

    # Build intro text
    intro = build_quiz_intro(params, language)
    yield enc.data("action", {"action": "quiz_generate"})
    tid = enc._id()
    yield enc.text_start(tid)
    yield enc.text_delta(tid, intro)
    yield enc.text_end(tid)

    # Stream quiz questions — also accumulate for session memory
    question_index = 0
    generated_questions: list = []
    try:
        async for question in generate_quiz(
            topic=params.get("topic", ""),
            count=params.get("count", 10),
            difficulty=params.get("difficulty", "medium"),
            types=params.get("types"),
            subject=params.get("subject", ""),
            grade=params.get("grade", ""),
            context=combined_context,
            weakness_focus=params.get("weakness_focus", []),
        ):
            yield enc.data("quiz-question", {
                "index": question_index,
                "question": question.model_dump(by_alias=True),
                "status": "generated",
            })
            generated_questions.append(question)
            question_index += 1
    except Exception as e:
        logger.exception("Quiz generation failed at question %d", question_index)
        yield enc.error(f"Quiz generation failed: {e}")
        return

    # Completion signal
    yield enc.data("quiz-complete", {
        "total": question_index,
        "message": f"{question_index} questions generated",
    })

    # Save quiz content to session memory so follow-up turns have context
    if generated_questions:
        summary_lines = [f"\n[Generated {len(generated_questions)} quiz questions]:"]
        for q in generated_questions:
            opts = ""
            if q.options:
                opt_labels = "ABCDEFGHIJ"
                opts = " / ".join(
                    f"{opt_labels[i]}: {o}" for i, o in enumerate(q.options)
                )
            answer = q.correct_answer if q.correct_answer else ""
            summary_lines.append(
                f"Q{q.order}({q.question_type.value},{q.difficulty}): "
                f"{q.question}"
                + (f" [{opts}]" if opts else "")
                + (f" Answer: {answer}" if answer else "")
            )
        enc.append_to_sink("\n".join(summary_lines))


async def _stream_unified_agent_mode(
    enc: DataStreamEncoder,
    req: ConversationRequest,
    router_result: RouterResult,
    intent: str,
    session: ConversationSession | None = None,
    history_text: str = "",
    message_history: list[ModelMessage] | None = None,
) -> AsyncGenerator[str, None]:
    """Unified agent entry for quiz/content generation with shared loop."""
    settings = get_settings()
    unified_content_enabled = bool(
        settings.agent_unified_enabled and settings.agent_unified_content_enabled
    )

    # Work on a local copy to avoid mutating the caller's router_result
    router_result = router_result.model_copy(deep=True)

    if intent == IntentType.QUIZ_GENERATE.value:
        # Keep Phase-1 behavior as fallback when unified content mode is disabled.
        if not unified_content_enabled:
            async for line in _stream_quiz_with_unified_fallback(
                enc, req, router_result, history_text, message_history
            ):
                yield line
            return

        if "generate_quiz_questions" not in router_result.candidate_tools:
            router_result.candidate_tools.append("generate_quiz_questions")
        if "generate_quiz_questions" not in router_result.suggested_tools:
            router_result.suggested_tools.append("generate_quiz_questions")
        router_result.expected_mode = "artifact"

        action_payload = {
            "action": "quiz_generate",
            "orchestrator": "unified_agent",
            "mode": "entry",
            "intent": intent,
        }
        try:
            async for line in _stream_agent_mode(
                enc,
                req,
                router_result,
                history_text=history_text,
                message_history=message_history,
                action_payload=action_payload,
                allowed_tool_names=["generate_quiz_questions"],
                raise_on_error=True,
            ):
                yield line
            return
        except Exception as exc:
            logger.warning(
                "[UnifiedAgent] quiz unified path failed, fallback to legacy quiz stream: %s",
                exc,
            )
            async for line in _stream_quiz_with_unified_fallback(
                enc, req, router_result, history_text, message_history
            ):
                yield line
            return

    if intent == IntentType.CONTENT_CREATE.value:
        agent_message = _compose_content_request_after_clarify(session, req.message)
        router_result.expected_mode = "artifact"
        if unified_content_enabled:
            action_payload = {
                "action": "agent",
                "orchestrator": "unified_agent",
                "mode": "entry",
                "intent": intent,
            }
            try:
                async for line in _stream_agent_mode(
                    enc,
                    req,
                    router_result,
                    agent_message=agent_message,
                    history_text=history_text,
                    message_history=message_history,
                    action_payload=action_payload,
                    raise_on_error=True,
                ):
                    yield line
                return
            except Exception as exc:
                logger.warning(
                    "[UnifiedAgent] content unified path failed, fallback to legacy agent path: %s",
                    exc,
                )

        async for line in _stream_agent_mode(
            enc,
            req,
            router_result,
            agent_message=agent_message,
            history_text=history_text,
            message_history=message_history,
        ):
            yield line
        return

    # Defensive fallback for unexpected caller input.
    async for line in _stream_agent_mode(
        enc, req, router_result, history_text=history_text, message_history=message_history
    ):
        yield line


async def _stream_agent_mode(
    enc: DataStreamEncoder,
    req: ConversationRequest,
    router_result: RouterResult,
    agent_message: str | None = None,
    history_text: str = "",
    message_history: list[ModelMessage] | None = None,
    action_payload: dict | None = None,
    skip_teacher_context: bool = False,
    allowed_tool_names: list[str] | None = None,
    raise_on_error: bool = False,
) -> AsyncGenerator[str, None]:
    """Agent Path — LLM + Tools free orchestration for content generation.

    The PydanticAI Agent autonomously decides which tools to call based on the
    teacher's request.  Supports lesson plans, slides, worksheets, feedback,
    translations, and any other content generation task.

    Includes automatic model fallback and one terminal-state retry.
    """
    import asyncio as _asyncio

    from agents.provider import get_model_chain_for_tier
    from agents.teacher_agent import create_teacher_agent
    from services.tool_tracker import ToolTracker, ToolEvent

    tier_value = router_result.model_tier
    if hasattr(tier_value, "value"):
        tier_value = tier_value.value
    payload = action_payload or {
        "action": "agent",
        "mode": "entry",
        "intent": router_result.intent,
        "modelTier": tier_value,
    }
    if "modelTier" not in payload:
        payload["modelTier"] = tier_value
    yield enc.data("action", payload)

    if skip_teacher_context:
        teacher_context = {"teacher_id": req.teacher_id, "classes": []}
    else:
        teacher_context = await _get_teacher_context(req.teacher_id)

    from services.multimodal import build_user_content, has_attachments

    agent_input_text = agent_message or req.message
    agent_input: str | list = agent_input_text
    if req.attachments and has_attachments(req.attachments):
        agent_input = await build_user_content(agent_input_text, req.attachments)

    tier = router_result.model_tier
    if hasattr(tier, "value"):
        tier = tier.value
    model_chain = get_model_chain_for_tier(tier)

    tid = enc._id()
    yield enc.start_step()
    settings = get_settings()
    last_error = None
    completed = False

    for attempt, model_name in enumerate(model_chain):
        try:
            if attempt > 0:
                logger.warning(
                    "Agent fallback: attempt %d using %s (previous failed: %s)",
                    attempt + 1, model_name, last_error,
                )
                yield enc.reasoning_start("fallback")
                yield enc.reasoning_delta(
                    "fallback",
                    f"Primary model unavailable, switching to backup: {model_name}",
                )
                yield enc.reasoning_end("fallback")

            loop_history: list[ModelMessage] = list(message_history or [])
            output_repair_budget = 1    # structured output repair (UnexpectedModelBehavior)
            validation_retry_budget = 1  # terminal state validation (RetryNeeded/SoftRetryNeeded)

            while True:
                tracker = ToolTracker()
                called_tool_names: set[str] = set()
                emitted_event_types: set[str] = set()
                final_result: FinalResult | None = None

                agent = create_teacher_agent(
                    teacher_context=teacher_context,
                    suggested_tools=router_result.suggested_tools,
                    candidate_tools=router_result.candidate_tools,
                    model_tier=tier,
                    _override_model=model_name if attempt > 0 else None,
                    tool_tracker=tracker,
                    _allowed_tool_names=allowed_tool_names,
                    output_type=FinalResult,
                )

                merged_queue: _asyncio.Queue[tuple[str, object]] = _asyncio.Queue()
                agent_done = _asyncio.Event()
                messages_holder: list[list[ModelMessage]] = []

                async def _agent_runner():
                    try:
                        async with agent.run_stream(
                            agent_input,
                            message_history=loop_history,
                            model_settings={"max_tokens": settings.agent_max_tokens},
                        ) as stream_result:
                            await merged_queue.put(("text-start", tid))
                            last_message = ""
                            async for partial in stream_result.stream_output(
                                debounce_by=0.1
                            ):
                                current = partial.message or ""
                                if (
                                    current.startswith(last_message)
                                    and len(current) > len(last_message)
                                ):
                                    delta = current[len(last_message):]
                                    if delta:
                                        await merged_queue.put(("text-delta", delta))
                                elif current != last_message:
                                    # Message was rewritten by LLM (rare);
                                    # update tracking without incremental delta.
                                    pass
                                last_message = current
                            messages_holder.append(stream_result.all_messages())
                            final_output = await stream_result.get_output()
                            await merged_queue.put(("final-output", final_output))
                            await merged_queue.put(("text-end", None))
                    except Exception as exc:
                        await merged_queue.put(("error", exc))
                    finally:
                        agent_done.set()

                async def _tool_monitor():
                    while not agent_done.is_set():
                        try:
                            event = await _asyncio.wait_for(tracker.queue.get(), timeout=1.0)
                            await merged_queue.put(("tool-progress", event))
                        except _asyncio.TimeoutError:
                            continue
                    while not tracker.queue.empty():
                        await merged_queue.put(("tool-progress", tracker.queue.get_nowait()))

                runner_task = _asyncio.create_task(_agent_runner())
                monitor_task = _asyncio.create_task(_tool_monitor())

                last_heartbeat = time.monotonic()
                while True:
                    if runner_task.done() and monitor_task.done() and merged_queue.empty():
                        break
                    try:
                        msg_type, queue_payload = await _asyncio.wait_for(
                            merged_queue.get(), timeout=5.0
                        )
                    except _asyncio.TimeoutError:
                        now = time.monotonic()
                        if now - last_heartbeat > _SSE_HEARTBEAT_INTERVAL:
                            yield ": heartbeat\n\n"
                            last_heartbeat = now
                        continue

                    if msg_type == "text-start":
                        yield enc.text_start(str(queue_payload))
                    elif msg_type == "text-delta":
                        yield enc.text_delta(tid, str(queue_payload))
                    elif msg_type == "text-end":
                        yield enc.text_end(tid)
                    elif msg_type == "tool-progress" and isinstance(queue_payload, ToolEvent):
                        yield enc.data(
                            "tool-progress",
                            {
                                "tool": queue_payload.tool,
                                "status": queue_payload.status,
                                "message": queue_payload.message,
                                "duration_ms": queue_payload.duration_ms,
                            },
                        )
                    elif msg_type == "final-output" and isinstance(queue_payload, FinalResult):
                        final_result = queue_payload
                    elif msg_type == "error":
                        raise queue_payload  # type: ignore[misc]

                    last_heartbeat = time.monotonic()

                await runner_task
                await monitor_task

                agent_messages = messages_holder[0] if messages_holder else []
                interactive_plan = None
                for call in agent_messages:
                    if not hasattr(call, "parts"):
                        continue
                    for part in call.parts:
                        if not hasattr(part, "tool_name") or not hasattr(part, "content"):
                            continue
                        if isinstance(part.tool_name, str):
                            called_tool_names.add(part.tool_name)
                        if part.tool_name == "request_interactive_content":
                            interactive_plan = part.content
                            continue
                        for event_line in _build_tool_result_events(
                            enc, part.tool_name, part.content
                        ):
                            event_type = _extract_sse_event_type(event_line)
                            if event_type:
                                emitted_event_types.add(event_type)
                            yield event_line

                if interactive_plan and isinstance(interactive_plan, dict):
                    from skills.interactive_skill import generate_interactive_stream

                    async for event in generate_interactive_stream(
                        interactive_plan, teacher_context
                    ):
                        if event["type"] == "start":
                            line = enc.data("interactive-content-start", event)
                        elif event["type"].endswith("-delta"):
                            line = enc.data(
                                f"interactive-{event['type']}",
                                {"content": event["content"]},
                            )
                        elif (
                            event["type"].endswith("-complete")
                            and event["type"] != "complete"
                        ):
                            phase = event["type"].replace("-complete", "")
                            line = enc.data(f"interactive-{phase}-complete", {})
                        elif event["type"] == "complete":
                            line = enc.data(
                                "interactive-content",
                                {
                                    "html": event.get("html", ""),
                                    "css": event.get("css", ""),
                                    "js": event.get("js", ""),
                                    "title": event.get("title", "Interactive Content"),
                                    "description": event.get("description", ""),
                                    "preferredHeight": event.get("preferredHeight", 500),
                                },
                            )
                            # Store summary in session for follow-up context
                            enc.append_to_sink(
                                f"\n[已生成互动内容: {event.get('title', '')}]\n"
                                f"描述: {event.get('description', '')}\n"
                                f"包含: HTML({len(event.get('html', ''))}字符) + CSS + JS"
                            )
                        else:
                            continue
                        event_type = _extract_sse_event_type(line)
                        if event_type:
                            emitted_event_types.add(event_type)
                        yield line

                if final_result is None:
                    raise RuntimeError("Unified agent did not produce FinalResult output")

                try:
                    validate_terminal_state(
                        final_result,
                        emitted_events=emitted_event_types,
                        called_tools=called_tool_names,
                        expected_mode=router_result.expected_mode or "artifact",
                    )
                except SoftRetryNeeded as exc:
                    if validation_retry_budget > 0:
                        validation_retry_budget -= 1
                        loop_history = (message_history or []) + agent_messages
                        logger.warning(
                            "[UnifiedAgent] soft validation retry: %s", exc
                        )
                        continue
                    logger.warning(
                        "[UnifiedAgent] soft validation exhausted; accepting result"
                    )
                except RetryNeeded as exc:
                    if validation_retry_budget > 0:
                        validation_retry_budget -= 1
                        loop_history = (message_history or []) + agent_messages
                        logger.warning(
                            "[UnifiedAgent] terminal-state retry: %s", exc
                        )
                        continue
                    raise

                completed = True
                break

            if completed:
                break

        except Exception as e:
            last_error = f"{model_name}: {type(e).__name__}: {e}"
            exc_name = type(e).__name__

            # ── Output Repair Pass: try to salvage structured output ──
            if exc_name == "UnexpectedModelBehavior" and output_repair_budget > 0:
                output_repair_budget -= 1
                raw_body = getattr(e, "body", None)
                if isinstance(raw_body, bytes):
                    raw_body = raw_body.decode("utf-8", errors="replace")
                elif not isinstance(raw_body, str):
                    raw_body = str(raw_body) if raw_body else None
                logger.warning(
                    "[UnifiedAgent] Structured output failed, attempting repair pass. "
                    "raw_body_len=%d",
                    len(raw_body) if raw_body else 0,
                )
                repaired = await _attempt_output_repair(raw_body, model_name)
                if repaired is not None:
                    final_result = repaired
                    completed = True
                    break

            is_provider_error = _is_provider_error(e)
            if is_provider_error and attempt < len(model_chain) - 1:
                logger.warning(
                    "Agent model %s failed (provider error), will try fallback: %s",
                    model_name, e,
                )
                continue
            logger.exception("Agent path error (attempt %d/%d)", attempt + 1, len(model_chain))
            if raise_on_error:
                raise
            yield enc.error(f"Agent path error: {e}")
            break

    yield enc.finish_step()


def _detect_artifact_type_from_intent(intent: str, streamed_text: str) -> str | None:
    """Infer the artifact type produced during this turn from intent + text cues."""
    if intent == "quiz_generate":
        return "quiz"
    if intent == "content_create":
        lower = streamed_text.lower()
        if "互动" in lower or "interactive" in lower:
            return "interactive"
        if "ppt" in lower or "演示" in lower or "slides" in lower:
            return "pptx"
        if "已生成" in lower and ("文档" in lower or "docx" in lower or "pdf" in lower):
            return "document"
        # Fallback: check for known markers injected by append_to_sink
        if "[已生成互动内容" in streamed_text:
            return "interactive"
        if "[已生成PPT大纲" in streamed_text:
            return "pptx"
        if "[已生成" in streamed_text and "文档" in streamed_text:
            return "document"
    return None


def _extract_sse_event_type(line: str) -> str | None:
    """Extract `type` from a single SSE `data:` line."""
    if not line.startswith("data: "):
        return None
    try:
        payload = json.loads(line[6:].strip())
    except Exception:
        return None
    event_type = payload.get("type") if isinstance(payload, dict) else None
    return event_type if isinstance(event_type, str) else None


def _compose_content_request_after_clarify(
    session: ConversationSession | None,
    current_message: str,
) -> str:
    """Expand a post-clarify reply into an executable content request.

    When the previous assistant turn was ``clarify`` and the user only replies
    with missing parameters (e.g. grade, duration), the model can reply with an
    acknowledgement but skip actual generation. We stitch the original request
    and new details into one explicit instruction so Agent Path proceeds.
    """
    if session is None or len(session.turns) < 3:
        return current_message

    turns = session.turns
    if turns[-1].role != "user":
        return current_message

    # Find the most recent assistant turn before the current user turn.
    last_assistant_idx: int | None = None
    for idx in range(len(turns) - 2, -1, -1):
        if turns[idx].role == "assistant":
            last_assistant_idx = idx
            break

    if last_assistant_idx is None:
        return current_message

    last_action = (turns[last_assistant_idx].action or "").strip().lower()
    # Detect both router-level clarify and agent-path clarify (stored as "clarify_needed")
    is_clarify_turn = last_action in (IntentType.CLARIFY.value, "clarify_needed")
    if not is_clarify_turn:
        return current_message

    # Extract the assistant's clarify question text
    assistant_question = turns[last_assistant_idx].content.strip()

    original_request = ""
    for idx in range(last_assistant_idx - 1, -1, -1):
        turn = turns[idx]
        if turn.role == "user" and turn.content.strip():
            original_request = turn.content.strip()
            break

    if not original_request:
        return current_message

    logger.info(
        "[Continuity] Expanding post-clarify content request. original=%.80s question=%.80s details=%.80s",
        original_request,
        assistant_question,
        current_message,
    )
    return (
        "Continue the previous request with the provided details and generate the final output now.\n\n"
        f"Original request:\n{original_request}\n\n"
        f"Assistant asked:\n{assistant_question}\n\n"
        f"User's answer:\n{current_message}\n\n"
        "You MUST now either:\n"
        "1. Produce the complete deliverable by calling the appropriate tool(s), OR\n"
        "2. Ask another clarify question ONLY if specific critical information is still missing.\n"
        "Do NOT merely acknowledge the answer. Take action immediately."
    )


def _is_provider_error(exc: Exception) -> bool:
    """Check if an exception indicates a model-level failure worth retrying with fallback.

    Returns True for:
    - Provider connectivity errors (connection, auth, rate limit)
    - Model behaviour errors (tool call failures after retries)

    Returns False for application-level errors (e.g. business logic).
    """
    exc_name = type(exc).__name__
    exc_msg = str(exc).lower()

    # PydanticAI wraps provider errors
    provider_error_types = {
        "ModelAPIError", "ModelHTTPError", "APIConnectionError",
        "RateLimitError", "AuthenticationError", "APIStatusError",
        "RemoteProtocolError", "ConnectError", "TimeoutException",
    }
    if exc_name in provider_error_types:
        return True

    # Model can't use tools correctly after retries → try a different model
    if exc_name == "UnexpectedModelBehavior":
        return True

    # Check wrapped cause
    cause = getattr(exc, "__cause__", None)
    if cause and type(cause).__name__ in provider_error_types:
        return True

    # Check message patterns
    if any(p in exc_msg for p in ("connection error", "rate limit", "429", "401", "403", "503")):
        return True

    return False


async def _attempt_output_repair(
    raw_body: str | None,
    model_name: str,
) -> FinalResult | None:
    """Attempt to repair a malformed FinalResult from raw model output.

    Makes a single non-streaming LLM call asking the model to extract/reformat
    the raw output into a valid FinalResult JSON.

    Returns FinalResult if repair succeeds, None otherwise.
    """
    if not raw_body or not raw_body.strip():
        return None

    from pydantic_ai import Agent
    from agents.provider import create_model

    repair_prompt = (
        "The following text is a malformed response from an AI assistant. "
        "Extract the intent and reformat it as valid JSON matching this exact schema:\n\n"
        '{"status": "answer_ready"|"artifact_ready"|"clarify_needed", '
        '"message": "...", "artifacts": [...], "clarify": {"question": "..."} | null}\n\n'
        "Rules:\n"
        "- If the text contains a question for the user, status=clarify_needed and set clarify.question\n"
        "- If the text mentions generated files/content, status=artifact_ready\n"
        "- Otherwise, status=answer_ready\n"
        "- Output ONLY the JSON object, nothing else.\n\n"
        f"Raw text:\n{raw_body[:3000]}"
    )

    try:
        repair_agent = Agent(
            model=create_model(model_name),
            output_type=FinalResult,
            retries=0,
            defer_model_check=True,
        )
        result = await repair_agent.run(repair_prompt)
        logger.info("[RepairPass] Successfully repaired output: status=%s", result.output.status)
        return result.output
    except Exception as exc:
        logger.warning("[RepairPass] Repair failed: %s", exc)
        return None


def _build_tool_result_events(
    enc: DataStreamEncoder,
    tool_name: str,
    result: object,
) -> list[str]:
    """Convert tool call results into frontend-renderable SSE events."""
    events: list[str] = []

    if not isinstance(result, dict):
        return events

    if tool_name in ("generate_pptx", "generate_docx", "render_pdf"):
        file_type = {
            "generate_pptx": "pptx",
            "generate_docx": "docx",
            "render_pdf": "pdf",
        }.get(tool_name, "unknown")
        events.append(enc.data("file-ready", {
            "type": file_type,
            "url": result.get("url", ""),
            "filename": result.get("filename", ""),
            "size": result.get("size"),
        }))
        # Store summary in session for follow-up context
        enc.append_to_sink(
            f"\n[已生成{file_type}文档: {result.get('filename', '')}]"
        )

    elif tool_name == "propose_pptx_outline":
        events.append(enc.data("pptx-outline", {
            "title": result.get("title", ""),
            "outline": result.get("outline", []),
            "totalSlides": result.get("totalSlides", 0),
            "estimatedDuration": result.get("estimatedDuration", 0),
            "requiresConfirmation": True,
        }))
        # Store summary in session for follow-up context
        outline_titles = ", ".join(
            s.get("title", "") for s in (result.get("outline") or [])[:5]
        )
        enc.append_to_sink(
            f"\n[已生成PPT大纲: {result.get('title', '')}，"
            f"共{result.get('totalSlides', 0)}页，"
            f"包含: {outline_titles}]"
        )

    elif tool_name == "save_as_assignment":
        events.append(enc.data("assignment-saved", {
            "assignmentId": result.get("assignment_id"),
            "message": result.get("message", "Saved"),
        }))

    elif tool_name == "create_share_link":
        events.append(enc.data("share-link-created", {
            "shareUrl": result.get("share_url"),
            "qrCodeUrl": result.get("qr_code_url"),
        }))

    elif tool_name == "generate_interactive_html":
        events.append(enc.data("interactive-content", {
            "html": result.get("html", ""),
            "title": result.get("title", "Interactive Content"),
            "description": result.get("description", ""),
            "preferredHeight": result.get("preferredHeight", 500),
        }))
        enc.append_to_sink(
            f"\n[已生成互动内容: {result.get('title', '')}]\n"
            f"描述: {result.get('description', '')}"
        )

    elif tool_name == "generate_quiz_questions":
        questions = result.get("questions", [])
        if isinstance(questions, list):
            for idx, question in enumerate(questions):
                events.append(enc.data("quiz-question", {
                    "index": idx,
                    "question": question if isinstance(question, dict) else {},
                    "status": "generated",
                }))
            events.append(enc.data("quiz-complete", {
                "total": len(questions),
                "message": f"{len(questions)} questions generated",
            }))

    return events


async def _get_teacher_context(teacher_id: str) -> dict:
    """Get teacher context quickly (no LLM call)."""
    try:
        from tools.data_tools import get_teacher_classes
        classes_data = await get_teacher_classes(teacher_id)
        return {
            "teacher_id": teacher_id,
            "classes": classes_data.get("classes", []) if isinstance(classes_data, dict) else [],
        }
    except Exception:
        return {"teacher_id": teacher_id, "classes": []}


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
        attachments=req.attachments if req.attachments else None,
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
    last_event_time = time.monotonic()
    async for event in _executor.execute_blueprint_stream(blueprint, context):
        now = time.monotonic()
        if now - last_event_time > _SSE_HEARTBEAT_INTERVAL:
            yield ": heartbeat\n\n"

        lines, last_call_id = map_executor_event(
            enc, event, last_call_id=last_call_id
        )
        for line in lines:
            yield line
        last_event_time = time.monotonic()

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
    history_text: str = "",
    message_history: list[ModelMessage] | None = None,
) -> ConversationResponse:
    """Handle initial-mode intents (no existing blueprint)."""

    if intent in (IntentType.CHAT_SMALLTALK.value, IntentType.CHAT_QA.value):
        # Chat — friendly response
        text = await chat_response(
            req.message,
            intent_type=intent,
            language=req.language,
            conversation_history=history_text,
            attachments=req.attachments,
            message_history=message_history,
        )
        kind = "smalltalk" if intent == IntentType.CHAT_SMALLTALK.value else "qa"
        return ConversationResponse(
            mode="entry",
            action="chat",
            chat_kind=kind,
            chat_response=text,
            conversation_id=req.conversation_id,
        )

    if intent == IntentType.QUIZ_GENERATE.value:
        # Quiz fast path — not fully supported in JSON mode (use /stream).
        # Return a simple response directing to streaming endpoint.
        return ConversationResponse(
            mode="entry",
            action="build",
            chat_response="Quiz generation is best experienced via the streaming endpoint. "
            "Use POST /api/conversation/stream for real-time question delivery.",
            conversation_id=req.conversation_id,
        )

    if intent == IntentType.CONTENT_CREATE.value:
        # Agent Path — not fully supported in JSON mode (use /stream).
        return ConversationResponse(
            mode="entry",
            action="build",
            chat_response="Content generation is best experienced via the streaming endpoint. "
            "Use POST /api/conversation/stream for real-time content delivery.",
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
                attachments=req.attachments if req.attachments else None,
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
            history_text=history_text,
        )

        # Missing dependent context → clarify (class first, then assignment)
        if resolve_result.missing_context:
            if "class" in resolve_result.missing_context:
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
            if "assignment" in resolve_result.missing_context:
                return ConversationResponse(
                    mode="entry",
                    action="clarify",
                    chat_response="Which assignment would you like to analyze?",
                    clarify_options=resolve_result.clarify_options or None,
                    resolved_entities=resolve_result.entities or None,
                    conversation_id=req.conversation_id,
                )

        if resolve_result.scope_mode == "none":
            # No entities mentioned — proceed normally
            blueprint, _model = await generate_blueprint(
                user_prompt=req.message,
                language=req.language,
                attachments=req.attachments if req.attachments else None,
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
            attachments=req.attachments if req.attachments else None,
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
    text = await chat_response(
        req.message, language=req.language,
        conversation_history=history_text,
        attachments=req.attachments,
        message_history=message_history,
    )
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
    history_text: str = "",
    message_history: list[ModelMessage] | None = None,
) -> ConversationResponse:
    """Handle follow-up-mode intents (existing blueprint context)."""

    if intent == "chat":
        # Page chat — answer about existing data
        text = await page_chat_response(
            req.message,
            blueprint=req.blueprint,
            page_context=req.page_context,
            language=req.language,
            attachments=req.attachments,
            message_history=message_history,
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
        attachments=req.attachments,
        message_history=message_history,
    )
    return ConversationResponse(
        mode="followup",
        action="chat",
        chat_kind="page",
        chat_response=text,
        conversation_id=req.conversation_id,
    )
