"""Tests for knowledge point service."""

import pytest
from services.knowledge_service import (
    load_knowledge_registry,
    get_knowledge_point,
    list_knowledge_points,
    map_error_to_knowledge_points,
    get_prerequisite_chain,
    get_knowledge_points_for_weakness,
    get_related_knowledge_points,
)


class TestKnowledgeRegistry:
    """Tests for knowledge registry loading."""

    def test_load_registry_exists(self):
        """Should load existing registry."""
        registry = load_knowledge_registry("English", "DSE")

        assert registry is not None
        assert registry.get("subject") == "English"
        assert registry.get("level") == "DSE"
        assert len(registry.get("units", [])) > 0

    def test_load_registry_not_found(self):
        """Should return empty dict for non-existent registry."""
        registry = load_knowledge_registry("Physics", "DSE")
        assert registry == {}


class TestGetKnowledgePoint:
    """Tests for get_knowledge_point function."""

    def test_get_existing_kp(self):
        """Should get existing knowledge point."""
        kp = get_knowledge_point("DSE-ENG-U5-RC-01")

        assert kp is not None
        assert kp.id == "DSE-ENG-U5-RC-01"
        assert kp.name == "Reading Comprehension - Main Idea"
        assert kp.subject == "English"
        assert "reading" in kp.skill_tags

    def test_get_nonexistent_kp(self):
        """Should return None for non-existent knowledge point."""
        kp = get_knowledge_point("DSE-ENG-U5-XX-99")
        assert kp is None

    def test_get_invalid_id(self):
        """Should return None for invalid ID format."""
        kp = get_knowledge_point("invalid")
        assert kp is None


class TestListKnowledgePoints:
    """Tests for list_knowledge_points function."""

    def test_list_all_english(self):
        """Should list all English knowledge points."""
        kps = list_knowledge_points("English")

        assert len(kps) > 0
        assert all(kp.subject == "English" for kp in kps)

    def test_filter_by_unit(self):
        """Should filter by unit."""
        kps = list_knowledge_points("English", unit="DSE-ENG-U5")

        assert len(kps) > 0
        assert all(kp.unit == "DSE-ENG-U5" for kp in kps)

    def test_filter_by_skill_tags(self):
        """Should filter by skill tags."""
        kps = list_knowledge_points("English", skill_tags=["grammar"])

        assert len(kps) > 0
        assert all(any("grammar" in tag for tag in kp.skill_tags) for kp in kps)

    def test_filter_by_difficulty(self):
        """Should filter by difficulty."""
        kps = list_knowledge_points("English", difficulty="hard")

        assert len(kps) > 0
        assert all(kp.difficulty == "hard" for kp in kps)

    def test_empty_results(self):
        """Should return empty list when no matches."""
        kps = list_knowledge_points("NonExistent")
        assert kps == []


class TestMapErrorToKnowledgePoints:
    """Tests for error to knowledge point mapping."""

    def test_map_grammar_errors(self):
        """Should map grammar errors to grammar knowledge points."""
        kp_ids = map_error_to_knowledge_points(["grammar", "tense"])

        assert len(kp_ids) > 0
        assert any("GR-01" in kp_id for kp_id in kp_ids)

    def test_map_reading_errors(self):
        """Should map reading errors to reading knowledge points."""
        kp_ids = map_error_to_knowledge_points(["inference", "main_idea"])

        assert len(kp_ids) > 0
        assert any("RC-01" in kp_id for kp_id in kp_ids)
        assert any("RC-03" in kp_id for kp_id in kp_ids)

    def test_map_unknown_errors(self):
        """Should return empty for unknown error tags."""
        kp_ids = map_error_to_knowledge_points(["unknown_error_tag"])
        assert kp_ids == []

    def test_map_mixed_errors(self):
        """Should handle mix of known and unknown errors."""
        kp_ids = map_error_to_knowledge_points(["grammar", "unknown"])

        assert len(kp_ids) > 0
        # Should only include matches for known errors


class TestPrerequisiteChain:
    """Tests for prerequisite chain."""

    def test_get_chain_no_prerequisites(self):
        """Should return single item for KP without prerequisites."""
        chain = get_prerequisite_chain("DSE-ENG-U5-GR-01")

        assert len(chain) == 1
        assert chain[0].id == "DSE-ENG-U5-GR-01"

    def test_get_chain_with_prerequisites(self):
        """Should include prerequisites in chain."""
        # RC-02 has RC-01 as prerequisite
        chain = get_prerequisite_chain("DSE-ENG-U5-RC-02")

        assert len(chain) >= 2
        ids = [kp.id for kp in chain]
        assert "DSE-ENG-U5-RC-01" in ids
        assert "DSE-ENG-U5-RC-02" in ids
        # Prerequisites should come before dependents
        assert ids.index("DSE-ENG-U5-RC-01") < ids.index("DSE-ENG-U5-RC-02")

    def test_get_chain_nonexistent(self):
        """Should return empty for non-existent KP."""
        chain = get_prerequisite_chain("DSE-ENG-U5-XX-99")
        assert chain == []


class TestGetKnowledgePointsForWeakness:
    """Tests for weakness-based knowledge point retrieval."""

    def test_get_weak_kps_without_prereqs(self):
        """Should get only specified weak points."""
        kps = get_knowledge_points_for_weakness(
            ["DSE-ENG-U5-GR-01", "DSE-ENG-U5-GR-02"],
            include_prerequisites=False,
        )

        assert len(kps) == 2
        ids = [kp.id for kp in kps]
        assert "DSE-ENG-U5-GR-01" in ids
        assert "DSE-ENG-U5-GR-02" in ids

    def test_get_weak_kps_with_prereqs(self):
        """Should include prerequisites."""
        kps = get_knowledge_points_for_weakness(
            ["DSE-ENG-U5-RC-02"],
            include_prerequisites=True,
        )

        ids = [kp.id for kp in kps]
        # Should include RC-02 and its prerequisite RC-01
        assert "DSE-ENG-U5-RC-02" in ids
        assert "DSE-ENG-U5-RC-01" in ids

    def test_deduplication(self):
        """Should not duplicate knowledge points."""
        kps = get_knowledge_points_for_weakness(
            ["DSE-ENG-U5-RC-01", "DSE-ENG-U5-RC-02"],
            include_prerequisites=True,
        )

        ids = [kp.id for kp in kps]
        # RC-01 should appear only once even though it's both
        # specified directly and as a prerequisite of RC-02
        assert ids.count("DSE-ENG-U5-RC-01") == 1


class TestGetRelatedKnowledgePoints:
    """Tests for related knowledge point retrieval."""

    def test_get_related_same_unit(self):
        """Should get related KPs from same unit."""
        related = get_related_knowledge_points(
            "DSE-ENG-U5-RC-01",
            same_unit=True,
            same_skill=False,
        )

        assert len(related) > 0
        # Should not include the reference KP itself
        assert all(kp.id != "DSE-ENG-U5-RC-01" for kp in related)
        # All should be from same unit
        assert all(kp.unit == "DSE-ENG-U5" for kp in related)

    def test_get_related_nonexistent(self):
        """Should return empty for non-existent KP."""
        related = get_related_knowledge_points("DSE-ENG-U5-XX-99")
        assert related == []
