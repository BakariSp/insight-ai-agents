"""Data retrieval tools — mock versions for Phase 1.

Each tool returns structured data that mirrors the Java backend API responses.
In Phase 5 these will be replaced with real httpx calls.
"""

from services.mock_data import CLASSES, CLASS_DETAILS, SUBMISSIONS, STUDENT_GRADES


def get_teacher_classes(teacher_id: str) -> dict:
    """Get the list of classes assigned to a teacher.

    Args:
        teacher_id: The teacher's unique identifier (e.g. "t-001").

    Returns:
        Dictionary with teacher_id and list of class summaries.
    """
    classes = CLASSES.get(teacher_id, [])
    return {"teacher_id": teacher_id, "classes": classes}


def get_class_detail(teacher_id: str, class_id: str) -> dict:
    """Get detailed information about a specific class including students and assignments.

    Args:
        teacher_id: The teacher's unique identifier.
        class_id: The class identifier (e.g. "class-hk-f1a").

    Returns:
        Dictionary with full class details, student roster, and assignment list.
    """
    detail = CLASS_DETAILS.get(class_id)
    if not detail:
        return {"error": f"Class {class_id} not found", "teacher_id": teacher_id}
    return {**detail, "teacher_id": teacher_id}


def get_assignment_submissions(teacher_id: str, assignment_id: str) -> dict:
    """Get all student submissions for a specific assignment.

    Args:
        teacher_id: The teacher's unique identifier.
        assignment_id: The assignment identifier (e.g. "a-001").

    Returns:
        Dictionary with assignment info, submissions list, and raw scores array.
    """
    data = SUBMISSIONS.get(assignment_id)
    if not data:
        return {"error": f"Assignment {assignment_id} not found", "teacher_id": teacher_id}
    return {**data, "teacher_id": teacher_id}


def get_student_grades(teacher_id: str, student_id: str) -> dict:
    """Get all grades for a specific student.

    Args:
        teacher_id: The teacher's unique identifier.
        student_id: The student identifier (e.g. "s-001").

    Returns:
        Dictionary with student info and list of assignment grades.
    """
    data = STUDENT_GRADES.get(student_id)
    if not data:
        return {"error": f"Student {student_id} not found", "teacher_id": teacher_id}
    return {**data, "teacher_id": teacher_id}
