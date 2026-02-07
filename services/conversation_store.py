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

logger = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────


class ConversationTurn(BaseModel):
    """A single turn in a conversation."""

    role: str  # "user" or "assistant"
    content: str
    action: str | None = None  # Router action (e.g. "clarify", "build")
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

    def add_user_turn(self, message: str) -> None:
        """Record a user message (truncated to 500 chars)."""
        self.turns.append(ConversationTurn(
            role="user",
            content=message[:500],
        ))
        self.updated_at = time.time()

    def add_assistant_turn(
        self, response_summary: str, action: str | None = None
    ) -> None:
        """Record an assistant response with its action type."""
        self.turns.append(ConversationTurn(
            role="assistant",
            content=response_summary[:500],
            action=action,
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

    def format_history_for_prompt(self, max_turns: int = 5) -> str:
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
            content = turn.content[:200]
            lines.append(f"{prefix}: {action_tag}{content}")

        return "\n".join(lines)


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


# ── Module-level Singleton ───────────────────────────────────

_store: ConversationStore | None = None


def get_conversation_store() -> ConversationStore:
    """Get the singleton conversation store instance."""
    global _store
    if _store is None:
        from config.settings import get_settings

        settings = get_settings()
        ttl = settings.conversation_ttl
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
