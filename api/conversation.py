"""Conversation API — thin gateway for AI native runtime.

This is a ~100-line thin gateway that:
- Validates requests (ConversationRequest)
- Manages conversation_id lifecycle
- Calls NativeAgent.run_stream() / run()
- Adapts events via stream_adapter → Data Stream Protocol SSE

Does NOT: route intents, classify messages, select tools, maintain state machines.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from models.conversation import ConversationRequest
from services.multimodal import build_user_content, has_attachments
from services.conversation_store import (
    ConversationSession,
    generate_conversation_id,
    get_conversation_store,
)
from models.errors import classify_stream_error
from services.datastream import DataStreamEncoder
from services.tool_tracker import ToolTracker, ToolEvent
from agents.native_agent import AgentDeps, NativeAgent
from services.stream_adapter import adapt_stream, extract_tool_calls_summary
from services.artifact_store import get_artifact_store
from services.tool_summaries import summarize_tool_result

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["conversation"])
_agent = NativeAgent()


def _rehydrate_artifacts(
    conversation_id: str,
    artifact_type: str | None,
    artifacts: dict | None,
) -> None:
    """Inject frontend-provided artifact data into the in-memory store.

    When the user resumes a historical conversation, the frontend sends the
    last artifact content in ``req.artifacts``.  The Python in-memory store
    doesn't persist across restarts, so we need to re-inject the data so
    that ``get_artifact`` / ``patch_artifact`` / ``regenerate_from_previous``
    can find it.
    """
    if not artifacts or not artifact_type:
        return

    store = get_artifact_store()

    # Already have an artifact for this conversation → skip
    if store.get_latest_for_conversation(conversation_id) is not None:
        return

    content: str | dict | None = None
    content_format = "html"

    if artifact_type == "interactive":
        data = artifacts.get("interactive") or {}
        content = data.get("html", "")
        content_format = "html"
    elif artifact_type == "quiz":
        data = artifacts.get("quiz") or {}
        content = data
        content_format = "json"
    elif artifact_type == "document":
        data = artifacts.get("document") or {}
        content = data
        content_format = "html"
    elif artifact_type == "pptx":
        data = artifacts.get("pptx") or {}
        content = data
        content_format = "json"
    else:
        return

    if not content:
        return

    store.save_artifact(
        conversation_id=conversation_id,
        artifact_type=artifact_type,
        content_format=content_format,
        content=content,
    )
    logger.info(
        "Rehydrated %s artifact for conversation %s",
        artifact_type, conversation_id,
    )


# ── Instant acknowledgment text ────────────────────────────
# Emitted before the LLM stream begins so the user sees immediate
# feedback instead of a silent spinner while waiting for the first
# LLM token (~3-5 s) or tool execution (~30 s).

_ACK_ZH = {
    "generate": "好的，让我来处理您的请求…",
    "quiz":     "好的，正在为您生成题目…",
    "ppt":      "好的，正在为您准备 PPT…",
    "analyze":  "好的，正在为您分析数据…",
    "search":   "好的，正在搜索相关文档…",
    "modify":   "好的，正在为您修改内容…",
}
_ACK_EN = {
    "generate": "Sure, working on your request…",
    "quiz":     "Sure, generating questions for you…",
    "ppt":      "Sure, preparing your PPT…",
    "analyze":  "Sure, analyzing the data…",
    "search":   "Sure, searching documents…",
    "modify":   "Sure, modifying the content…",
}

_INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("quiz",     ["题", "quiz", "选择题", "填空题", "判断题", "试卷", "测试"]),
    ("ppt",      ["ppt", "PPT", "幻灯片", "slides", "演示"]),
    ("analyze",  ["分析", "成绩", "统计", "对比", "薄弱", "analyze", "score", "grade"]),
    ("search",   ["搜索", "查找", "文档", "资料", "search", "document"]),
    ("modify",   ["修改", "替换", "删除", "换", "改", "调整", "update", "replace", "edit"]),
]


def _build_ack(message: str, language: str = "zh") -> str:
    """Build a brief acknowledgment string based on the user message."""
    table = _ACK_EN if language.startswith("en") else _ACK_ZH

    for intent, keywords in _INTENT_KEYWORDS:
        if any(kw in message for kw in keywords):
            return table[intent]

    return table["generate"]


def _normalize_teacher_id(raw: str | None) -> str:
    """Normalize teacher_id, rejecting null-like values."""
    if raw is None:
        return ""
    value = str(raw).strip()
    if value.lower() in ("", "null", "undefined", "none"):
        return ""
    return value


@router.post("/conversation/stream")
async def conversation_stream(req: ConversationRequest):
    """SSE streaming endpoint — Data Stream Protocol."""
    teacher_id = _normalize_teacher_id(req.teacher_id)
    if not teacher_id:
        ctx_tid = (req.context or {}).get("teacherId", "")
        teacher_id = _normalize_teacher_id(ctx_tid)

    # Session management
    store = get_conversation_store()
    conversation_id = req.conversation_id or generate_conversation_id()
    session = await store.get(conversation_id)
    if session is None:
        session = ConversationSession(conversation_id=conversation_id)

    # Record user turn
    session.add_user_turn(req.message)
    if req.context:
        session.merge_context(req.context)

    # Rehydrate artifacts from frontend when resuming historical conversations.
    # The in-memory store doesn't survive restarts, so the frontend sends the
    # last artifact content in req.artifacts for re-injection.
    _rehydrate_artifacts(conversation_id, req.artifact_type, req.artifacts)

    # Extract blueprint context from request
    blueprint_context = {}
    if req.context:
        if "blueprintId" in req.context:
            blueprint_context["blueprint_id"] = req.context["blueprintId"]

        if "resolvedEntities" in req.context:
            blueprint_context["resolved_entities"] = req.context["resolvedEntities"]

        if "outputHints" in req.context:
            blueprint_context["blueprint_hints"] = req.context["outputHints"]

    # Build agent deps — check both frontend payload AND in-memory store
    # to determine if the conversation has artifacts.  The frontend may
    # not re-send ``req.artifacts`` on every turn after the first generation.
    class_id = (req.context or {}).get("classId") if req.context else None
    store_has_artifact = (
        get_artifact_store().get_latest_for_conversation(conversation_id)
        is not None
    )
    deps = AgentDeps(
        teacher_id=teacher_id,
        conversation_id=conversation_id,
        language=req.language,
        class_id=class_id,
        has_artifacts=req.artifacts is not None or store_has_artifact,
        context={**(req.context or {}), **blueprint_context},
    )

    # Load message history for multi-turn context
    message_history = session.to_pydantic_messages()

    # Process attachments — enrich prompt with file content / images
    user_prompt = None
    if has_attachments(req.attachments):
        try:
            user_prompt = await build_user_content(req.message, req.attachments)
            logger.info(
                "Processed %d attachment(s) for conversation %s",
                len(req.attachments), conversation_id,
            )
        except Exception as exc:
            logger.warning("Failed to process attachments: %s; falling back to text-only", exc)

    async def event_generator() -> AsyncGenerator[str, None]:
        text_parts: list[str] = []
        enc = DataStreamEncoder(text_sink=text_parts)
        _stream_ref: list = []  # capture stream for tool summary extraction
        tracker = ToolTracker()

        # Push conversationId to frontend via SSE (FP-4 contract)
        yield enc.data("conversation", {"conversationId": conversation_id})

        # Immediate status event so the frontend can render a loading
        # indicator within milliseconds instead of waiting for the first
        # LLM token (~3-5 s) or tool execution (~30 s).
        yield enc.data("status", {"status": "processing"})

        # Merged output queue — both stream adapter and tracker write here.
        # This ensures tracker events (e.g. per-question quiz streaming) are
        # yielded immediately during tool execution, instead of waiting for
        # the next adapt_stream line (which blocks on stream_responses()).
        merged: asyncio.Queue[str | None] = asyncio.Queue()
        tracker_done = asyncio.Event()

        async def _consume_tracker():
            """Consume ToolTracker events and put SSE lines into merged queue."""
            while not tracker_done.is_set() or not tracker.queue.empty():
                try:
                    event: ToolEvent = await asyncio.wait_for(
                        tracker.queue.get(), timeout=0.1
                    )
                except (asyncio.TimeoutError, TimeoutError):
                    continue

                # Convert tracker events to SSE lines
                if event.status == "running":
                    await merged.put(
                        enc.data("tool-progress", {
                            "toolName": event.tool,
                            "status": "running",
                        }, id=f"tp-{event.tool}")
                    )
                elif event.status == "done":
                    payload: dict = {
                        "toolName": event.tool,
                        "status": "done",
                        "duration_ms": event.duration_ms,
                    }
                    # Extract human-readable summary from tool result
                    if event.data:
                        summary = summarize_tool_result(event.tool, event.data)
                        if summary:
                            payload["summary"] = summary["text"]
                            if summary.get("details"):
                                payload["details"] = summary["details"]
                    await merged.put(
                        enc.data("tool-progress", payload, id=f"tp-{event.tool}")
                    )
                elif event.status == "error":
                    await merged.put(
                        enc.data("tool-progress", {
                            "toolName": event.tool,
                            "status": "error",
                            "message": event.message,
                        }, id=f"tp-{event.tool}")
                    )
                elif event.status == "stream-item" and event.data:
                    # Real-time quiz question streaming
                    evt_name = event.data.get("event", "")
                    if evt_name == "quiz-question":
                        q = event.data.get("question", {})
                        idx = event.data.get("index", 0)
                        q_id = q.get("id", f"q-{idx}")
                        await merged.put(
                            enc.data("quiz-question", {
                                "index": idx,
                                "question": q,
                            }, id=q_id)
                        )

        async def _produce_stream():
            """Run agent stream and put SSE lines into merged queue."""
            try:
                async for stream in _agent.run_stream(
                    message=req.message,
                    deps=deps,
                    message_history=message_history,
                    tracker=tracker,
                    user_prompt=user_prompt,
                ):
                    _stream_ref.append(stream)
                    msg_id = f"msg-{uuid.uuid4().hex[:12]}"
                    async for line in adapt_stream(
                        stream, enc, message_id=msg_id, context=blueprint_context,
                    ):
                        await merged.put(line)
            except Exception as e:
                logger.exception("Stream error for conversation %s", conversation_id)
                await merged.put(enc.error(classify_stream_error(str(e))))
                await merged.put(enc.finish("error"))
            finally:
                await merged.put(None)  # sentinel: stream done

        tracker_task = asyncio.create_task(_consume_tracker())
        stream_task = asyncio.create_task(_produce_stream())

        # Yield from merged queue — tracker events arrive in real-time
        # even while adapt_stream is blocked on tool execution.
        while True:
            line = await merged.get()
            if line is None:
                break
            yield line

        # Signal tracker consumer to stop and drain remaining events
        tracker_done.set()
        await stream_task
        await tracker_task
        while not merged.empty():
            line = merged.get_nowait()
            if line is not None:
                yield line

        # Extract tool calls summary for multi-turn context
        tool_summary = None
        if _stream_ref:
            tool_summary = extract_tool_calls_summary(_stream_ref[0])

        # Save assistant response to session
        response_text = "".join(text_parts) if text_parts else ""
        session.add_assistant_turn(
            response_text[:6000],
            tool_calls_summary=tool_summary,
        )
        await store.save(session)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Conversation-Id": conversation_id,
            "x-vercel-ai-ui-message-stream": "v1",
        },
    )


@router.post("/conversation")
async def conversation_json(req: ConversationRequest):
    """JSON endpoint — non-streaming response."""
    teacher_id = _normalize_teacher_id(req.teacher_id)
    if not teacher_id:
        ctx_tid = (req.context or {}).get("teacherId", "")
        teacher_id = _normalize_teacher_id(ctx_tid)

    store = get_conversation_store()
    conversation_id = req.conversation_id or generate_conversation_id()
    session = await store.get(conversation_id)
    if session is None:
        session = ConversationSession(conversation_id=conversation_id)

    session.add_user_turn(req.message)
    if req.context:
        session.merge_context(req.context)

    _rehydrate_artifacts(conversation_id, req.artifact_type, req.artifacts)

    class_id = (req.context or {}).get("classId") if req.context else None
    deps = AgentDeps(
        teacher_id=teacher_id,
        conversation_id=conversation_id,
        language=req.language,
        class_id=class_id,
        has_artifacts=req.artifacts is not None,
        context=req.context or {},
    )

    message_history = session.to_pydantic_messages()

    # Process attachments
    user_prompt = None
    if has_attachments(req.attachments):
        try:
            user_prompt = await build_user_content(req.message, req.attachments)
        except Exception as exc:
            logger.warning("Failed to process attachments: %s; falling back to text-only", exc)

    try:
        result = await _agent.run(
            message=req.message,
            deps=deps,
            message_history=message_history,
            user_prompt=user_prompt,
        )
        # PydanticAI >= 0.1: result.output; older versions: result.data
        response_text = result.output if hasattr(result, "output") else str(result.data)

        # Extract tool call summary from result messages
        tool_summary = extract_tool_calls_summary(result)
    except Exception as e:
        logger.exception("Error in conversation %s", conversation_id)
        raise HTTPException(status_code=500, detail=str(e))

    session.add_assistant_turn(
        response_text[:6000],
        tool_calls_summary=tool_summary,
    )
    await store.save(session)

    return {
        "conversationId": conversation_id,
        "response": response_text,
    }
