"""Stream adapter — PydanticAI events → Data Stream Protocol SSE.

Step 1.3 of AI native rewrite.  Converts PydanticAI's ``stream_responses()``
output into Vercel AI SDK Data Stream Protocol SSE lines consumed by the
frontend ``useChat`` hook.

Implementation is based on the Step 0.5 calibrated event mapping
(see ``docs/plans/stream-event-mapping.md``).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncIterator

from pydantic_ai.messages import (
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    ModelRequest,
)
from pydantic_ai.result import StreamedRunResult

from services.datastream import DataStreamEncoder

logger = logging.getLogger(__name__)


async def adapt_stream(
    stream: StreamedRunResult,
    enc: DataStreamEncoder,
    message_id: str | None = None,
) -> AsyncIterator[str]:
    """Convert PydanticAI stream into Data Stream Protocol SSE lines.

    Uses ``stream_responses()`` which yields ``(ModelResponse, is_last)`` tuples.
    We diff successive response snapshots to emit incremental SSE events.

    Args:
        stream: PydanticAI StreamedRunResult (inside async with context).
        enc: DataStreamEncoder instance for SSE formatting.
        message_id: Optional message ID for the start event.

    Yields:
        SSE-formatted strings ready for StreamingResponse.
    """
    yield enc.start(message_id=message_id)
    yield enc.start_step()

    # Track state for incremental diffing
    prev_text_len: dict[int, int] = {}  # part_index → last seen text length
    emitted_tool_start: set[int] = set()  # part indices where we emitted tool-input-start
    emitted_tool_input: set[int] = set()  # part indices where we emitted tool-input-available
    text_ids: dict[int, str] = {}  # part_index → text-id for SSE
    text_started: set[int] = set()  # part indices where we emitted text-start
    text_ended: set[int] = set()  # part indices where we already emitted text-end

    error_occurred = False

    try:
        async for response, is_last in stream.stream_responses():
            for idx, part in enumerate(response.parts):
                if isinstance(part, TextPart):
                    # ── Text streaming ──
                    text_id = text_ids.setdefault(idx, f"t-{idx}")

                    if idx not in text_started:
                        yield enc.text_start(text_id)
                        text_started.add(idx)

                    current_len = len(part.content)
                    prev_len = prev_text_len.get(idx, 0)

                    if current_len > prev_len:
                        delta = part.content[prev_len:]
                        yield enc.text_delta(text_id, delta)
                        prev_text_len[idx] = current_len

                elif isinstance(part, ToolCallPart):
                    # Close any preceding text parts before starting tool call
                    for tidx in text_started - text_ended:
                        yield enc.text_end(text_ids[tidx])
                        text_ended.add(tidx)

                    # ── Tool call streaming ──
                    call_id = part.tool_call_id or f"tc-{idx}"

                    if idx not in emitted_tool_start:
                        yield enc.tool_input_start(call_id, part.tool_name)
                        emitted_tool_start.add(idx)

                    # Emit tool-input-available when args are complete
                    if part.args and idx not in emitted_tool_input:
                        args = part.args if isinstance(part.args, dict) else {}
                        yield enc.tool_input_available(call_id, part.tool_name, args)
                        emitted_tool_input.add(idx)

        # After streaming completes, emit tool results from new_messages
        for msg in stream.new_messages():
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, ToolReturnPart):
                        call_id = part.tool_call_id or uuid.uuid4().hex[:8]
                        output = _serialize_tool_output(part.content)
                        yield enc.tool_output_available(call_id, output)

        # Close any text parts still open after stream completes
        for tidx in text_started - text_ended:
            yield enc.text_end(text_ids[tidx])
            text_ended.add(tidx)

    except Exception as e:
        error_occurred = True
        logger.exception("Error during stream adaptation")
        yield enc.error(str(e))

    finally:
        yield enc.finish_step()
        yield enc.finish("error" if error_occurred else "stop")


def _serialize_tool_output(content: Any) -> Any:
    """Ensure tool output is JSON-serializable."""
    if isinstance(content, str):
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return content
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        return content
    return str(content)


def extract_tool_calls_summary(result: Any) -> str | None:
    """Extract a brief summary of tool calls from a PydanticAI result.

    Inspects ``result.new_messages()`` (or ``result.all_messages()``) for
    ToolCallPart and ToolReturnPart to build a compact summary like::

        generate_quiz_questions(topic=英语, count=5) → ok; patch_artifact(op=replace) → ok

    Returns ``None`` if no tool calls were made.
    """
    try:
        messages = result.new_messages() if hasattr(result, "new_messages") else []
    except Exception:
        try:
            messages = result.all_messages() if hasattr(result, "all_messages") else []
        except Exception:
            return None

    calls: list[str] = []
    # Collect tool calls and their results
    call_map: dict[str, str] = {}  # tool_call_id → tool_name(args_summary)
    result_map: dict[str, str] = {}  # tool_call_id → status

    for msg in messages:
        if not hasattr(msg, "parts"):
            continue
        for part in msg.parts:
            if isinstance(part, ToolCallPart):
                call_id = part.tool_call_id or ""
                args_str = ""
                if isinstance(part.args, dict) and part.args:
                    # Keep only first 2 args for brevity
                    items = list(part.args.items())[:2]
                    args_str = ", ".join(f"{k}={v}" for k, v in items)
                call_map[call_id] = f"{part.tool_name}({args_str})"
            elif isinstance(part, ToolReturnPart):
                call_id = part.tool_call_id or ""
                status = "ok"
                if isinstance(part.content, dict):
                    status = str(part.content.get("status", "ok"))
                elif isinstance(part.content, str) and "error" in part.content.lower():
                    status = "error"
                result_map[call_id] = status

    for call_id, call_desc in call_map.items():
        status = result_map.get(call_id, "ok")
        calls.append(f"{call_desc} → {status}")

    return "; ".join(calls) if calls else None
