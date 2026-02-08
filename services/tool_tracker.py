"""Tool execution tracker — emits events for Agent Path tool calls.

Wraps tool functions to emit running/done/error events via an asyncio.Queue,
enabling the conversation layer to push real-time tool progress SSE events
to the frontend.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ToolEvent:
    """A single tool execution event."""

    tool: str
    status: str  # "running" | "done" | "error"
    message: str = ""
    duration_ms: float | None = None


class ToolTracker:
    """Track tool executions and emit events to a queue.

    Usage::

        tracker = ToolTracker()
        wrapped_fn = tracker.wrap(original_fn)
        # ... register wrapped_fn with agent ...
        # Consume events from tracker.queue in a separate task
    """

    def __init__(self) -> None:
        self.queue: asyncio.Queue[ToolEvent] = asyncio.Queue()

    def wrap(self, fn):
        """Wrap a tool function to emit tracking events."""

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            tool_name = fn.__name__
            await self.queue.put(ToolEvent(tool=tool_name, status="running"))
            start = time.monotonic()
            try:
                result = await fn(*args, **kwargs)
                ms = (time.monotonic() - start) * 1000
                await self.queue.put(
                    ToolEvent(tool=tool_name, status="done", duration_ms=ms)
                )
                return result
            except Exception as e:
                ms = (time.monotonic() - start) * 1000
                await self.queue.put(
                    ToolEvent(
                        tool=tool_name, status="error", message=str(e), duration_ms=ms
                    )
                )
                raise

        return wrapper
