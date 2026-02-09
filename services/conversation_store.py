"""Conversation session store — server-side memory for multi-turn conversations.

Provides an abstract interface for session storage with an in-memory
implementation.  The interface is designed for easy swap to Redis later.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

logger = logging.getLogger(__name__)

# Modern LLMs support 50k+ token context — be generous with per-turn storage.
MAX_TURN_CHARS = 6000

# ── Data Models ──────────────────────────────────────────────


class ConversationTurn(BaseModel):
    """A single turn in a conversation."""

    role: str  # "user" or "assistant"
    content: str
    action: str | None = None  # Router action (e.g. "clarify", "build")
    tool_calls_summary: str | None = None  # "tool1(args), tool2(args)" for LLM context
    attachment_count: int = 0  # Number of image/file attachments in this turn
    timestamp: float = Field(default_factory=time.time)


class ConversationSession(BaseModel):
    """Server-side session state for a conversation."""

    conversation_id: str
    turns: list[ConversationTurn] = Field(default_factory=list)
    accumulated_context: dict[str, Any] = Field(default_factory=dict)
    last_intent: str | None = None
    last_action: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def add_user_turn(self, message: str, attachment_count: int = 0) -> None:
        """Record a user message."""
        self.turns.append(ConversationTurn(
            role="user",
            content=message[:MAX_TURN_CHARS],
            attachment_count=attachment_count,
        ))
        self.updated_at = time.time()

    def add_assistant_turn(
        self,
        response_summary: str,
        action: str | None = None,
        tool_calls_summary: str | None = None,
    ) -> None:
        """Record an assistant response with its action type and tool calls.

        Args:
            response_summary: Text output from the assistant.
            action: Router action label (e.g. "clarify", "build").
            tool_calls_summary: Brief summary of tool calls made, e.g.
                ``"generate_quiz_questions(topic=英语语法, count=5) → ok"``.
                Included in message history so the LLM knows what tools
                were used in prior turns and avoids redundant calls.
        """
        self.turns.append(ConversationTurn(
            role="assistant",
            content=response_summary[:MAX_TURN_CHARS],
            action=action,
            tool_calls_summary=tool_calls_summary,
        ))
        self.updated_at = time.time()

    def merge_context(self, new_context: dict[str, Any]) -> None:
        """Merge new structured context into accumulated context.

        Current-request values overwrite existing keys.
        Nested dicts are shallow-merged one level deep.
        """
        for key, value in new_context.items():
            if (
                isinstance(value, dict)
                and isinstance(self.accumulated_context.get(key), dict)
            ):
                self.accumulated_context[key].update(value)
            else:
                self.accumulated_context[key] = value
        self.updated_at = time.time()

    def recent_turns(self, n: int = 10) -> list[ConversationTurn]:
        """Return the last *n* turns."""
        return self.turns[-n:]

    def format_history_for_prompt(self, max_turns: int = 10) -> str:
        """Format recent history as concise text for prompt injection.

        Returns an empty string if there are no previous turns.
        Only includes turns *before* the current (latest) user message
        so the router sees prior context, not the message it is classifying.
        """
        # Exclude the last turn if it's the current user message being classified
        turns_for_context = self.turns[:-1] if self.turns else []
        recent = turns_for_context[-max_turns:]
        if not recent:
            return ""

        lines: list[str] = []
        for turn in recent:
            prefix = "USER" if turn.role == "user" else "ASSISTANT"
            action_tag = f"[{turn.action}] " if turn.action else ""
            content = turn.content[:2000]
            lines.append(f"{prefix}: {action_tag}{content}")

        return "\n".join(lines)

    def to_pydantic_messages(self, max_turns: int = 20) -> list[ModelMessage]:
        """Convert recent turns into PydanticAI ModelMessage objects.

        This provides proper multi-turn context to ``agent.run(message_history=...)``,
        giving the LLM structured user/assistant message roles instead of
        plain-text history injection.

        For assistant turns that include ``tool_calls_summary``, the summary
        is prepended to the response text so the LLM sees what tools were
        previously invoked and avoids redundant calls (e.g. re-generating
        when it should patch).

        Excludes the current (latest) user turn, as that will be passed
        as the ``user_prompt`` argument to ``agent.run()``.
        """
        turns_for_context = self.turns[:-1] if self.turns else []
        recent = turns_for_context[-max_turns:]
        if not recent:
            return []

        messages: list[ModelMessage] = []
        for turn in recent:
            if turn.role == "user":
                messages.append(
                    ModelRequest(parts=[UserPromptPart(content=turn.content)])
                )
            else:
                content = turn.content
                if turn.tool_calls_summary:
                    content = f"[Tools used: {turn.tool_calls_summary}]\n{content}"
                messages.append(
                    ModelResponse(parts=[TextPart(content=content)])
                )
        return messages


# ── Abstract Interface ───────────────────────────────────────


class ConversationStore(ABC):
    """Abstract conversation store — implement for different backends."""

    @abstractmethod
    async def get(self, conversation_id: str) -> ConversationSession | None:
        """Retrieve a session by ID.  Returns None if not found or expired."""
        ...

    @abstractmethod
    async def save(self, session: ConversationSession) -> None:
        """Persist a session (create or update)."""
        ...

    @abstractmethod
    async def delete(self, conversation_id: str) -> None:
        """Remove a session."""
        ...

    @abstractmethod
    async def cleanup_expired(self) -> int:
        """Remove all expired sessions.  Returns count removed."""
        ...


# ── In-Memory Implementation ────────────────────────────────


class InMemoryConversationStore(ConversationStore):
    """Thread-safe in-memory store with TTL expiration.

    Suitable for single-instance deployments (~10 concurrent users).
    """

    def __init__(self, ttl_seconds: int = 1800):
        self._store: dict[str, ConversationSession] = {}
        self._ttl = ttl_seconds

    def _is_expired(self, session: ConversationSession) -> bool:
        return (time.time() - session.updated_at) > self._ttl

    async def get(self, conversation_id: str) -> ConversationSession | None:
        session = self._store.get(conversation_id)
        if session is None:
            return None
        if self._is_expired(session):
            del self._store[conversation_id]
            logger.debug("Session expired: %s", conversation_id)
            return None
        return session

    async def save(self, session: ConversationSession) -> None:
        self._store[session.conversation_id] = session

    async def delete(self, conversation_id: str) -> None:
        self._store.pop(conversation_id, None)

    async def cleanup_expired(self) -> int:
        now = time.time()
        expired = [
            cid for cid, s in self._store.items()
            if (now - s.updated_at) > self._ttl
        ]
        for cid in expired:
            del self._store[cid]
        if expired:
            logger.info("Cleaned up %d expired conversation sessions", len(expired))
        return len(expired)

    @property
    def size(self) -> int:
        """Number of sessions currently stored (may include expired)."""
        return len(self._store)


# ── Redis Implementation ─────────────────────────────────────


class RedisConversationStore(ConversationStore):
    """Redis-backed store with automatic TTL expiration.

    Supports multi-worker deployments.  Sessions are serialized as JSON
    and stored with a Redis TTL matching ``conversation_ttl``.
    """

    _KEY_PREFIX = "conv:"

    def __init__(self, redis_url: str, ttl_seconds: int = 1800):
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=10,
            socket_timeout=10,
        )
        self._ttl = ttl_seconds

    def _key(self, conversation_id: str) -> str:
        return f"{self._KEY_PREFIX}{conversation_id}"

    async def get(self, conversation_id: str) -> ConversationSession | None:
        data = await self._redis.get(self._key(conversation_id))
        if data is None:
            return None
        try:
            return ConversationSession.model_validate_json(data)
        except Exception:
            logger.warning("Failed to deserialize session: %s", conversation_id)
            return None

    async def save(self, session: ConversationSession) -> None:
        key = self._key(session.conversation_id)
        data = session.model_dump_json()
        await self._redis.set(key, data, ex=self._ttl)

    async def delete(self, conversation_id: str) -> None:
        await self._redis.delete(self._key(conversation_id))

    async def cleanup_expired(self) -> int:
        # Redis TTL handles expiration automatically — no manual cleanup needed
        return 0

    async def close(self) -> None:
        """Close the Redis connection pool."""
        await self._redis.aclose()

    async def ping(self) -> bool:
        """Check Redis connectivity."""
        try:
            return await self._redis.ping()
        except Exception:
            return False


# ── Module-level Singleton ───────────────────────────────────

_store: ConversationStore | None = None


def get_conversation_store() -> ConversationStore:
    """Get the singleton conversation store instance."""
    global _store
    if _store is None:
        from config.settings import get_settings

        settings = get_settings()
        ttl = settings.conversation_ttl

        if settings.conversation_store_type == "redis" and settings.redis_url:
            _store = RedisConversationStore(
                redis_url=settings.redis_url,
                ttl_seconds=ttl,
            )
            logger.info(
                "Initialized RedisConversationStore (TTL=%ds)", ttl
            )
        else:
            _store = InMemoryConversationStore(ttl_seconds=ttl)
            logger.info(
                "Initialized InMemoryConversationStore (TTL=%ds)", ttl
            )
    return _store


def generate_conversation_id() -> str:
    """Generate a new server-side conversation ID."""
    return f"conv-{uuid.uuid4().hex[:12]}"


# ── Background Cleanup Task ──────────────────────────────────


async def periodic_cleanup(interval_seconds: int = 300) -> None:
    """Background task that periodically cleans up expired sessions.

    Should be started as an ``asyncio.Task`` in the FastAPI lifespan.
    """
    store = get_conversation_store()
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await store.cleanup_expired()
        except Exception:
            logger.exception("Conversation store cleanup failed")
