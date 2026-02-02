"""Adapter for Java Grade / Student Submission APIs → internal GradeData.

Java API endpoints handled:
- GET /dify/teacher/{teacherId}/submissions/students/{studentId} → GradeData
- GET /dify/student/{studentId}/courses/{courseId}/mygrades      → GradeData
"""

from __future__ import annotations

import logging
from typing import Any

from models.data import GradeData, GradeRecord
from services.java_client import JavaClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response → Internal Model conversions
# ---------------------------------------------------------------------------

def _parse_grade_from_submission(raw: dict[str, Any]) -> GradeRecord:
    """Convert a Java ``SubmissionDTO`` (from student submissions endpoint) to :class:`GradeRecord`."""
    max_score = raw.get("totalPoints", raw.get("maxScore", 100)) or 100
    score = raw.get("score", 0) or 0
    return GradeRecord(
        assignment_id=str(raw.get("assignmentUid") or raw.get("assignmentId", "")),
        title=raw.get("assignmentTitle", ""),
        score=score,
        max_score=max_score,
        percentage=(score / max_score * 100) if max_score > 0 else None,
    )


def _parse_grade_history_item(raw: dict[str, Any]) -> GradeRecord:
    """Convert a Java ``GradeHistoryItem`` to :class:`GradeRecord`."""
    return GradeRecord(
        assignment_id=str(raw.get("assignmentId", "")),
        title=raw.get("assignmentName", ""),
        score=raw.get("score", 0) or 0,
        max_score=raw.get("totalScore", 100) or 100,
        percentage=raw.get("percentage"),
    )


# ---------------------------------------------------------------------------
# High-level API calls
# ---------------------------------------------------------------------------

async def get_student_submissions(
    client: JavaClient, teacher_id: str, student_id: str
) -> GradeData:
    """Fetch all submission records for a student (teacher view).

    GET /dify/teacher/{teacherId}/submissions/students/{studentId}
    """
    resp = await client.get(
        f"/dify/teacher/{teacher_id}/submissions/students/{student_id}"
    )
    items = _unwrap_data(resp)

    if not isinstance(items, list):
        logger.warning("get_student_submissions: expected list, got %s", type(items))
        items = []

    grades = [_parse_grade_from_submission(s) for s in items]
    scores = [g.score for g in grades]

    return GradeData(
        student_id=student_id,
        name=items[0].get("studentName", "") if items else "",
        average_score=sum(scores) / len(scores) if scores else None,
        highest_score=max(scores) if scores else None,
        total_graded=len(grades),
        grades=grades,
    )


async def get_course_grades(
    client: JavaClient, student_id: str, course_id: str
) -> GradeData:
    """Fetch student's grades for a specific course (student view).

    GET /dify/student/{studentId}/courses/{courseId}/mygrades
    """
    resp = await client.get(
        f"/dify/student/{student_id}/courses/{course_id}/mygrades"
    )
    raw = _unwrap_data(resp)

    if not isinstance(raw, dict):
        logger.warning("get_course_grades: expected dict, got %s", type(raw))
        return GradeData(student_id=student_id)

    history = raw.get("gradeHistory", [])
    grades = [_parse_grade_history_item(item) for item in history]

    return GradeData(
        student_id=student_id,
        average_score=raw.get("averageScore"),
        highest_score=raw.get("highestScore"),
        total_graded=raw.get("totalGraded", len(grades)),
        grades=grades,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unwrap_data(response: Any) -> Any:
    """Extract ``data`` from Java ``Result<T>`` wrapper."""
    if isinstance(response, dict) and "data" in response:
        return response["data"]
    return response
