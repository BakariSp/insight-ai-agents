"""Platform operation tools — interact with Java backend for business operations.

Phase 1: These return placeholder responses.
Phase 2: Will connect to Java backend POST /api/assignments, etc.
"""

from __future__ import annotations


async def save_as_assignment(
    title: str,
    questions: list[dict],
    class_id: str = "",
    due_date: str = "",
    description: str = "",
) -> dict:
    """Save generated questions as an assignment draft.

    Args:
        title: Assignment title.
        questions: List of question dicts (QuizQuestionV1 format).
        class_id: Target class ID (optional; omit to save as draft).
        due_date: Due date in ISO format (optional).
        description: Assignment description.

    Returns:
        {"assignment_id": str|None, "message": str, "questions_count": int}
    """
    # Phase 1: return guidance message
    # Phase 2: POST to Java backend /api/assignments
    return {
        "assignment_id": None,
        "message": (
            f"Prepared {len(questions)} questions. "
            "Please click 'Save as Assignment' in the side panel to publish."
        ),
        "questions_count": len(questions),
    }


async def create_share_link(
    assignment_id: str,
) -> dict:
    """Generate an anonymous share link for a saved assignment.

    Args:
        assignment_id: The assignment ID to create a share link for.

    Returns:
        {"share_url": str|None, "message": str}
    """
    # Phase 1: return guidance message
    # Phase 2: POST to Java backend /api/assignments/{id}/share-link
    return {
        "share_url": None,
        "message": (
            "Share link feature coming soon. "
            "Please publish via the assignment management page for now."
        ),
    }
