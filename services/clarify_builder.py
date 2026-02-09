"""Clarify options builder — generates structured interactive options for clarification.

When the RouterAgent returns a `clarify` intent with a `route_hint`, this service
builds the appropriate ClarifyOptions by calling data tools to populate choices.
"""

from __future__ import annotations

import logging

from models.conversation import ClarifyChoice, ClarifyOptions
from tools.data_tools import get_teacher_classes as _raw_get_teacher_classes

logger = logging.getLogger(__name__)

# Preset time range options (static, no tool call needed)
_TIME_RANGE_CHOICES = [
    ClarifyChoice(label="This week", value="this_week", description="Last 7 days"),
    ClarifyChoice(label="This month", value="this_month", description="Last 30 days"),
    ClarifyChoice(
        label="This semester", value="this_semester", description="Current semester"
    ),
]

_DEFAULT_CLASS_CHOICES = [
    ClarifyChoice(
        label="Form 1A",
        value="class-hk-f1a",
        description="Fallback option when teacher classes are unavailable",
    ),
    ClarifyChoice(
        label="Form 1B",
        value="class-hk-f1b",
        description="Fallback option when teacher classes are unavailable",
    ),
]


async def build_clarify_options(
    route_hint: str | None,
    teacher_id: str = "",
) -> ClarifyOptions:
    """Build ClarifyOptions based on the route hint.

    Dispatches to the appropriate builder based on what information is missing:
    - "needClassId" → fetch teacher's classes → single-select class list
    - "needTimeRange" → preset time range options
    - "needAssignment" → fetch class assignments → single-select assignment list
    - "needSubject" → preset subject options

    Args:
        route_hint: What the router thinks is missing (e.g. "needClassId").
        teacher_id: Teacher ID for data tool calls.

    Returns:
        A ClarifyOptions with populated choices.
    """
    if route_hint == "needClassId":
        return await _build_class_choices(teacher_id)
    if route_hint == "needTimeRange":
        return _build_time_range_choices()
    if route_hint == "needAssignment":
        return await _build_assignment_choices(teacher_id)
    if route_hint == "needSubject":
        return _build_subject_choices()

    # Unknown hint — return empty options with custom input allowed
    logger.warning("Unknown route_hint: %s", route_hint)
    return ClarifyOptions(allow_custom_input=True)


async def _build_class_choices(teacher_id: str) -> ClarifyOptions:
    """Fetch teacher's classes and return as selectable options."""
    try:
        data = await _raw_get_teacher_classes(teacher_id=teacher_id)
        classes = data.get("classes", [])
        choices = [
            ClarifyChoice(
                label=cls.get("name", cls.get("class_id", "")),
                value=cls.get("class_id", ""),
                description=f"{cls.get('grade', '')} · {cls.get('subject', '')} · "
                f"{cls.get('student_count', '?')} students",
            )
            for cls in classes
        ]
    except Exception:
        logger.exception("Failed to fetch classes for teacher %s", teacher_id)
        choices = []

    if not choices:
        # Keep clarify usable even when teacher_id is missing or data tool is unavailable.
        choices = _DEFAULT_CLASS_CHOICES

    return ClarifyOptions(
        type="single_select",
        choices=choices,
        allow_custom_input=True,
    )


def _build_time_range_choices() -> ClarifyOptions:
    """Return preset time range options."""
    return ClarifyOptions(
        type="single_select",
        choices=_TIME_RANGE_CHOICES,
        allow_custom_input=True,
    )


async def _build_assignment_choices(teacher_id: str) -> ClarifyOptions:
    """Fetch assignments and return as selectable options.

    Note: This requires a class_id which may not be available yet.
    Falls back to empty choices with custom input.
    """
    # Without a class_id, we can't fetch assignments directly.
    # Return empty choices encouraging the user to specify.
    return ClarifyOptions(
        type="single_select",
        choices=[],
        allow_custom_input=True,
    )


def _build_subject_choices() -> ClarifyOptions:
    """Return preset subject options."""
    return ClarifyOptions(
        type="single_select",
        choices=[
            ClarifyChoice(label="English", value="english", description="English Language"),
            ClarifyChoice(label="Mathematics", value="math", description="Mathematics"),
            ClarifyChoice(label="Chinese", value="chinese", description="Chinese Language"),
            ClarifyChoice(label="Science", value="science", description="General Science"),
        ],
        allow_custom_input=True,
    )
