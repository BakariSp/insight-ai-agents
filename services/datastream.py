"""Data Stream Protocol encoder — Vercel AI SDK UI Message Stream v1.

Encodes internal agent events into the Vercel AI SDK Data Stream Protocol
(SSE format) for consumption by ``useChat`` / AI Elements on the frontend.

Each method returns one or more SSE lines: ``"data: {json}\\n\\n"``

Reference: https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol

Required response header: ``x-vercel-ai-ui-message-stream: v1``
Termination marker: ``data: [DONE]\\n\\n``
"""

from __future__ import annotations

import json
import uuid
from typing import Any


class DataStreamEncoder:
    """Encode internal events into Vercel AI SDK Data Stream Protocol.

    Every public method returns a ready-to-yield SSE string.
    """

    @staticmethod
    def _sse(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

    @staticmethod
    def _id() -> str:
        return uuid.uuid4().hex[:8]

    # ── Message Control ──────────────────────────────────────────

    def start(self, message_id: str | None = None) -> str:
        return self._sse({"type": "start", "messageId": message_id or self._id()})

    def finish(self) -> str:
        return self._sse({"type": "finish"}) + "data: [DONE]\n\n"

    def start_step(self) -> str:
        return self._sse({"type": "start-step"})

    def finish_step(self) -> str:
        return self._sse({"type": "finish-step"})

    # ── Reasoning ────────────────────────────────────────────────

    def reasoning_start(self, reasoning_id: str) -> str:
        return self._sse({"type": "reasoning-start", "id": reasoning_id})

    def reasoning_delta(self, reasoning_id: str, delta: str) -> str:
        return self._sse(
            {"type": "reasoning-delta", "id": reasoning_id, "delta": delta}
        )

    def reasoning_end(self, reasoning_id: str) -> str:
        return self._sse({"type": "reasoning-end", "id": reasoning_id})

    # ── Text ─────────────────────────────────────────────────────

    def text_start(self, text_id: str) -> str:
        return self._sse({"type": "text-start", "id": text_id})

    def text_delta(self, text_id: str, delta: str) -> str:
        return self._sse({"type": "text-delta", "id": text_id, "delta": delta})

    def text_end(self, text_id: str) -> str:
        return self._sse({"type": "text-end", "id": text_id})

    # ── Tool Calls ───────────────────────────────────────────────

    def tool_input_start(self, call_id: str, name: str) -> str:
        return self._sse(
            {"type": "tool-input-start", "toolCallId": call_id, "toolName": name}
        )

    def tool_input_available(
        self, call_id: str, name: str, input_data: dict[str, Any]
    ) -> str:
        return self._sse(
            {
                "type": "tool-input-available",
                "toolCallId": call_id,
                "toolName": name,
                "input": input_data,
            }
        )

    def tool_output_available(self, call_id: str, output: Any) -> str:
        return self._sse(
            {"type": "tool-output-available", "toolCallId": call_id, "output": output}
        )

    # ── Custom Data ──────────────────────────────────────────────

    def data(self, name: str, payload: Any) -> str:
        return self._sse({"type": f"data-{name}", "data": payload})

    # ── Error ────────────────────────────────────────────────────

    def error(self, text: str) -> str:
        return self._sse({"type": "error", "errorText": text})


# ── Executor event mapping ───────────────────────────────────────


def map_executor_event(
    enc: DataStreamEncoder,
    event: dict[str, Any],
    *,
    last_call_id: str | None = None,
) -> tuple[list[str], str | None]:
    """Map an ExecutorAgent SSE event dict to Data Stream Protocol lines.

    The executor's internal event format (PHASE, TOOL_CALL, TOOL_RESULT,
    BLOCK_START, SLOT_DELTA, BLOCK_COMPLETE, COMPLETE, ERROR, DATA_ERROR)
    is translated to the corresponding Data Stream Protocol events.

    Returns:
        A tuple of ``(lines, updated_last_call_id)``.  ``lines`` is a list
        of SSE strings ready to yield.  ``updated_last_call_id`` should be
        passed back on subsequent calls so TOOL_RESULT can reference the
        correct tool-call ID.
    """
    t = event.get("type")
    lines: list[str] = []
    call_id = last_call_id

    if t == "PHASE":
        lines.append(enc.finish_step())
        lines.append(enc.start_step())
        rid = f"phase-{event.get('phase', 'unknown')}"
        lines.append(enc.reasoning_start(rid))
        lines.append(enc.reasoning_delta(rid, event.get("message", "")))
        lines.append(enc.reasoning_end(rid))

    elif t == "TOOL_CALL":
        call_id = enc._id()
        tool = event.get("tool", "unknown")
        args = event.get("args", {})
        lines.append(enc.tool_input_start(call_id, tool))
        lines.append(enc.tool_input_available(call_id, tool, args))

    elif t == "TOOL_RESULT":
        result_call_id = call_id or enc._id()
        output = event.get(
            "result", event.get("error", {"status": event.get("status")})
        )
        lines.append(enc.tool_output_available(result_call_id, output))

    elif t == "BLOCK_START":
        lines.append(
            enc.data(
                "block-start",
                {
                    "blockId": event.get("blockId"),
                    "componentType": event.get("componentType"),
                },
            )
        )

    elif t == "SLOT_DELTA":
        lines.append(
            enc.data(
                "slot-delta",
                {
                    "blockId": event.get("blockId"),
                    "slotKey": event.get("slotKey"),
                    "deltaText": event.get("deltaText"),
                },
            )
        )

    elif t == "BLOCK_COMPLETE":
        lines.append(enc.data("block-complete", {"blockId": event.get("blockId")}))

    elif t == "COMPLETE":
        lines.append(enc.data("page", event.get("result", {})))

    elif t in ("ERROR", "DATA_ERROR"):
        lines.append(enc.error(event.get("message", "Unknown error")))

    elif t == "MESSAGE":
        rid = f"msg-{enc._id()}"
        lines.append(enc.reasoning_start(rid))
        lines.append(enc.reasoning_delta(rid, event.get("message", "")))
        lines.append(enc.reasoning_end(rid))

    return lines, call_id
