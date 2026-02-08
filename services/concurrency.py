"""Global concurrency controls for LLM API calls and heavy endpoints.

Prevents overwhelming DashScope/OpenAI rate limits under load.
Uses asyncio.Semaphore to cap the number of *concurrent* outbound LLM
requests per worker process.

All middleware uses pure ASGI implementation (not BaseHTTPMiddleware)
to preserve SSE streaming compatibility.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

# ── Global LLM semaphore ─────────────────────────────────────
# Default: 10 concurrent LLM calls per worker.
# With 4 workers → up to 40 concurrent calls cluster-wide.
# DashScope qwen-max at 120 RPM: 40 concurrent × ~15s avg = ~160 RPM peak,
# so the semaphore plus natural latency keeps us under limits.

_MAX_CONCURRENT_LLM = 10
_llm_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-init to ensure semaphore is bound to the running event loop."""
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_LLM)
        logger.info("LLM concurrency semaphore initialized (max=%d)", _MAX_CONCURRENT_LLM)
    return _llm_semaphore


async def rate_limited_llm_call(
    func: Callable[..., Coroutine[Any, Any, Any]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Execute an async LLM function with concurrency limiting.

    Usage::

        result = await rate_limited_llm_call(litellm.acompletion, model=..., messages=...)
    """
    sem = _get_semaphore()
    async with sem:
        return await func(*args, **kwargs)


# ── Heavy endpoint concurrency middleware (pure ASGI) ─────────
# Limits concurrent requests to LLM-heavy endpoints (SSE streams, builds).
# Requests that exceed the limit receive 503 instead of queuing forever.

_MAX_CONCURRENT_HEAVY = 15  # per worker
_heavy_semaphore: asyncio.Semaphore | None = None

# Paths that count as "heavy" (LLM-intensive)
_HEAVY_PATHS = frozenset({
    "/api/conversation/stream",
    "/api/page/generate",
    "/api/page/patch",
    "/api/conversation",
    "/api/workflow/generate",
})


def _get_heavy_semaphore() -> asyncio.Semaphore:
    global _heavy_semaphore
    if _heavy_semaphore is None:
        _heavy_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_HEAVY)
        logger.info("Heavy endpoint semaphore initialized (max=%d)", _MAX_CONCURRENT_HEAVY)
    return _heavy_semaphore


class ConcurrencyLimitMiddleware:
    """Pure ASGI middleware — reject heavy requests when the worker is at capacity.

    Returns HTTP 503 with Retry-After header for overloaded endpoints.
    Lightweight endpoints (health, models, skills) pass through unaffected.

    Uses raw ASGI protocol (not BaseHTTPMiddleware) to preserve SSE
    streaming behavior.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path not in _HEAVY_PATHS:
            await self.app(scope, receive, send)
            return

        sem = _get_heavy_semaphore()

        # Try to acquire without blocking — if full, return 503
        if not sem._value:  # noqa: SLF001
            logger.warning("Concurrency limit reached for %s — returning 503", path)
            body = json.dumps(
                {"detail": "Server busy — too many concurrent requests. Please retry."}
            ).encode()
            await send({
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", b"5"),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })
            return

        async with sem:
            await self.app(scope, receive, send)
