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

                    if is_last and idx not in emitted_tool_start:
                        yield enc.text_end(text_id)

                elif isinstance(part, ToolCallPart):
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
                        call_id = part.tool_call_id or enc._id()
                        output = _serialize_tool_output(part.content)
                        yield enc.tool_output_available(call_id, output)

        # Close any open text parts
        for idx in text_started:
            if idx in text_ids and idx not in emitted_tool_start:
                pass  # Already closed above

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
