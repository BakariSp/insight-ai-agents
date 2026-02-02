"""Tests for FastMCP tools — data tools and stats tools."""

import pytest

from tools.data_tools import (
    get_assignment_submissions,
    get_class_detail,
    get_student_grades,
    get_teacher_classes,
)
from tools.stats_tools import calculate_stats, compare_performance


# ── Data Tools ──────────────────────────────────────────────


def test_get_teacher_classes_found():
    result = get_teacher_classes("t-001")
    assert result["teacher_id"] == "t-001"
    assert len(result["classes"]) == 2
    assert result["classes"][0]["class_id"] == "class-hk-f1a"


def test_get_teacher_classes_not_found():
    result = get_teacher_classes("t-999")
    assert result["teacher_id"] == "t-999"
    assert result["classes"] == []


def test_get_class_detail_found():
    result = get_class_detail("t-001", "class-hk-f1a")
    assert result["class_id"] == "class-hk-f1a"
    assert result["name"] == "Form 1A"
    assert len(result["students"]) == 5
    assert len(result["assignments"]) == 2


def test_get_class_detail_not_found():
    result = get_class_detail("t-001", "class-xxx")
    assert "error" in result


def test_get_assignment_submissions_found():
    result = get_assignment_submissions("t-001", "a-001")
    assert result["assignment_id"] == "a-001"
    assert len(result["submissions"]) == 5
    assert result["scores"] == [58, 85, 72, 91, 65]


def test_get_assignment_submissions_not_found():
    result = get_assignment_submissions("t-001", "a-999")
    assert "error" in result


def test_get_student_grades_found():
    result = get_student_grades("t-001", "s-001")
    assert result["student_id"] == "s-001"
    assert result["name"] == "Wong Ka Ho"
    assert len(result["grades"]) == 2


def test_get_student_grades_not_found():
    result = get_student_grades("t-001", "s-999")
    assert "error" in result


# ── Stats Tools ─────────────────────────────────────────────


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
