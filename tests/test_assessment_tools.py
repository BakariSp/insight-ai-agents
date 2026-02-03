"""Tests for Phase 7 assessment tools."""

import pytest
from tools.assessment_tools import (
    analyze_student_weakness,
    get_student_error_patterns,
    calculate_class_mastery,
)


# Sample submission data with question-level items
SAMPLE_SUBMISSIONS = [
    {
        "student_id": "s1",
        "name": "Alice",
        "score": 75,
        "submitted": True,
        "items": [
            {
                "question_id": "q1",
                "score": 1,
                "max_score": 1,
                "correct": True,
                "error_tags": [],
                "knowledge_point_ids": ["DSE-ENG-U5-RC-01"],
            },
            {
                "question_id": "q2",
                "score": 0,
                "max_score": 1,
                "correct": False,
                "error_tags": ["grammar", "tense"],
                "knowledge_point_ids": ["DSE-ENG-U5-GR-01"],
            },
            {
                "question_id": "q3",
                "score": 1,
                "max_score": 1,
                "correct": True,
                "error_tags": [],
                "knowledge_point_ids": ["DSE-ENG-U5-RC-02"],
            },
        ],
    },
    {
        "student_id": "s2",
        "name": "Bob",
        "score": 50,
        "submitted": True,
        "items": [
            {
                "question_id": "q1",
                "score": 0,
                "max_score": 1,
                "correct": False,
                "error_tags": ["inference"],
                "knowledge_point_ids": ["DSE-ENG-U5-RC-01"],
            },
            {
                "question_id": "q2",
                "score": 0,
                "max_score": 1,
                "correct": False,
                "error_tags": ["grammar", "subject-verb"],
                "knowledge_point_ids": ["DSE-ENG-U5-GR-01"],
            },
            {
                "question_id": "q3",
                "score": 1,
                "max_score": 1,
                "correct": True,
                "error_tags": [],
                "knowledge_point_ids": ["DSE-ENG-U5-RC-02"],
            },
        ],
    },
    {
        "student_id": "s3",
        "name": "Charlie",
        "score": 100,
        "submitted": True,
        "items": [
            {
                "question_id": "q1",
                "score": 1,
                "max_score": 1,
                "correct": True,
                "error_tags": [],
                "knowledge_point_ids": ["DSE-ENG-U5-RC-01"],
            },
            {
                "question_id": "q2",
                "score": 1,
                "max_score": 1,
                "correct": True,
                "error_tags": [],
                "knowledge_point_ids": ["DSE-ENG-U5-GR-01"],
            },
            {
                "question_id": "q3",
                "score": 1,
                "max_score": 1,
                "correct": True,
                "error_tags": [],
                "knowledge_point_ids": ["DSE-ENG-U5-RC-02"],
            },
        ],
    },
]


class TestAnalyzeStudentWeakness:
    """Tests for analyze_student_weakness."""

    @pytest.mark.asyncio
    async def test_empty_submissions(self):
        """Should return empty analysis for no submissions."""
        result = await analyze_student_weakness(
            teacher_id="t1",
            class_id="c1",
        )
        assert result["classId"] == "c1"
        assert result["weakPoints"] == []
        assert result["recommendedFocus"] == []

    @pytest.mark.asyncio
    async def test_identifies_weak_points(self):
        """Should identify knowledge points with high error rates."""
        result = await analyze_student_weakness(
            teacher_id="t1",
            class_id="c1",
            submissions=SAMPLE_SUBMISSIONS,
        )

        assert result["classId"] == "c1"
        assert len(result["weakPoints"]) == 3

        # Grammar (GR-01) should be weakest: 2/3 students got it wrong
        # Error rate = 2/3 = 0.667
        weak_points = {wp["knowledgePointId"]: wp for wp in result["weakPoints"]}

        assert "DSE-ENG-U5-GR-01" in weak_points
        gr01 = weak_points["DSE-ENG-U5-GR-01"]
        assert gr01["errorRate"] == pytest.approx(0.667, rel=0.01)
        assert gr01["affectedStudents"] == 2
        assert "grammar" in gr01["commonErrorTags"]

    @pytest.mark.asyncio
    async def test_recommended_focus(self):
        """Should recommend top weak points for focus."""
        result = await analyze_student_weakness(
            teacher_id="t1",
            class_id="c1",
            submissions=SAMPLE_SUBMISSIONS,
        )

        assert len(result["recommendedFocus"]) <= 3
        # Grammar should be in recommended focus (highest error rate)
        assert "DSE-ENG-U5-GR-01" in result["recommendedFocus"]


class TestGetStudentErrorPatterns:
    """Tests for get_student_error_patterns."""

    @pytest.mark.asyncio
    async def test_empty_submissions(self):
        """Should return empty patterns for no submissions."""
        result = await get_student_error_patterns(
            teacher_id="t1",
            student_id="s1",
        )
        assert result["studentId"] == "s1"
        assert result["errorPatterns"] == []
        assert result["overallMastery"] == 0.0

    @pytest.mark.asyncio
    async def test_identifies_student_errors(self):
        """Should identify error patterns for a specific student."""
        result = await get_student_error_patterns(
            teacher_id="t1",
            student_id="s2",
            submissions=SAMPLE_SUBMISSIONS,
        )

        assert result["studentId"] == "s2"
        assert len(result["errorPatterns"]) == 2  # Two knowledge points with errors

        # Check error patterns
        patterns = {ep["knowledgePointId"]: ep for ep in result["errorPatterns"]}

        # Grammar error
        assert "DSE-ENG-U5-GR-01" in patterns
        assert patterns["DSE-ENG-U5-GR-01"]["errorCount"] == 1

        # Reading comprehension error
        assert "DSE-ENG-U5-RC-01" in patterns
        assert patterns["DSE-ENG-U5-RC-01"]["errorCount"] == 1

    @pytest.mark.asyncio
    async def test_calculates_mastery(self):
        """Should calculate overall mastery rate."""
        # Charlie has 100% correct
        result = await get_student_error_patterns(
            teacher_id="t1",
            student_id="s3",
            submissions=SAMPLE_SUBMISSIONS,
        )

        assert result["studentId"] == "s3"
        assert result["overallMastery"] == 1.0
        assert result["errorPatterns"] == []


class TestCalculateClassMastery:
    """Tests for calculate_class_mastery."""

    def test_empty_submissions(self):
        """Should handle empty submissions."""
        result = calculate_class_mastery([])
        assert result["knowledgePointMastery"] == []
        assert result["averageMastery"] == 0.0

    def test_calculates_mastery_per_kp(self):
        """Should calculate mastery rate per knowledge point."""
        result = calculate_class_mastery(SAMPLE_SUBMISSIONS)

        assert len(result["knowledgePointMastery"]) == 3

        mastery = {m["knowledgePointId"]: m for m in result["knowledgePointMastery"]}

        # RC-02: 3/3 correct = 100%
        assert mastery["DSE-ENG-U5-RC-02"]["masteryRate"] == 1.0

        # RC-01: 2/3 correct = 66.7%
        assert mastery["DSE-ENG-U5-RC-01"]["masteryRate"] == pytest.approx(0.667, rel=0.01)

        # GR-01: 1/3 correct = 33.3%
        assert mastery["DSE-ENG-U5-GR-01"]["masteryRate"] == pytest.approx(0.333, rel=0.01)

    def test_filters_by_knowledge_points(self):
        """Should filter by specific knowledge points."""
        result = calculate_class_mastery(
            SAMPLE_SUBMISSIONS,
            knowledge_point_ids=["DSE-ENG-U5-RC-01"],
        )

        assert len(result["knowledgePointMastery"]) == 1
        assert result["knowledgePointMastery"][0]["knowledgePointId"] == "DSE-ENG-U5-RC-01"
