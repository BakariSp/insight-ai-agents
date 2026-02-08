"""Tests for the conversation session store."""

from __future__ import annotations

import time

import pytest

from services.conversation_store import (
    ConversationSession,
    ConversationTurn,
    InMemoryConversationStore,
    generate_conversation_id,
)


# ── Unit tests: ConversationSession ──────────────────────────


class TestConversationSession:
    def test_add_user_turn(self):
        session = ConversationSession(conversation_id="test-1")
        session.add_user_turn("Hello")
        assert len(session.turns) == 1
        assert session.turns[0].role == "user"
        assert session.turns[0].content == "Hello"

    def test_add_assistant_turn(self):
        session = ConversationSession(conversation_id="test-1")
        session.add_assistant_turn("Hi there!", action="chat_smalltalk")
        assert len(session.turns) == 1
        assert session.turns[0].role == "assistant"
        assert session.turns[0].action == "chat_smalltalk"

    def test_content_truncation(self):
        from services.conversation_store import MAX_TURN_CHARS
        session = ConversationSession(conversation_id="test-1")
        long_message = "x" * 10000
        session.add_user_turn(long_message)
        assert len(session.turns[0].content) == MAX_TURN_CHARS

    def test_merge_context_simple(self):
        session = ConversationSession(conversation_id="test-1")
        session.merge_context({"classId": "class-1"})
        assert session.accumulated_context["classId"] == "class-1"

    def test_merge_context_overwrite(self):
        session = ConversationSession(conversation_id="test-1")
        session.merge_context({"classId": "class-1"})
        session.merge_context({"classId": "class-2"})
        assert session.accumulated_context["classId"] == "class-2"

    def test_merge_context_shallow_dict_merge(self):
        session = ConversationSession(conversation_id="test-1")
        session.merge_context({"input": {"class": "c1"}})
        session.merge_context({"input": {"student": "s1"}})
        assert session.accumulated_context["input"] == {"class": "c1", "student": "s1"}

    def test_recent_turns(self):
        session = ConversationSession(conversation_id="test-1")
        for i in range(10):
            session.add_user_turn(f"Message {i}")
        assert len(session.recent_turns(3)) == 3
        assert session.recent_turns(3)[0].content == "Message 7"

    def test_format_history_empty(self):
        session = ConversationSession(conversation_id="test-1")
        assert session.format_history_for_prompt() == ""

    def test_format_history_excludes_current_message(self):
        """The current user message (last turn) should be excluded from history."""
        session = ConversationSession(conversation_id="test-1")
        session.add_user_turn("Analyze grades")
        session.add_assistant_turn("Which class?", action="clarify")
        session.add_user_turn("1A班")  # Current message being classified
        history = session.format_history_for_prompt()
        assert "Analyze grades" in history
        assert "Which class?" in history
        assert "1A班" not in history

    def test_format_history_action_tags(self):
        session = ConversationSession(conversation_id="test-1")
        session.add_user_turn("Analyze grades")
        session.add_assistant_turn("Which class?", action="clarify")
        session.add_user_turn("current")  # Current message
        history = session.format_history_for_prompt()
        assert "[clarify]" in history

    def test_format_history_max_turns(self):
        session = ConversationSession(conversation_id="test-1")
        for i in range(20):
            session.add_user_turn(f"Message {i}")
            session.add_assistant_turn(f"Response {i}", action="chat")
        session.add_user_turn("current")
        history = session.format_history_for_prompt(max_turns=3)
        lines = [l for l in history.split("\n") if l.strip()]
        assert len(lines) == 3


# ── Unit tests: InMemoryConversationStore ────────────────────


class TestInMemoryConversationStore:
    @pytest.fixture
    def store(self):
        return InMemoryConversationStore(ttl_seconds=5)

    @pytest.mark.asyncio
    async def test_create_and_retrieve(self, store):
        session = ConversationSession(conversation_id="test-1")
        session.add_user_turn("Hello")
        await store.save(session)

        retrieved = await store.get("test-1")
        assert retrieved is not None
        assert retrieved.conversation_id == "test-1"
        assert len(retrieved.turns) == 1

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, store):
        result = await store.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_expiration(self, store):
        store._ttl = 0  # Expire immediately
        session = ConversationSession(conversation_id="test-1")
        session.updated_at = time.time() - 1  # In the past
        await store.save(session)

        result = await store.get("test-1")
        assert result is None
        assert store.size == 0  # Cleaned up on access

    @pytest.mark.asyncio
    async def test_delete(self, store):
        session = ConversationSession(conversation_id="test-1")
        await store.save(session)
        await store.delete("test-1")
        assert await store.get("test-1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store):
        # Should not raise
        await store.delete("nonexistent")

    @pytest.mark.asyncio
    async def test_cleanup_expired(self, store):
        store._ttl = 2  # 2 seconds TTL

        s1 = ConversationSession(conversation_id="old-1")
        s1.updated_at = time.time() - 10  # Expired
        s2 = ConversationSession(conversation_id="old-2")
        s2.updated_at = time.time() - 10  # Expired
        s3 = ConversationSession(conversation_id="fresh")
        # s3 keeps default updated_at (now) — not expired

        await store.save(s1)
        await store.save(s2)
        await store.save(s3)

        removed = await store.cleanup_expired()
        assert removed == 2
        assert store.size == 1

    @pytest.mark.asyncio
    async def test_size(self, store):
        assert store.size == 0
        await store.save(ConversationSession(conversation_id="a"))
        await store.save(ConversationSession(conversation_id="b"))
        assert store.size == 2


# ── Unit tests: generate_conversation_id ─────────────────────


class TestGenerateConversationId:
    def test_format(self):
        cid = generate_conversation_id()
        assert cid.startswith("conv-")
        assert len(cid) == 17  # "conv-" + 12 hex chars

    def test_uniqueness(self):
        ids = {generate_conversation_id() for _ in range(100)}
        assert len(ids) == 100
