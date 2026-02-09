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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["conversation"])
_agent = NativeAgent()


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

    # Build agent deps
    class_id = (req.context or {}).get("classId") if req.context else None
    deps = AgentDeps(
        teacher_id=teacher_id,
        conversation_id=conversation_id,
        language=req.language,
        class_id=class_id,
        has_artifacts=req.artifacts is not None,
        context=req.context or {},
    )

    # Load message history for multi-turn context
    message_history = session.to_pydantic_messages()

    async def event_generator() -> AsyncGenerator[str, None]:
        text_parts: list[str] = []
        enc = DataStreamEncoder(text_sink=text_parts)
        _stream_ref: list = []  # capture stream for tool summary extraction
        tracker = ToolTracker()

        # Push conversationId to frontend via SSE (FP-4 contract)
        yield enc.data("conversation", {"conversationId": conversation_id})

        # Queue for tracker events to be yielded as SSE
        tracker_lines: asyncio.Queue[str] = asyncio.Queue()
        tracker_done = asyncio.Event()

        async def _consume_tracker():
            """Consume ToolTracker events and convert to SSE lines."""
            while not tracker_done.is_set() or not tracker.queue.empty():
                try:
                    event: ToolEvent = await asyncio.wait_for(
                        tracker.queue.get(), timeout=0.1
                    )
                except (asyncio.TimeoutError, TimeoutError):
                    continue

                # Convert tracker events to SSE lines
                if event.status == "running":
                    await tracker_lines.put(
                        enc.data("tool-progress", {
                            "toolName": event.tool,
                            "status": "running",
                        }, id=f"tp-{event.tool}")
                    )
                elif event.status == "done":
                    await tracker_lines.put(
                        enc.data("tool-progress", {
                            "toolName": event.tool,
                            "status": "done",
                            "duration_ms": event.duration_ms,
                        }, id=f"tp-{event.tool}")
                    )
                elif event.status == "error":
                    await tracker_lines.put(
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
                        await tracker_lines.put(
                            enc.data("quiz-question", {
                                "index": idx,
                                "question": q,
                            }, id=q_id)
                        )

        tracker_task = asyncio.create_task(_consume_tracker())

        try:
            async for stream in _agent.run_stream(
                message=req.message,
                deps=deps,
                message_history=message_history,
                tracker=tracker,
            ):
                _stream_ref.append(stream)
                msg_id = f"msg-{uuid.uuid4().hex[:12]}"
                async for line in adapt_stream(stream, enc, message_id=msg_id):
                    # Also drain any tracker lines that accumulated
                    while not tracker_lines.empty():
                        yield tracker_lines.get_nowait()
                    yield line
        except Exception as e:
            logger.exception("Stream error for conversation %s", conversation_id)
            yield enc.error(classify_stream_error(str(e)))
            yield enc.finish("error")

        # Signal tracker consumer to stop and drain remaining events
        tracker_done.set()
        await tracker_task
        while not tracker_lines.empty():
            yield tracker_lines.get_nowait()

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

    try:
        result = await _agent.run(
            message=req.message,
            deps=deps,
            message_history=message_history,
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
