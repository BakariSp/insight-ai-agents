"""Tool execution tracker — emits events for Agent Path tool calls.

Wraps tool functions to emit running/done/error events via an asyncio.Queue,
enabling the conversation layer to push real-time tool progress SSE events
to the frontend.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ContextVar so tools can access the current tracker without signature changes.
# This avoids polluting PydanticAI tool schemas with internal parameters.
current_tracker: contextvars.ContextVar[ToolTracker | None] = contextvars.ContextVar(
    "current_tracker", default=None
)


@dataclass
class ToolEvent:
    """A single tool execution event."""

    tool: str
    status: str  # "running" | "done" | "error" | "stream-item"
    message: str = ""
    duration_ms: float | None = None
    data: dict | None = None


class ToolTracker:
    """Track tool executions and emit events to a queue.

    Usage::

        tracker = ToolTracker()
        wrapped_fn = tracker.wrap(original_fn)
        # ... register wrapped_fn with agent ...
        # Consume events from tracker.queue in a separate task
    """

    # Generation tools that should only execute once per turn.
    # Prevents LLM from calling the same generation tool multiple times
    # with identical intent (a common hallucination pattern).
    DEDUP_TOOLS: frozenset[str] = frozenset({
        "generate_quiz_questions",
    })

    def __init__(self) -> None:
        self.queue: asyncio.Queue[ToolEvent] = asyncio.Queue()
        self._called_gen: set[str] = set()

    async def push(self, event: ToolEvent) -> None:
        """Push an arbitrary event (e.g. incremental quiz question)."""
        await self.queue.put(event)

    def wrap(self, fn):
        """Wrap a tool function to emit tracking events.

        Sets :data:`current_tracker` ContextVar so the tool implementation
        can push incremental progress events (e.g. per-question streaming)
        without changing its function signature.
        """

        tracker_ref = self

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            tool_name = fn.__name__

            # Dedup: prevent LLM from calling generation tools twice per turn
            if tool_name in tracker_ref.DEDUP_TOOLS:
                if tool_name in tracker_ref._called_gen:
                    logger.warning(
                        "Duplicate call to %s suppressed — already executed this turn",
                        tool_name,
                    )
                    return {
                        "status": "already_completed",
                        "message": (
                            f"{tool_name} was already executed this turn. "
                            "Use refine_quiz_questions to modify existing questions."
                        ),
                    }
                tracker_ref._called_gen.add(tool_name)

            await tracker_ref.queue.put(ToolEvent(tool=tool_name, status="running"))
            token = current_tracker.set(tracker_ref)
            start = time.monotonic()
            try:
                result = await fn(*args, **kwargs)
                ms = (time.monotonic() - start) * 1000
                await tracker_ref.queue.put(
                    ToolEvent(tool=tool_name, status="done", duration_ms=ms)
                )
                return result
            except Exception as e:
                ms = (time.monotonic() - start) * 1000
                await tracker_ref.queue.put(
                    ToolEvent(
                        tool=tool_name, status="error", message=str(e), duration_ms=ms
                    )
                )
                raise
            finally:
                current_tracker.reset(token)

        return wrapper
