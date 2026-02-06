"""Adapter for Java Submission APIs → internal SubmissionData.

Java API endpoints handled:
- GET /dify/teacher/{teacherId}/submissions/assignments/{assignmentId} → SubmissionData
"""

from __future__ import annotations

import logging
from typing import Any

from models.data import SubmissionData, SubmissionRecord
from services.java_client import JavaClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response → Internal Model conversions
# ---------------------------------------------------------------------------

def _parse_submission(raw: dict[str, Any]) -> SubmissionRecord:
    """Convert a Java ``SubmissionDTO`` to :class:`SubmissionRecord`."""
    return SubmissionRecord(
        student_id=str(raw.get("uid") or raw.get("studentId", "")),
        name=raw.get("studentName") or raw.get("guestName", ""),
        score=raw.get("score"),
        submitted=raw.get("status", "").lower() not in ("not_submitted", ""),
        status=raw.get("status", ""),
        feedback=raw.get("feedback") or raw.get("teacherComment") or "",
    )


# ---------------------------------------------------------------------------
# High-level API calls
# ---------------------------------------------------------------------------

async def get_submissions(
    client: JavaClient, teacher_id: str, assignment_id: str
) -> SubmissionData:
    """Fetch all submissions for an assignment.

    GET /dify/teacher/{teacherId}/submissions/assignments/{assignmentId}
    """
    resp = await client.get(
        f"/dify/teacher/{teacher_id}/submissions/assignments/{assignment_id}"
    )
    items = _unwrap_data(resp)

    if not isinstance(items, list):
        logger.warning("get_submissions: expected list, got %s", type(items))
        items = []

    records = [_parse_submission(s) for s in items]
    scores = [r.score for r in records if r.score is not None]

    # Try to extract assignment title from the first record
    title = items[0].get("assignmentTitle", "") if items else ""

    return SubmissionData(
        assignment_id=assignment_id,
        title=title,
        submissions=records,
        scores=scores,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unwrap_data(response: Any) -> Any:
    """Extract ``data`` from Java ``Result<T>`` wrapper."""
    if isinstance(response, dict) and "data" in response:
        return response["data"]
    return response
