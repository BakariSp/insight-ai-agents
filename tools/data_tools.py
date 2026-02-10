"""Data retrieval tools — fetch from Java backend with debug-only mock fallback.

Each tool calls the adapter layer → JavaClient for real data.
When ``debug=true`` and ``USE_MOCK_DATA=true``, tools may fall back to mock data.
In production (debug=false), missing teacher_id or backend errors return
structured error payloads instead of mock data.

The return type (plain dict) is preserved so Planner/Executor code
does not need changes.
"""

from __future__ import annotations

import logging
from typing import Any

from config.settings import get_settings
from services.mock_data import CLASSES, CLASS_DETAILS, SUBMISSIONS, STUDENT_GRADES

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mock fallback helpers (unchanged from Phase 1)
# ---------------------------------------------------------------------------

def _mock_teacher_classes(teacher_id: str) -> dict:
    classes = CLASSES.get(teacher_id, [])
    return {"teacher_id": teacher_id, "classes": classes}


def _mock_class_detail(teacher_id: str, class_id: str) -> dict:
    detail = CLASS_DETAILS.get(class_id)
    if not detail:
        return {"error": f"Class {class_id} not found", "teacher_id": teacher_id}
    return {**detail, "teacher_id": teacher_id}


def _mock_assignment_submissions(teacher_id: str, assignment_id: str) -> dict:
    data = SUBMISSIONS.get(assignment_id)
    if not data:
        return {"error": f"Assignment {assignment_id} not found", "teacher_id": teacher_id}
    return {**data, "teacher_id": teacher_id}


def _mock_student_grades(teacher_id: str, student_id: str) -> dict:
    data = STUDENT_GRADES.get(student_id)
    if not data:
        return {"error": f"Student {student_id} not found", "teacher_id": teacher_id}
    return {**data, "teacher_id": teacher_id}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _should_use_mock() -> bool:
    settings = get_settings()
    return settings.debug and settings.use_mock_data


def _normalize_teacher_id(teacher_id: str | None) -> str:
    """Normalize optional teacher_id to a clean string."""
    if teacher_id is None:
        return ""
    tid = str(teacher_id).strip()
    if not tid:
        return ""
    if tid.lower() in {"none", "null", "undefined"}:
        return ""
    return tid


def _get_client():
    """Lazy import to avoid circular dependency at module load time."""
    from services.java_client import get_java_client
    return get_java_client()


# ---------------------------------------------------------------------------
# Public tool functions (async, registered in TOOL_REGISTRY)
# ---------------------------------------------------------------------------

async def get_teacher_classes(teacher_id: str) -> dict:
    """Get the list of classes assigned to a teacher.

    Args:
        teacher_id: The teacher's unique identifier (UUID).

    Returns:
        Dictionary with teacher_id and list of class summaries.
    """
    teacher_id = _normalize_teacher_id(teacher_id)
    if not teacher_id:
        logger.warning("get_teacher_classes called without teacher_id")
        return {"status": "error", "reason": "teacher_id is required", "teacher_id": teacher_id, "classes": []}
    if _should_use_mock():
        return _mock_teacher_classes(teacher_id)

    try:
        from adapters.class_adapter import list_classes
        client = _get_client()
        classes = await list_classes(client, teacher_id)
        return {
            "teacher_id": teacher_id,
            "classes": [c.model_dump() for c in classes],
        }
    except ValueError:
        # Null-data from Java backend — transient error.
        # Re-raise so PydanticAI's max_retries triggers automatic retry.
        raise
    except Exception as exc:
        logger.exception("get_teacher_classes failed")
        if _should_use_mock():
            return _mock_teacher_classes(teacher_id)
        return {"status": "error", "reason": str(exc), "teacher_id": teacher_id, "classes": []}


async def get_class_detail(teacher_id: str, class_id: str) -> dict:
    """Get detailed information about a specific class including students and assignments.

    Args:
        teacher_id: The teacher's unique identifier (UUID).
        class_id: The class identifier (UUID or numeric ID).

    Returns:
        Dictionary with full class details, student roster, and assignment list.
    """
    teacher_id = _normalize_teacher_id(teacher_id)
    if not teacher_id:
        logger.warning("get_class_detail called without teacher_id")
        return {"status": "error", "reason": "teacher_id is required", "class_id": class_id}
    if _should_use_mock():
        return _mock_class_detail(teacher_id, class_id)

    try:
        from adapters.class_adapter import get_detail, list_assignments
        client = _get_client()
        detail = await get_detail(client, teacher_id, class_id)
        assignments = await list_assignments(client, teacher_id, class_id)
        detail.assignments = assignments
        result = detail.model_dump()
        result["teacher_id"] = teacher_id
        # Override stale counter with real assignment count
        result["assignment_count"] = len(assignments)
        return result
    except ValueError:
        raise  # Null-data transient error — let PydanticAI retry
    except Exception as exc:
        logger.exception("get_class_detail failed")
        if _should_use_mock():
            return _mock_class_detail(teacher_id, class_id)
        return {"status": "error", "reason": str(exc), "teacher_id": teacher_id, "class_id": class_id}


async def get_assignment_submissions(teacher_id: str, assignment_id: str) -> dict:
    """Get all student submissions for a specific assignment.

    Args:
        teacher_id: The teacher's unique identifier (UUID).
        assignment_id: The assignment identifier (UUID).

    Returns:
        Dictionary with assignment info, submissions list, and raw scores array.
    """
    teacher_id = _normalize_teacher_id(teacher_id)
    if not teacher_id:
        logger.warning("get_assignment_submissions called without teacher_id")
        return {
            "status": "error",
            "reason": "teacher_id is required",
            "teacher_id": teacher_id,
            "assignment_id": assignment_id,
            "submissions": [],
            "scores": [],
        }
    if _should_use_mock():
        return _mock_assignment_submissions(teacher_id, assignment_id)

    try:
        from adapters.submission_adapter import get_submissions
        client = _get_client()
        data = await get_submissions(client, teacher_id, assignment_id)
        result = data.model_dump()
        result["teacher_id"] = teacher_id
        return result
    except ValueError:
        raise  # Null-data transient error — let PydanticAI retry
    except Exception as exc:
        logger.exception("get_assignment_submissions failed")
        if _should_use_mock():
            return _mock_assignment_submissions(teacher_id, assignment_id)
        return {
            "status": "error",
            "reason": str(exc),
            "teacher_id": teacher_id,
            "assignment_id": assignment_id,
            "submissions": [],
            "scores": [],
        }


async def get_student_grades(teacher_id: str, student_id: str) -> dict:
    """Get all grades for a specific student.

    Args:
        teacher_id: The teacher's unique identifier (UUID).
        student_id: The student identifier (UUID).

    Returns:
        Dictionary with student info and list of assignment grades.
    """
    teacher_id = _normalize_teacher_id(teacher_id)
    if not teacher_id:
        logger.warning("get_student_grades called without teacher_id")
        return {
            "status": "error",
            "reason": "teacher_id is required",
            "teacher_id": teacher_id,
            "student_id": student_id,
            "grades": [],
        }
    if _should_use_mock():
        return _mock_student_grades(teacher_id, student_id)

    try:
        from adapters.grade_adapter import get_student_submissions
        client = _get_client()
        data = await get_student_submissions(client, teacher_id, student_id)
        result = data.model_dump()
        result["teacher_id"] = teacher_id
        return result
    except ValueError:
        raise  # Null-data transient error — let PydanticAI retry
    except Exception as exc:
        logger.exception("get_student_grades failed")
        if _should_use_mock():
            return _mock_student_grades(teacher_id, student_id)
        return {
            "status": "error",
            "reason": str(exc),
            "teacher_id": teacher_id,
            "student_id": student_id,
            "grades": [],
        }
