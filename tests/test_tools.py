"""Tests for FastMCP tools — data tools and stats tools."""

import pytest
from unittest.mock import patch

from tools.data_tools import (
    get_assignment_submissions,
    get_class_detail,
    get_student_grades,
    get_teacher_classes,
)
from tools.stats_tools import calculate_stats, compare_performance


# ── Data Tools (async, tested with USE_MOCK_DATA=True) ─────────────────────


@pytest.mark.asyncio
async def test_get_teacher_classes_found():
    with patch("tools.data_tools._should_use_mock", return_value=True):
        result = await get_teacher_classes("t-001")
    assert result["teacher_id"] == "t-001"
    assert len(result["classes"]) == 2
    assert result["classes"][0]["class_id"] == "class-hk-f1a"


@pytest.mark.asyncio
async def test_get_teacher_classes_not_found():
    with patch("tools.data_tools._should_use_mock", return_value=True):
        result = await get_teacher_classes("t-999")
    assert result["teacher_id"] == "t-999"
    assert result["classes"] == []


@pytest.mark.asyncio
async def test_get_class_detail_found():
    with patch("tools.data_tools._should_use_mock", return_value=True):
        result = await get_class_detail("t-001", "class-hk-f1a")
    assert result["class_id"] == "class-hk-f1a"
    assert result["name"] == "Form 1A"
    assert len(result["students"]) == 5
    assert len(result["assignments"]) == 2


@pytest.mark.asyncio
async def test_get_class_detail_not_found():
    with patch("tools.data_tools._should_use_mock", return_value=True):
        result = await get_class_detail("t-001", "class-xxx")
    assert "error" in result


@pytest.mark.asyncio
async def test_get_assignment_submissions_found():
    with patch("tools.data_tools._should_use_mock", return_value=True):
        result = await get_assignment_submissions("t-001", "a-001")
    assert result["assignment_id"] == "a-001"
    assert len(result["submissions"]) == 5
    assert result["scores"] == [58, 85, 72, 91, 65]


@pytest.mark.asyncio
async def test_get_assignment_submissions_not_found():
    with patch("tools.data_tools._should_use_mock", return_value=True):
        result = await get_assignment_submissions("t-001", "a-999")
    assert "error" in result


@pytest.mark.asyncio
async def test_get_student_grades_found():
    with patch("tools.data_tools._should_use_mock", return_value=True):
        result = await get_student_grades("t-001", "s-001")
    assert result["student_id"] == "s-001"
    assert result["name"] == "Wong Ka Ho"
    assert len(result["grades"]) == 2


@pytest.mark.asyncio
async def test_get_student_grades_not_found():
    with patch("tools.data_tools._should_use_mock", return_value=True):
        result = await get_student_grades("t-001", "s-999")
    assert "error" in result


# ── Data Tools: fallback on backend error ──────────────────────────────────


@pytest.mark.asyncio
async def test_get_teacher_classes_fallback_on_error():
    """When USE_MOCK_DATA=False and backend fails, should fallback to mock."""
    with patch("tools.data_tools._should_use_mock", return_value=False), \
         patch("tools.data_tools._get_client", side_effect=RuntimeError("no backend")):
        result = await get_teacher_classes("t-001")
    assert result["teacher_id"] == "t-001"
    assert len(result["classes"]) == 2  # mock data


@pytest.mark.asyncio
async def test_get_class_detail_fallback_on_error():
    with patch("tools.data_tools._should_use_mock", return_value=False), \
         patch("tools.data_tools._get_client", side_effect=RuntimeError("no backend")):
        result = await get_class_detail("t-001", "class-hk-f1a")
    assert result["class_id"] == "class-hk-f1a"


@pytest.mark.asyncio
async def test_get_assignment_submissions_fallback_on_error():
    """When USE_MOCK_DATA=False and backend fails, should fallback to mock."""
    with patch("tools.data_tools._should_use_mock", return_value=False), \
         patch("tools.data_tools._get_client", side_effect=RuntimeError("no backend")):
        result = await get_assignment_submissions("t-001", "a-001")
    assert result["assignment_id"] == "a-001"
    assert len(result["submissions"]) == 5  # mock data


@pytest.mark.asyncio
async def test_get_student_grades_fallback_on_error():
    """When USE_MOCK_DATA=False and backend fails, should fallback to mock."""
    with patch("tools.data_tools._should_use_mock", return_value=False), \
         patch("tools.data_tools._get_client", side_effect=RuntimeError("no backend")):
        result = await get_student_grades("t-001", "s-001")
    assert result["student_id"] == "s-001"
    assert result["name"] == "Wong Ka Ho"


# ── Data Tools: Java backend via adapter (real path) ─────────────────────


@pytest.mark.asyncio
async def test_get_teacher_classes_calls_adapter_when_not_mock():
    """When USE_MOCK_DATA=False and backend succeeds, should use adapter."""
    from unittest.mock import AsyncMock, MagicMock
    from models.data import ClassInfo

    mock_client = MagicMock()
    fake_classes = [ClassInfo(class_id="uuid-1", name="Class A")]

    with patch("tools.data_tools._should_use_mock", return_value=False), \
         patch("tools.data_tools._get_client", return_value=mock_client), \
         patch("adapters.class_adapter.list_classes", new_callable=AsyncMock, return_value=fake_classes):
        result = await get_teacher_classes("t-001")

    assert result["teacher_id"] == "t-001"
    assert len(result["classes"]) == 1
    assert result["classes"][0]["class_id"] == "uuid-1"


@pytest.mark.asyncio
async def test_get_class_detail_calls_adapter_when_not_mock():
    """When USE_MOCK_DATA=False and backend succeeds, should use adapter."""
    from unittest.mock import AsyncMock, MagicMock
    from models.data import ClassDetail, AssignmentInfo

    mock_client = MagicMock()
    fake_detail = ClassDetail(class_id="uuid-1", name="Class A")
    fake_assignments = [AssignmentInfo(assignment_id="a-1", title="Test 1")]

    with patch("tools.data_tools._should_use_mock", return_value=False), \
         patch("tools.data_tools._get_client", return_value=mock_client), \
         patch("adapters.class_adapter.get_detail", new_callable=AsyncMock, return_value=fake_detail), \
         patch("adapters.class_adapter.list_assignments", new_callable=AsyncMock, return_value=fake_assignments):
        result = await get_class_detail("t-001", "uuid-1")

    assert result["class_id"] == "uuid-1"
    assert result["name"] == "Class A"
    assert len(result["assignments"]) == 1


@pytest.mark.asyncio
async def test_get_class_detail_degrades_when_assignment_list_fails():
    """Class detail should still return when assignment list call fails."""
    from unittest.mock import AsyncMock, MagicMock
    from models.data import ClassDetail

    mock_client = MagicMock()
    fake_detail = ClassDetail(class_id="uuid-1", name="Class A")

    with patch("tools.data_tools._should_use_mock", return_value=False), \
         patch("tools.data_tools._get_client", return_value=mock_client), \
         patch("adapters.class_adapter.get_detail", new_callable=AsyncMock, return_value=fake_detail), \
         patch("adapters.class_adapter.list_assignments", new_callable=AsyncMock, side_effect=RuntimeError("assignments down")):
        result = await get_class_detail("t-001", "uuid-1")

    assert result["class_id"] == "uuid-1"
    assert result["name"] == "Class A"
    assert result["assignments"] == []
    assert result["assignment_count"] == 0
    assert result["warning"] == "assignments_unavailable"


@pytest.mark.asyncio
async def test_get_assignment_submissions_calls_adapter_when_not_mock():
    """When USE_MOCK_DATA=False and backend succeeds, should use adapter."""
    from unittest.mock import AsyncMock, MagicMock
    from models.data import SubmissionData, SubmissionRecord

    mock_client = MagicMock()
    fake_data = SubmissionData(
        assignment_id="a-1",
        title="Test 1",
        submissions=[SubmissionRecord(student_id="s-1", name="Alice", score=90)],
        scores=[90],
    )

    with patch("tools.data_tools._should_use_mock", return_value=False), \
         patch("tools.data_tools._get_client", return_value=mock_client), \
         patch("adapters.submission_adapter.get_submissions", new_callable=AsyncMock, return_value=fake_data):
        result = await get_assignment_submissions("t-001", "a-1")

    assert result["assignment_id"] == "a-1"
    assert len(result["submissions"]) == 1
    assert result["scores"] == [90]


@pytest.mark.asyncio
async def test_get_student_grades_calls_adapter_when_not_mock():
    """When USE_MOCK_DATA=False and backend succeeds, should use adapter."""
    from unittest.mock import AsyncMock, MagicMock
    from models.data import GradeData, GradeRecord

    mock_client = MagicMock()
    fake_data = GradeData(
        student_id="s-1",
        name="Alice",
        total_graded=1,
        grades=[GradeRecord(assignment_id="a-1", title="Test 1", score=90)],
    )

    with patch("tools.data_tools._should_use_mock", return_value=False), \
         patch("tools.data_tools._get_client", return_value=mock_client), \
         patch("adapters.grade_adapter.get_student_submissions", new_callable=AsyncMock, return_value=fake_data):
        result = await get_student_grades("t-001", "s-1")

    assert result["student_id"] == "s-1"
    assert result["name"] == "Alice"
    assert len(result["grades"]) == 1


# ── Stats Tools (sync, unchanged) ─────────────────────────────────────────


def test_calculate_stats_all_metrics():
    data = [58, 85, 72, 91, 65]
    result = calculate_stats(data)
    assert result["count"] == 5
    assert result["mean"] == 74.2
    assert result["median"] == 72.0
    assert "stddev" in result
    assert result["min"] == 58.0
    assert result["max"] == 91.0
    assert "percentiles" in result
    assert "p25" in result["percentiles"]
    assert "distribution" in result
    assert len(result["distribution"]["labels"]) == 7
    assert sum(result["distribution"]["counts"]) == 5


def test_calculate_stats_selected_metrics():
    data = [10, 20, 30]
    result = calculate_stats(data, metrics=["mean", "min", "max"])
    assert result["mean"] == 20.0
    assert result["min"] == 10.0
    assert result["max"] == 30.0
    assert "median" not in result
    assert "distribution" not in result


def test_calculate_stats_empty():
    result = calculate_stats([])
    assert "error" in result


def test_compare_performance():
    group_a = [80, 85, 90]
    group_b = [60, 65, 70]
    result = compare_performance(group_a, group_b)
    assert "group_a" in result
    assert "group_b" in result
    assert "difference" in result
    assert result["difference"]["mean"] > 0


def test_compare_performance_empty_group():
    result = compare_performance([], [1, 2, 3])
    assert "error" in result
