"""Rubric retrieval tools for question generation and assessment.

Phase 7: These tools provide access to structured rubrics (评分标准)
that guide question generation and scoring.
"""

from __future__ import annotations

from typing import Any

from services.rubric_service import (
    get_rubric_for_task,
    list_rubrics,
    get_rubric_context,
)


async def get_rubric(
    subject: str,
    task_type: str,
    level: str = "DSE",
) -> dict[str, Any]:
    """获取指定科目和题型的评分标准

    Args:
        subject: 科目 (e.g., "English", "Chinese", "Math")
        task_type: 题型 (e.g., "essay", "reading_comprehension", "short_answer")
        level: 考试级别 (默认 "DSE")

    Returns:
        评分标准结构，包含 criteria, levels, commonErrors
        若未找到则返回 error 字段
    """
    rubric = get_rubric_for_task(subject, task_type, level)

    if not rubric:
        return {
            "error": f"No rubric found for {subject} {task_type} at {level} level",
            "suggestion": "Try listing available rubrics with list_available_rubrics",
        }

    # Return context suitable for LLM use
    return get_rubric_context(rubric)


async def list_available_rubrics(
    subject: str = "",
    task_type: str = "",
    level: str = "",
) -> dict[str, Any]:
    """列出可用的评分标准

    Args:
        subject: 可选，按科目筛选
        task_type: 可选，按题型筛选
        level: 可选，按级别筛选

    Returns:
        包含 rubrics 列表的字典，每项有 id, name, subject, taskType, level
    """
    rubrics = list_rubrics(subject=subject, task_type=task_type, level=level)

    return {
        "rubrics": rubrics,
        "count": len(rubrics),
        "filters": {
            "subject": subject or "all",
            "taskType": task_type or "all",
            "level": level or "all",
        },
    }
