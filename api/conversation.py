"""Conversation API — unified entry point for all user interactions.

Routes requests through the RouterAgent to determine intent, then dispatches
to the appropriate agent (ChatAgent, PlannerAgent, PageChatAgent, TeacherAgent)
based on the classified intent and confidence level.

Supports two modes:
- **Initial mode** (no blueprint): chat / quiz_generate / build / content_create / clarify
- **Follow-up mode** (with blueprint): chat / refine / rebuild

Three execution paths:
- **Skill Path**: quiz_generate → single LLM call (~5s)
- **Blueprint Path**: build_workflow → Blueprint + Executor pipeline (~100s)
- **Agent Path**: content_create → PydanticAI Agent + tool-use loop (~10-60s)

Endpoints:
- ``POST /api/conversation``         — JSON response (legacy, backward-compat)
- ``POST /api/conversation/stream``  — SSE Data Stream Protocol (Activity Stream)
"""

from __future__ import annotations

import logging
import re
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
from models.entity import EntityType
from services.clarify_builder import build_clarify_options
from pydantic_ai.messages import ModelMessage
from services.conversation_store import (
    ConversationSession,
    generate_conversation_id,
    get_conversation_store,
)
from config.settings import get_settings
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

        is_followup = req.blueprint is not None

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
        if is_followup:
            async for line in _stream_followup(enc, req, intent, router_result, history_text, message_history):
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
        session.add_assistant_turn(response_summary, action=intent)
        session.last_intent = intent
        session.last_action = intent
        if req.context:
            session.merge_context(req.context)
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

    # ── Quiz Generate (Skill fast path) ──
    if intent == IntentType.QUIZ_GENERATE.value:
        async for line in _stream_quiz_with_unified_fallback(
            enc, req, router_result, history_text, message_history
        ):
            yield line
        return

    # ── Content Create (Agent Path) ──
    if intent == IntentType.CONTENT_CREATE.value:
        agent_message = _compose_content_request_after_clarify(session, req.message)
        async for line in _stream_agent_mode(
            enc, req, router_result,
            agent_message=agent_message,
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
    return await generate_quiz_questions(
        topic=str(params.get("topic", "") or ""),
        count=int(params.get("count", 10) or 10),
        difficulty=str(params.get("difficulty", "medium") or "medium"),
        types=params.get("types"),
        subject=str(params.get("subject", "") or ""),
        grade=str(params.get("grade", "") or ""),
        context="",
        weakness_focus=params.get("weakness_focus"),
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


async def _stream_agent_mode(
    enc: DataStreamEncoder,
    req: ConversationRequest,
    router_result: RouterResult,
    agent_message: str | None = None,
    history_text: str = "",
    message_history: list[ModelMessage] | None = None,
    action_payload: dict | None = None,
    skip_teacher_context: bool = False,
) -> AsyncGenerator[str, None]:
    """Agent Path — LLM + Tools free orchestration for content generation.

    The PydanticAI Agent autonomously decides which tools to call based on the
    teacher's request.  Supports lesson plans, slides, worksheets, feedback,
    translations, and any other content generation task.

    Includes automatic fallback: if the primary model fails (connection error,
    rate limit, auth), retries with the next model in the tier's fallback chain.

    When the agent calls ``request_interactive_content``, the three-stream
    parallel generator is launched after the agent completes, yielding
    progressive HTML/CSS/JS delta events.
    """
    import asyncio as _asyncio

    from agents.provider import get_model_chain_for_tier
    from agents.teacher_agent import create_teacher_agent
    from services.tool_tracker import ToolTracker, ToolEvent

    # 1. Tell frontend we're in agent mode
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

    # 2. Get teacher context (fast, no LLM)
    if skip_teacher_context:
        teacher_context = {"teacher_id": req.teacher_id, "classes": []}
    else:
        teacher_context = await _get_teacher_context(req.teacher_id)

    # 3. Prepare agent input (enrich with attachments)
    from services.multimodal import build_user_content, has_attachments
    agent_input_text = agent_message or req.message
    agent_input_text = _apply_ppt_execution_directive(agent_input_text, history_text)
    agent_input: str | list = agent_input_text
    if req.attachments and has_attachments(req.attachments):
        agent_input = await build_user_content(agent_input_text, req.attachments)

    # 4. Run Agent with fallback chain
    tier = router_result.model_tier
    if hasattr(tier, "value"):
        tier = tier.value
    model_chain = get_model_chain_for_tier(tier)

    tid = enc._id()
    yield enc.start_step()
    settings = get_settings()
    last_error = None

    # Tool tracker for real-time progress events
    tracker = ToolTracker()

    for attempt, model_name in enumerate(model_chain):
        try:
            saw_tool_progress = False
            emitted_ppt_artifact = False
            agent = create_teacher_agent(
                teacher_context=teacher_context,
                suggested_tools=router_result.suggested_tools,
                model_tier=tier,
                _override_model=model_name if attempt > 0 else None,
                tool_tracker=tracker,
            )

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

            # Run agent stream + tool tracker concurrently via merged queue
            merged_queue: _asyncio.Queue[tuple[str, object]] = _asyncio.Queue()
            agent_done = _asyncio.Event()
            _agent_messages_holder: list[list[ModelMessage]] = []

            async def _agent_runner():
                try:
                    async with agent.run_stream(
                        agent_input,
                        message_history=message_history or [],
                        model_settings={"max_tokens": settings.agent_max_tokens},
                    ) as stream_result:
                        await merged_queue.put(("text-start", tid))
                        async for chunk in stream_result.stream_text(delta=True):
                            await merged_queue.put(("text-delta", chunk))
                        # Capture full message graph before stream context exits.
                        _agent_messages_holder.append(stream_result.all_messages())
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
                # Drain remaining events
                while not tracker.queue.empty():
                    event = tracker.queue.get_nowait()
                    await merged_queue.put(("tool-progress", event))

            runner_task = _asyncio.create_task(_agent_runner())
            monitor_task = _asyncio.create_task(_tool_monitor())

            last_heartbeat = time.monotonic()
            streamed_reply_parts: list[str] = []

            while True:
                if runner_task.done() and monitor_task.done() and merged_queue.empty():
                    break
                try:
                    msg_type, payload = await _asyncio.wait_for(merged_queue.get(), timeout=5.0)
                except _asyncio.TimeoutError:
                    now = time.monotonic()
                    if now - last_heartbeat > _SSE_HEARTBEAT_INTERVAL:
                        yield ": heartbeat\n\n"
                        last_heartbeat = now
                    continue

                if msg_type == "text-start":
                    yield enc.text_start(str(payload))
                elif msg_type == "text-delta":
                    delta_text = str(payload)
                    streamed_reply_parts.append(delta_text)
                    yield enc.text_delta(tid, delta_text)
                elif msg_type == "text-end":
                    yield enc.text_end(tid)
                elif msg_type == "tool-progress":
                    if isinstance(payload, ToolEvent):
                        saw_tool_progress = True
                        yield enc.data("tool-progress", {
                            "tool": payload.tool,
                            "status": payload.status,
                            "message": payload.message,
                            "duration_ms": payload.duration_ms,
                        })
                elif msg_type == "error":
                    raise payload  # type: ignore[misc]

                last_heartbeat = time.monotonic()

            await runner_task
            await monitor_task

            agent_messages = _agent_messages_holder[0] if _agent_messages_holder else []

            # 5. Check tool call results and push structured events
            # Also detect request_interactive_content for three-stream follow-up
            interactive_plan = None
            for call in agent_messages:
                if hasattr(call, "parts"):
                    for part in call.parts:
                        if hasattr(part, "tool_name") and hasattr(part, "content"):
                            if part.tool_name == "request_interactive_content":
                                interactive_plan = part.content
                            else:
                                events = _build_tool_result_events(
                                    enc, part.tool_name, part.content
                                )
                                if events and part.tool_name in (
                                    "propose_pptx_outline",
                                    "generate_pptx",
                                ):
                                    emitted_ppt_artifact = True
                                for event in events:
                                    yield event

            # 6. If agent planned interactive content, launch three-stream generation
            if interactive_plan and isinstance(interactive_plan, dict):
                from skills.interactive_skill import generate_interactive_stream

                async for event in generate_interactive_stream(
                    interactive_plan, teacher_context
                ):
                    if event["type"] == "start":
                        yield enc.data("interactive-content-start", event)
                    elif event["type"].endswith("-delta"):
                        yield enc.data(f"interactive-{event['type']}", {
                            "content": event["content"],
                        })
                    elif event["type"].endswith("-complete") and event["type"] != "complete":
                        phase = event["type"].replace("-complete", "")
                        yield enc.data(f"interactive-{phase}-complete", {})
                    elif event["type"] == "complete":
                        yield enc.data("interactive-content", {
                            "html": event.get("html", ""),
                            "css": event.get("css", ""),
                            "js": event.get("js", ""),
                            "title": event.get("title", "Interactive Content"),
                            "description": event.get("description", ""),
                            "preferredHeight": event.get("preferredHeight", 500),
                        })

            reply_text = "".join(streamed_reply_parts)
            ppt_intent_for_turn = _is_ppt_request(f"{history_text}\n{agent_input_text}")
            ppt_confirmation_for_turn = _is_ppt_confirmation(
                f"{history_text}\n{agent_input_text}"
            )
            promised_outline = _looks_like_outline_promise(reply_text)
            if (ppt_intent_for_turn or promised_outline) and not emitted_ppt_artifact:
                outline_payload = _build_fallback_ppt_outline(
                    f"{history_text}\n{agent_input_text}"
                )
                if outline_payload is not None and ppt_confirmation_for_turn:
                    logger.warning(
                        "[AgentPath] PPT confirmation had no file artifact; generating fallback PPT."
                    )
                    try:
                        from tools.render_tools import generate_pptx

                        fallback_slides = _outline_to_fallback_slides(outline_payload)
                        fallback_file = await generate_pptx(
                            slides=fallback_slides,
                            title=str(outline_payload.get("title") or "Presentation"),
                            template="education",
                        )
                        if not saw_tool_progress:
                            yield enc.data(
                                "tool-progress",
                                {
                                    "tool": "generate_pptx",
                                    "status": "done",
                                    "message": "Fallback PPT generated",
                                },
                            )
                        for event in _build_tool_result_events(
                            enc, "generate_pptx", fallback_file
                        ):
                            yield event
                    except Exception:
                        logger.exception(
                            "[AgentPath] Fallback PPT generation failed; emitting outline."
                        )
                        yield enc.data(
                            "tool-progress",
                            {
                                "tool": "propose_pptx_outline",
                                "status": "done",
                                "message": "Fallback outline generated",
                            },
                        )
                        yield enc.data("pptx-outline", outline_payload)
                elif outline_payload is not None:
                    logger.warning(
                        "[AgentPath] PPT request returned no tool artifact; emitting fallback outline."
                    )
                    if not saw_tool_progress:
                        yield enc.data(
                            "tool-progress",
                            {
                                "tool": "propose_pptx_outline",
                                "status": "done",
                                "message": "Fallback outline generated",
                            },
                        )
                    yield enc.data("pptx-outline", outline_payload)

            last_error = None
            break  # success — exit the fallback loop

        except Exception as e:
            last_error = f"{model_name}: {type(e).__name__}: {e}"
            is_provider_error = _is_provider_error(e)
            if is_provider_error and attempt < len(model_chain) - 1:
                logger.warning(
                    "Agent model %s failed (provider error), will try fallback: %s",
                    model_name, e,
                )
                continue  # try next model in chain
            else:
                # Non-provider error or last model in chain — give up
                logger.exception("Agent path error (attempt %d/%d)", attempt + 1, len(model_chain))
                yield enc.error(f"Agent path error: {e}")
                break

    yield enc.finish_step()


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
    if last_action != IntentType.CLARIFY.value:
        return current_message

    original_request = ""
    for idx in range(last_assistant_idx - 1, -1, -1):
        turn = turns[idx]
        if turn.role == "user" and turn.content.strip():
            original_request = turn.content.strip()
            break

    if not original_request:
        return current_message

    logger.info(
        "[Continuity] Expanding post-clarify content request. original=%.80s details=%.80s",
        original_request,
        current_message,
    )
    return (
        "Continue the previous request with the provided details and generate the final output now.\n\n"
        f"Original request:\n{original_request}\n\n"
        f"Additional details from user:\n{current_message}\n\n"
        "Do not only acknowledge. Produce the complete deliverable directly."
    )


_PPT_REQUEST_RE = re.compile(
    r"(?:\bppt\b|课件|投影片|幻灯片|slides?|presentation|deck)",
    re.IGNORECASE,
)
_PPT_CONFIRM_RE = re.compile(
    r"(?:"
    r"(?:confirm|confirmed|approve|approved|go ahead|proceed|finalize)"
    r"|(?:确认|同意|可以|开始|继续|生成|制作).{0,6}(?:ppt|课件|幻灯片)"
    r"|(?:确认生成|开始生成|继续生成)"
    r")",
    re.IGNORECASE,
)
_OUTLINE_PROMISE_RE = re.compile(
    r"(?:outline|大纲|审阅|先.*(设计|提供).*(课件|PPT)|review)",
    re.IGNORECASE,
)


def _is_ppt_request(text: str) -> bool:
    return bool(text and _PPT_REQUEST_RE.search(text))


def _is_ppt_confirmation(text: str) -> bool:
    return bool(text and _PPT_CONFIRM_RE.search(text))


def _apply_ppt_execution_directive(message: str, history_text: str = "") -> str:
    """Inject a strict tool-use instruction for PPT requests.

    This reduces cases where the model says it will draft an outline but
    never calls ``propose_pptx_outline``/``generate_pptx``.
    """
    joined = f"{history_text}\n{message}".strip()
    if not _is_ppt_request(joined):
        return message

    if _is_ppt_confirmation(joined):
        return (
            f"{message}\n\n"
            "[Execution Requirement]\n"
            "The teacher has explicitly confirmed PPT generation.\n"
            "In this turn you MUST call generate_pptx directly and return the file artifact.\n"
            "Do NOT call propose_pptx_outline again."
        )

    return (
        f"{message}\n\n"
        "[Execution Requirement]\n"
        "This is a PPT/slides request. In this turn you MUST call a PPT tool.\n"
        "- If the teacher is still deciding structure: call propose_pptx_outline.\n"
        "- If the teacher already confirmed generation: call generate_pptx.\n"
        "Do not reply with outline text only."
    )


def _looks_like_outline_promise(text: str) -> bool:
    return bool(text and _OUTLINE_PROMISE_RE.search(text))


def _build_fallback_ppt_outline(message: str) -> dict | None:
    """Build a minimal outline payload when no PPT tool artifact was emitted."""
    if not _is_ppt_request(message):
        return None

    title = "Mathematics Lesson PPT"
    topic_match = re.search(r"(概率统计|函数|几何|代数|微积分|统计)", message)
    if topic_match:
        title = f"{topic_match.group(1)} Lesson PPT"

    outline = [
        {
            "title": "课程目标与导入",
            "key_points": ["学习目标", "知识背景", "课堂安排"],
        },
        {
            "title": "核心概念与公式推导",
            "key_points": ["概念定义", "公式推导步骤", "常见误区"],
        },
        {
            "title": "例题演示",
            "key_points": ["典型例题1", "典型例题2", "解题策略"],
        },
        {
            "title": "课堂练习与互动",
            "key_points": ["分层练习", "即时反馈", "纠错讲解"],
        },
        {
            "title": "总结与作业",
            "key_points": ["重点回顾", "方法总结", "课后任务"],
        },
    ]

    return {
        "title": title,
        "outline": outline,
        "totalSlides": len(outline),
        "estimatedDuration": 45,
        "requiresConfirmation": True,
    }


def _outline_to_fallback_slides(outline_payload: dict) -> list[dict]:
    """Convert fallback outline payload to generate_pptx-compatible slides."""
    title = str(outline_payload.get("title") or "Presentation")
    outline = outline_payload.get("outline")
    if not isinstance(outline, list):
        outline = []

    slides: list[dict] = [
        {
            "layout": "title",
            "title": title,
            "body": "Auto-generated by Insight AI",
            "notes": "Generated from confirmed outline fallback.",
        }
    ]

    for section in outline:
        if not isinstance(section, dict):
            continue
        section_title = str(section.get("title") or "Section")
        key_points = section.get("key_points")
        points: list[str] = []
        if isinstance(key_points, list):
            for item in key_points[:8]:
                if item is None:
                    continue
                clean = str(item).strip()
                if clean:
                    points.append(clean)
        body = "\n".join(points) if points else "Key ideas and teaching focus."
        slides.append(
            {
                "layout": "content",
                "title": section_title,
                "body": body,
                "notes": f"Explain: {section_title}",
            }
        )

    max_slides = max(2, get_settings().pptx_max_slides)
    return slides[:max_slides]


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

    elif tool_name == "propose_pptx_outline":
        events.append(enc.data("pptx-outline", {
            "title": result.get("title", ""),
            "outline": result.get("outline", []),
            "totalSlides": result.get("totalSlides", 0),
            "estimatedDuration": result.get("estimatedDuration", 0),
            "requiresConfirmation": True,
        }))

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
