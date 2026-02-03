"""Tests for RAG service."""

import pytest
from services.rag_service import (
    CurriculumRAG,
    SimpleRAGStore,
    Document,
    COLLECTIONS,
    get_rag_service,
)


class TestSimpleRAGStore:
    """Tests for SimpleRAGStore."""

    def setup_method(self):
        """Set up test store."""
        self.store = SimpleRAGStore()

    def test_add_and_query_document(self):
        """Should add and retrieve documents."""
        self.store.add_document(
            collection="official_corpus",
            doc_id="test-doc-1",
            content="This is a test document about reading comprehension skills.",
            metadata={"type": "test"},
        )

        results = self.store.query("official_corpus", "reading comprehension")

        assert len(results) >= 1
        assert results[0]["id"] == "test-doc-1"
        assert "reading comprehension" in results[0]["content"].lower()

    def test_query_with_metadata_filter(self):
        """Should filter by metadata."""
        self.store.add_document(
            collection="official_corpus",
            doc_id="rubric-1",
            content="Essay rubric content",
            metadata={"type": "rubric"},
        )
        self.store.add_document(
            collection="official_corpus",
            doc_id="kp-1",
            content="Knowledge point content",
            metadata={"type": "knowledge_point"},
        )

        results = self.store.query(
            "official_corpus",
            "content",
            where={"type": "rubric"},
        )

        assert len(results) == 1
        assert results[0]["id"] == "rubric-1"

    def test_query_no_results(self):
        """Should return empty list when no matches."""
        results = self.store.query("official_corpus", "nonexistent query terms xyz")
        assert results == []

    def test_invalid_collection(self):
        """Should raise error for invalid collection."""
        with pytest.raises(ValueError, match="Unknown collection"):
            self.store.add_document("invalid_collection", "id", "content")

        with pytest.raises(ValueError, match="Unknown collection"):
            self.store.query("invalid_collection", "query")

    def test_collection_stats(self):
        """Should return collection statistics."""
        self.store.add_document("official_corpus", "doc1", "content 1")
        self.store.add_document("official_corpus", "doc2", "content 2")

        stats = self.store.get_collection_stats("official_corpus")

        assert stats["collection"] == "official_corpus"
        assert stats["doc_count"] == 2
        assert "description" in stats


class TestCurriculumRAG:
    """Tests for CurriculumRAG service."""

    def setup_method(self):
        """Set up fresh RAG instance."""
        # Create a fresh instance (not using singleton)
        self.rag = CurriculumRAG()

    def test_initialization_loads_data(self):
        """Should load rubrics and knowledge points on init."""
        stats = self.rag.get_stats()

        # Should have loaded DSE English Writing rubric
        assert stats["official_corpus"]["doc_count"] >= 1

    def test_query_rubric_content(self):
        """Should find rubric content."""
        results = self.rag.query(
            "official_corpus",
            "English essay writing criteria",
        )

        # Should find the DSE English Writing rubric
        assert len(results) >= 1
        assert any("essay" in r["content"].lower() for r in results)

    def test_add_custom_document(self):
        """Should allow adding custom documents."""
        self.rag.add_document(
            collection="school_assets",
            doc_id="custom-rubric-1",
            content="Custom school rubric for math tests",
            metadata={"type": "rubric", "subject": "Math"},
        )

        results = self.rag.query("school_assets", "math rubric")

        assert len(results) >= 1
        assert results[0]["id"] == "custom-rubric-1"

    @pytest.mark.asyncio
    async def test_get_rubric_context(self):
        """Should get rubric context for LLM."""
        context = await self.rag.get_rubric_context("English", "essay")

        # Should return non-empty context if rubric exists
        # (may be empty if rubric not loaded)
        if context:
            assert "essay" in context.lower() or "writing" in context.lower()

    @pytest.mark.asyncio
    async def test_get_curriculum_context(self):
        """Should get curriculum context for LLM."""
        context = await self.rag.get_curriculum_context("English", "U5")

        # May be empty if no knowledge points loaded
        # Test just ensures no errors
        assert isinstance(context, str)

    @pytest.mark.asyncio
    async def test_search_similar_questions(self):
        """Should search question bank."""
        # Add a sample question
        self.rag.add_document(
            collection="question_bank",
            doc_id="q1",
            content="What is the main idea of the passage?",
            metadata={"type": "question", "difficulty": "medium"},
        )

        results = await self.rag.search_similar_questions(
            knowledge_point_ids=["reading", "main idea"],
            difficulty="medium",
        )

        assert len(results) >= 1


class TestGetRagService:
    """Tests for singleton access."""

    def test_returns_same_instance(self):
        """Should return same instance."""
        service1 = get_rag_service()
        service2 = get_rag_service()

        assert service1 is service2

    def test_instance_has_data(self):
        """Should have loaded initial data."""
        service = get_rag_service()
        stats = service.get_stats()

        assert "official_corpus" in stats
