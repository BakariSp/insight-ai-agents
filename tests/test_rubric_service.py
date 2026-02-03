"""Tests for rubric service and tools."""

import pytest
from services.rubric_service import (
    load_rubric,
    list_rubrics,
    get_rubric_for_task,
    get_rubric_context,
)
from tools.rubric_tools import get_rubric, list_available_rubrics


class TestRubricService:
    """Tests for rubric_service.py functions."""

    def test_load_rubric_exists(self):
        """Should load an existing rubric by ID."""
        rubric = load_rubric("DSE-ENG-Writing-Argumentative")
        assert rubric is not None
        assert rubric.id == "DSE-ENG-Writing-Argumentative"
        assert rubric.subject == "English"
        assert rubric.task_type == "essay"
        assert rubric.total_marks == 21
        assert len(rubric.criteria) == 3

    def test_load_rubric_not_found(self):
        """Should return None for non-existent rubric."""
        rubric = load_rubric("non-existent-rubric")
        assert rubric is None

    def test_list_rubrics_all(self):
        """Should list all rubrics when no filter provided."""
        rubrics = list_rubrics()
        assert len(rubrics) >= 1
        assert any(r["id"] == "DSE-ENG-Writing-Argumentative" for r in rubrics)

    def test_list_rubrics_filter_subject(self):
        """Should filter rubrics by subject."""
        rubrics = list_rubrics(subject="English")
        assert len(rubrics) >= 1
        assert all(r["subject"].lower() == "english" for r in rubrics)

    def test_list_rubrics_filter_task_type(self):
        """Should filter rubrics by task type."""
        rubrics = list_rubrics(task_type="essay")
        assert len(rubrics) >= 1
        assert all(r["taskType"].lower() == "essay" for r in rubrics)

    def test_list_rubrics_filter_no_match(self):
        """Should return empty list when no rubrics match filter."""
        rubrics = list_rubrics(subject="NonExistentSubject")
        assert rubrics == []

    def test_get_rubric_for_task(self):
        """Should find best matching rubric for a task."""
        rubric = get_rubric_for_task("English", "essay", "DSE")
        assert rubric is not None
        assert rubric.subject == "English"
        assert rubric.task_type == "essay"

    def test_get_rubric_for_task_not_found(self):
        """Should return None when no matching rubric found."""
        rubric = get_rubric_for_task("Physics", "lab_report", "DSE")
        assert rubric is None

    def test_get_rubric_context(self):
        """Should convert rubric to LLM-friendly context."""
        rubric = load_rubric("DSE-ENG-Writing-Argumentative")
        assert rubric is not None

        context = get_rubric_context(rubric)

        assert context["rubricId"] == "DSE-ENG-Writing-Argumentative"
        assert context["name"] == "DSE English Writing - Argumentative Essay"
        assert context["totalMarks"] == 21
        assert "Content" in context["criteriaText"]
        assert "Organization" in context["criteriaText"]
        assert "Language" in context["criteriaText"]
        assert len(context["commonErrors"]) > 0


class TestRubricTools:
    """Tests for rubric_tools.py async functions."""

    @pytest.mark.asyncio
    async def test_get_rubric_found(self):
        """Should return rubric context when found."""
        result = await get_rubric("English", "essay", "DSE")

        assert "error" not in result
        assert result["rubricId"] == "DSE-ENG-Writing-Argumentative"
        assert result["totalMarks"] == 21
        assert "criteriaText" in result

    @pytest.mark.asyncio
    async def test_get_rubric_not_found(self):
        """Should return error when rubric not found."""
        result = await get_rubric("Physics", "lab_report", "DSE")

        assert "error" in result
        assert "No rubric found" in result["error"]

    @pytest.mark.asyncio
    async def test_list_available_rubrics_all(self):
        """Should list all available rubrics."""
        result = await list_available_rubrics()

        assert "rubrics" in result
        assert "count" in result
        assert result["count"] >= 1
        assert result["filters"]["subject"] == "all"

    @pytest.mark.asyncio
    async def test_list_available_rubrics_filtered(self):
        """Should list rubrics with filters."""
        result = await list_available_rubrics(subject="English")

        assert "rubrics" in result
        assert result["count"] >= 1
        assert result["filters"]["subject"] == "English"
        assert all(r["subject"].lower() == "english" for r in result["rubrics"])
