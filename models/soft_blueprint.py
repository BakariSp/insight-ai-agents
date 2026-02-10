"""Soft Blueprint models — parameterized instruction templates with entity slots.

The core idea: capture INTENT (what to do), not WORKFLOW (how to do it).
NativeAgent will autonomously select tools at execution time.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from models.base import CamelModel


class EntitySlotType(str, Enum):
    """EntitySlot type enum — matches Java backend."""

    CLASS_SELECTOR = "class_selector"
    ASSIGNMENT_SELECTOR = "assignment_selector"
    STUDENT_SELECTOR = "student_selector"
    DATE_RANGE = "date_range"
    TEXT_INPUT = "text_input"
    NUMBER_INPUT = "number_input"


class ArtifactType(str, Enum):
    """Expected artifact type enum — matches Java backend."""

    REPORT = "report"
    QUIZ = "quiz"
    INTERACTIVE = "interactive"
    DOCUMENT = "document"


class EntitySlot(CamelModel):
    """Parameterized entity slot (e.g., class_selector, assignment_selector)."""

    key: str = Field(..., description="Slot key for template substitution (e.g., 'class_id')")
    label: str = Field(..., description="Human-readable label (e.g., '班级')")
    type: EntitySlotType = Field(..., description="Slot type determines UI widget")
    required: bool = Field(True, description="Whether this slot must be filled")
    depends_on: str | None = Field(
        None, description="Parent slot key for cascade (e.g., assignment depends on class)"
    )


class TabHint(CamelModel):
    """Tab structure hint for report layout."""

    key: str = Field(..., description="Tab key (e.g., 'overview')")
    label: str = Field(..., description="Tab display label (e.g., '整体概览')")
    description: str | None = Field(None, description="What content this tab should contain")


class OutputHints(CamelModel):
    """Hints about expected output structure — not enforced, just guidance."""

    expected_artifacts: list[ArtifactType] = Field(
        default_factory=list,
        description="What artifacts to generate (report, quiz, interactive...)",
    )
    tabs: list[TabHint] | None = Field(
        None, description="Tab structure (only for 'report' artifact)"
    )
    preferred_components: list[str] | None = Field(
        None, description="Component types to use (kpi_grid, chart, table...)"
    )


class SoftBlueprint(CamelModel):
    """
    Soft Blueprint — distilled from conversation.

    The core idea: capture INTENT (what to do), not WORKFLOW (how to do it).
    NativeAgent will autonomously select tools at execution time.
    """

    name: str = Field(..., max_length=200, description="Blueprint display name")
    description: str | None = Field(None, description="Blueprint description")
    icon: str = Field("chart", description="Icon identifier (chart, quiz, file-text, lightbulb...)")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")

    entity_slots: list[EntitySlot] = Field(
        ..., description="Parameterized entities (class, assignment, etc.)"
    )
    execution_prompt: str = Field(
        ...,
        max_length=5000,
        description="Distilled instruction template with placeholders like {class_name}",
    )
    output_hints: OutputHints = Field(
        default_factory=OutputHints, description="Structure hints for output"
    )

    source_conversation_id: str | None = Field(
        None, description="Source conversation ID for traceability"
    )
