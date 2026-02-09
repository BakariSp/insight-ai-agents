"""Adapter for Java Classroom / Class APIs → internal ClassInfo / ClassDetail.

Java API endpoints handled:
- GET /dify/teacher/{teacherId}/classes/me        → list[ClassInfo]
- GET /dify/teacher/{teacherId}/classes/{classId}  → ClassDetail
- GET /dify/teacher/{teacherId}/classes/{classId}/assignments → list[AssignmentInfo]
"""

from __future__ import annotations

import logging
from typing import Any

from models.data import AssignmentInfo, ClassDetail, ClassInfo, StudentInfo
from services.java_client import JavaClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response → Internal Model conversions
# ---------------------------------------------------------------------------

def _parse_classroom(raw: dict[str, Any]) -> ClassInfo:
    """Convert a single Java ``Classroom`` object to :class:`ClassInfo`."""
    return ClassInfo(
        class_id=str(raw.get("uid") or raw.get("id", "")),
        name=raw.get("name", ""),
        grade=raw.get("grade", ""),
        subject=raw.get("subject", ""),
        student_count=raw.get("studentCount", 0),
        assignment_count=raw.get("assignmentCount", 0),
        description=raw.get("description", ""),
        semester_label=raw.get("semesterLabel") or "",
    )


def _parse_assignment(raw: dict[str, Any]) -> AssignmentInfo:
    """Convert a Java ``ClassAssignmentDTO`` to :class:`AssignmentInfo`."""
    return AssignmentInfo(
        assignment_id=str(raw.get("assignmentId") or raw.get("uid") or raw.get("id", "")),
        title=raw.get("title", ""),
        type=raw.get("assignmentType") or raw.get("type") or "",
        max_score=raw.get("total_points") or raw.get("totalPoints") or raw.get("maxScore") or 100,
        status=raw.get("status") or "",
        due_date=str(raw["due_date"]) if raw.get("due_date") else (str(raw["dueDate"]) if raw.get("dueDate") else None),
        submission_count=raw.get("submission_count") or raw.get("submissionCount") or 0,
        total_students=raw.get("total_students") or raw.get("totalStudents") or 0,
        average_score=raw.get("average_score") or raw.get("averageScore"),
    )


# ---------------------------------------------------------------------------
# High-level API calls (through JavaClient)
# ---------------------------------------------------------------------------

async def list_classes(client: JavaClient, teacher_id: str) -> list[ClassInfo]:
    """Fetch all classes for a teacher.

    GET /dify/teacher/{teacherId}/classes/me
    """
    resp = await client.get(f"/dify/teacher/{teacher_id}/classes/me")
    items = _unwrap_data(resp)
    if not isinstance(items, list):
        logger.warning("list_classes: expected list, got %s", type(items))
        return []
    return [_parse_classroom(c) for c in items]


async def get_detail(client: JavaClient, teacher_id: str, class_id: str) -> ClassDetail:
    """Fetch detailed class info.

    GET /dify/teacher/{teacherId}/classes/{classId}
    """
    resp = await client.get(f"/dify/teacher/{teacher_id}/classes/{class_id}")
    raw = _unwrap_data(resp)
    if not isinstance(raw, dict):
        return ClassDetail(class_id=class_id, name="Unknown")

    # Parse students if returned by Java (C-3: class detail now includes student roster)
    students_raw = raw.get("students")
    students = []
    if isinstance(students_raw, list):
        students = [
            StudentInfo(
                student_id=str(s.get("studentId") or ""),
                name=s.get("name") or "",
                number=str(s.get("studentNo") or ""),
            )
            for s in students_raw
            if isinstance(s, dict)
        ]

    return ClassDetail(
        class_id=str(raw.get("uid") or raw.get("id", class_id)),
        name=raw.get("name", ""),
        grade=raw.get("grade", ""),
        subject=raw.get("subject", ""),
        student_count=raw.get("studentCount", 0),
        students=students,
        assignments=[],
    )


async def list_assignments(
    client: JavaClient, teacher_id: str, class_id: str
) -> list[AssignmentInfo]:
    """Fetch assignments for a class.

    GET /dify/teacher/{teacherId}/classes/{classId}/assignments
    """
    resp = await client.get(
        f"/dify/teacher/{teacher_id}/classes/{class_id}/assignments",
        params={"limit": 100},
    )
    raw = _unwrap_data(resp)

    # Response is PageResponseDTOClassAssignmentDTO → {data: [...], pagination: {...}}
    if isinstance(raw, dict) and "data" in raw:
        items = raw["data"]
    elif isinstance(raw, list):
        items = raw
    else:
        logger.warning("list_assignments: unexpected shape %s", type(raw))
        return []

    return [_parse_assignment(a) for a in items]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unwrap_data(response: Any) -> Any:
    """Extract the ``data`` field from a Java ``Result<T>`` wrapper.

    Java responses have the shape: ``{code, message, data, timestamp}``.
    If the response is already raw data (no wrapper), return as-is.
    """
    if isinstance(response, dict) and "data" in response:
        return response["data"]
    return response
