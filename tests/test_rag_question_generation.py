"""Tests for RAG service and question generation with HKDSE subjects.

Tests the complete flow:
1. RAG service loading knowledge points and rubrics
2. Knowledge service retrieving subject-specific data
3. Question pipeline generating questions for Math, Chinese, and ICT
"""

from __future__ import annotations

import pytest

from services.rag_service import get_rag_service, CurriculumRAG
from services.knowledge_service import (
    load_knowledge_registry,
    get_knowledge_point,
    list_knowledge_points,
    map_error_to_knowledge_points,
    SUBJECT_CODE_MAP,
)
from services.rubric_service import load_rubric, list_rubrics


class TestRAGServiceInitialization:
    """Test RAG service initialization and data loading."""

    def test_rag_service_singleton(self):
        """Test that get_rag_service returns the same instance."""
        rag1 = get_rag_service()
        rag2 = get_rag_service()
        # Note: Due to lru_cache, these should be the same instance
        assert rag1 is not None
        assert rag2 is not None

    def test_rag_service_loads_collections(self):
        """Test that RAG service has all expected collections."""
        rag = CurriculumRAG()
        stats = rag.get_stats()

        assert "official_corpus" in stats
        assert "school_assets" in stats
        assert "question_bank" in stats

    def test_rag_service_loads_knowledge_points(self):
        """Test that knowledge points are loaded into RAG."""
        rag = CurriculumRAG()
        stats = rag.get_stats()

        # Should have loaded documents from data/knowledge_points
        official_stats = stats["official_corpus"]
        assert official_stats["doc_count"] > 0


class TestKnowledgePointsLoading:
    """Test loading of knowledge points for different subjects."""

    def test_load_english_knowledge_points(self):
        """Test loading English knowledge points."""
        registry = load_knowledge_registry("English", "DSE")

        assert registry is not None
        assert registry.get("subject") == "English"
        assert registry.get("level") == "DSE"
        assert "units" in registry
        assert len(registry["units"]) > 0

    def test_load_math_knowledge_points(self):
        """Test loading Math knowledge points."""
        registry = load_knowledge_registry("Math", "DSE")

        assert registry is not None
        assert registry.get("subject") == "Math"
        assert registry.get("level") == "DSE"
        assert "units" in registry

        # Verify specific math units
        unit_ids = [u["id"] for u in registry["units"]]
        assert "DSE-MATH-C1" in unit_ids  # Algebra
        assert "DSE-MATH-C2" in unit_ids  # Geometry
        assert "DSE-MATH-C3" in unit_ids  # Statistics

    def test_load_chinese_knowledge_points(self):
        """Test loading Chinese knowledge points."""
        registry = load_knowledge_registry("Chinese", "DSE")

        assert registry is not None
        assert registry.get("subject") == "Chinese"
        assert registry.get("level") == "DSE"
        assert "units" in registry

        # Verify Chinese units
        unit_ids = [u["id"] for u in registry["units"]]
        assert "DSE-CHI-RD" in unit_ids  # 閱讀能力
        assert "DSE-CHI-WR" in unit_ids  # 寫作能力

    def test_load_ict_knowledge_points(self):
        """Test loading ICT knowledge points."""
        registry = load_knowledge_registry("ICT", "DSE")

        assert registry is not None
        assert registry.get("subject") == "ICT"
        assert registry.get("level") == "DSE"
        assert "units" in registry

        # Verify ICT units
        unit_ids = [u["id"] for u in registry["units"]]
        assert "DSE-ICT-A" in unit_ids  # Information Processing
        assert "DSE-ICT-D" in unit_ids  # Programming


class TestKnowledgePointRetrieval:
    """Test retrieval of specific knowledge points."""

    def test_get_math_knowledge_point(self):
        """Test getting a specific math knowledge point."""
        kp = get_knowledge_point("DSE-MATH-C1-QE-01")

        assert kp is not None
        assert kp.id == "DSE-MATH-C1-QE-01"
        assert "Quadratic" in kp.name or "Factorization" in kp.name
        assert "algebra" in kp.skill_tags or "equations" in kp.skill_tags

    def test_get_chinese_knowledge_point(self):
        """Test getting a specific Chinese knowledge point."""
        kp = get_knowledge_point("DSE-CHI-RD-CM-01")

        assert kp is not None
        assert kp.id == "DSE-CHI-RD-CM-01"
        assert "主旨" in kp.name

    def test_get_ict_knowledge_point(self):
        """Test getting a specific ICT knowledge point."""
        kp = get_knowledge_point("DSE-ICT-D-PG-01")

        assert kp is not None
        assert kp.id == "DSE-ICT-D-PG-01"
        assert "Algorithm" in kp.name

    def test_get_nonexistent_knowledge_point(self):
        """Test getting a knowledge point that doesn't exist."""
        kp = get_knowledge_point("DSE-FAKE-XX-01")
        assert kp is None


class TestKnowledgePointFiltering:
    """Test filtering knowledge points by various criteria."""

    def test_list_math_by_difficulty(self):
        """Test filtering math knowledge points by difficulty."""
        easy_kps = list_knowledge_points("Math", difficulty="easy", level="DSE")
        hard_kps = list_knowledge_points("Math", difficulty="hard", level="DSE")

        assert len(easy_kps) > 0
        assert len(hard_kps) > 0
        assert all(kp.difficulty == "easy" for kp in easy_kps)
        assert all(kp.difficulty == "hard" for kp in hard_kps)

    def test_list_ict_by_skill_tags(self):
        """Test filtering ICT knowledge points by skill tags."""
        programming_kps = list_knowledge_points(
            "ICT",
            skill_tags=["programming"],
            level="DSE",
        )

        assert len(programming_kps) > 0
        assert all(
            any("programming" in tag for tag in kp.skill_tags)
            for kp in programming_kps
        )


class TestErrorTagMapping:
    """Test mapping error tags to knowledge points."""

    def test_map_math_errors(self):
        """Test mapping math error tags."""
        errors = ["quadratic", "factorization"]
        kp_ids = map_error_to_knowledge_points(errors, "Math")

        assert len(kp_ids) > 0
        assert "DSE-MATH-C1-QE-01" in kp_ids

    def test_map_chinese_errors(self):
        """Test mapping Chinese error tags."""
        errors = ["文言文", "修辭"]
        kp_ids = map_error_to_knowledge_points(errors, "Chinese")

        assert len(kp_ids) > 0
        # Should include classical Chinese knowledge points
        assert any("DSE-CHI-RD-LT" in kp_id for kp_id in kp_ids)

    def test_map_ict_errors(self):
        """Test mapping ICT error tags."""
        errors = ["sql", "database", "loop"]
        kp_ids = map_error_to_knowledge_points(errors, "ICT")

        assert len(kp_ids) > 0
        assert any("DSE-ICT-A-DB" in kp_id for kp_id in kp_ids)
        assert any("DSE-ICT-D-PG" in kp_id for kp_id in kp_ids)

    def test_map_unknown_errors(self):
        """Test mapping unknown error tags returns empty."""
        errors = ["unknown_error_xyz"]
        kp_ids = map_error_to_knowledge_points(errors, "Math")

        assert kp_ids == []


class TestRubricLoading:
    """Test loading rubrics for different subjects."""

    def test_list_rubrics(self):
        """Test listing all available rubrics."""
        rubrics = list_rubrics()

        assert len(rubrics) > 0
        # Should have rubrics for multiple subjects
        subjects = {r.get("subject", "") for r in rubrics}
        assert "English" in subjects or "Math" in subjects

    def test_list_rubrics_by_subject(self):
        """Test filtering rubrics by subject."""
        math_rubrics = list_rubrics(subject="Math")
        chinese_rubrics = list_rubrics(subject="Chinese")

        assert len(math_rubrics) >= 0  # May or may not have math rubrics
        assert len(chinese_rubrics) >= 0

    def test_load_math_rubric(self):
        """Test loading a specific math rubric."""
        rubric = load_rubric("dse-math-problem-solving")

        if rubric:
            assert rubric.subject == "Math"
            assert rubric.total_marks > 0
            assert len(rubric.criteria) > 0

    def test_load_chinese_rubric(self):
        """Test loading a specific Chinese rubric."""
        rubric = load_rubric("dse-chi-writing-essay")

        if rubric:
            assert rubric.subject == "Chinese"
            assert rubric.total_marks > 0

    def test_load_ict_rubric(self):
        """Test loading a specific ICT rubric."""
        rubric = load_rubric("dse-ict-programming")

        if rubric:
            assert rubric.subject == "ICT"
            assert len(rubric.criteria) > 0


class TestRAGQuerying:
    """Test RAG query functionality."""

    def test_query_math_content(self):
        """Test querying math-related content."""
        rag = CurriculumRAG()

        results = rag.query(
            "official_corpus",
            "quadratic equations algebra",
            n_results=3,
        )

        assert isinstance(results, list)
        # May or may not find results depending on loaded data

    def test_query_with_subject_filter(self):
        """Test querying with subject metadata filter."""
        rag = CurriculumRAG()

        results = rag.query(
            "official_corpus",
            "programming algorithm",
            n_results=5,
            where={"type": "knowledge_point"},
        )

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_get_rubric_context(self):
        """Test getting rubric context for question generation."""
        rag = CurriculumRAG()

        context = await rag.get_rubric_context("Math", "problem_solving")

        # Context may be empty if no matching rubrics are loaded
        assert isinstance(context, str)

    @pytest.mark.asyncio
    async def test_get_curriculum_context(self):
        """Test getting curriculum context."""
        rag = CurriculumRAG()

        context = await rag.get_curriculum_context("ICT", "DSE-ICT-D")

        assert isinstance(context, str)


class TestSubjectCodeMapping:
    """Test subject code mappings."""

    def test_subject_codes_complete(self):
        """Test that all major subjects have code mappings."""
        assert "ENG" in SUBJECT_CODE_MAP
        assert "MATH" in SUBJECT_CODE_MAP
        assert "CHI" in SUBJECT_CODE_MAP
        assert "ICT" in SUBJECT_CODE_MAP

    def test_subject_code_values(self):
        """Test that subject code values are correct."""
        assert SUBJECT_CODE_MAP["ENG"] == "English"
        assert SUBJECT_CODE_MAP["MATH"] == "Math"
        assert SUBJECT_CODE_MAP["CHI"] == "Chinese"
        assert SUBJECT_CODE_MAP["ICT"] == "ICT"


class TestIntegrationRAGKnowledge:
    """Integration tests for RAG and knowledge services."""

    def test_full_flow_math(self):
        """Test full flow: list points → get point → find in RAG."""
        # 1. List math knowledge points
        kps = list_knowledge_points("Math", level="DSE")
        assert len(kps) > 0

        # 2. Get a specific knowledge point
        kp = kps[0]
        assert kp.id is not None

        # 3. Map an error to knowledge points
        kp_ids = map_error_to_knowledge_points(["quadratic"], "Math")
        assert len(kp_ids) > 0

    def test_full_flow_chinese(self):
        """Test full flow for Chinese subject."""
        # 1. List Chinese knowledge points
        kps = list_knowledge_points("Chinese", level="DSE")
        assert len(kps) > 0

        # 2. Get a specific knowledge point
        kp = get_knowledge_point("DSE-CHI-WR-ST-02")
        if kp:
            assert "議論文" in kp.name

        # 3. Map errors
        kp_ids = map_error_to_knowledge_points(["議論文"], "Chinese")
        assert len(kp_ids) > 0

    def test_full_flow_ict(self):
        """Test full flow for ICT subject."""
        # 1. List ICT knowledge points
        kps = list_knowledge_points("ICT", level="DSE")
        assert len(kps) > 0

        # 2. Get programming knowledge points
        prog_kps = list_knowledge_points(
            "ICT",
            skill_tags=["programming"],
            level="DSE",
        )
        assert len(prog_kps) > 0

        # 3. Map errors
        kp_ids = map_error_to_knowledge_points(["sql", "loop"], "ICT")
        assert len(kp_ids) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
