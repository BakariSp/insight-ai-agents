"""Interaction trace models — record a complete teacher interaction session.

Used for Phase 4 "Blueprint post-hoc crystallisation": after the teacher is
satisfied with a generated result, the trace can be analysed by a Plan Agent
to produce a reusable Blueprint / WorkflowTemplate.
"""

from __future__ import annotations

from models.base import CamelModel


class SkillCall(CamelModel):
    """Record of a single skill invocation during a conversation."""

    skill_name: str
    input_params: dict = {}
    output_summary: str = ""
    duration_ms: int = 0
    was_successful: bool = True


class TeacherEdit(CamelModel):
    """Record of a teacher's manual edit on generated content."""

    action: str  # "replace" | "delete" | "edit" | "reorder"
    target_index: int = 0
    detail: str = ""


class InteractionTrace(CamelModel):
    """Full trace of a teacher interaction — from first message to final output."""

    conversation_id: str
    teacher_id: str
    created_at: str = ""

    # Trigger
    initial_message: str = ""
    all_messages: list[str] = []

    # Skill calls
    skill_calls: list[SkillCall] = []

    # Output
    output_type: str = ""  # "quiz" | "report" | "lesson_plan"
    output_data: dict = {}

    # Teacher modifications
    teacher_edits: list[TeacherEdit] = []
