"""FastAPI middleware — Request ID tracking (pure ASGI, streaming-safe)."""

from __future__ import annotations

import uuid
from typing import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestIdMiddleware:
    """Inject a unique request ID into every HTTP request/response.

    Uses pure ASGI implementation (no BaseHTTPMiddleware) to avoid
    breaking SSE streaming responses.

    If the client sends ``X-Request-ID``, it is reused; otherwise a short
    UUID is generated. The ID is returned in the response headers.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract request ID from headers
        headers = dict(scope.get("headers", []))
        request_id = headers.get(b"x-request-id", b"").decode() or str(uuid.uuid4())[:8]

        # Store in scope state for downstream access
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_request_id)
