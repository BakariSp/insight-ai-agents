"""Tests for Soft Blueprint models."""

import pytest

from models.soft_blueprint import (
    ArtifactType,
    EntitySlot,
    EntitySlotType,
    OutputHints,
    SoftBlueprint,
    TabHint,
)


def test_entity_slot_serialization():
    """Test EntitySlot serialization with camelCase."""
    slot = EntitySlot(
        key="class_id",
        label="班级",
        type=EntitySlotType.CLASS_SELECTOR,
        required=True,
        depends_on=None,
    )

    data = slot.model_dump(by_alias=True)
    assert data["key"] == "class_id"
    assert data["label"] == "班级"
    assert data["type"] == "class_selector"
    assert data["required"] is True
    assert data["dependsOn"] is None


def test_entity_slot_with_dependency():
    """Test EntitySlot with depends_on relationship."""
    slot = EntitySlot(
        key="assignment_id",
        label="作业",
        type=EntitySlotType.ASSIGNMENT_SELECTOR,
        required=True,
        depends_on="class_id",
    )

    data = slot.model_dump(by_alias=True)
    assert data["dependsOn"] == "class_id"


def test_tab_hint():
    """Test TabHint model."""
    tab = TabHint(key="overview", label="整体概览", description="KPI and summary")

    data = tab.model_dump(by_alias=True)
    assert data["key"] == "overview"
    assert data["label"] == "整体概览"
    assert data["description"] == "KPI and summary"


def test_output_hints():
    """Test OutputHints model."""
    hints = OutputHints(
        expected_artifacts=[ArtifactType.REPORT],
        tabs=[
            TabHint(key="overview", label="Overview"),
            TabHint(key="details", label="Details"),
        ],
        preferred_components=["kpi_grid", "chart"],
    )

    data = hints.model_dump(by_alias=True)
    assert data["expectedArtifacts"] == ["report"]
    assert len(data["tabs"]) == 2
    assert data["preferredComponents"] == ["kpi_grid", "chart"]


def test_soft_blueprint_full():
    """Test full SoftBlueprint model."""
    blueprint = SoftBlueprint(
        name="Test Blueprint",
        description="Test description",
        icon="chart",
        tags=["test", "analysis"],
        entity_slots=[
            EntitySlot(
                key="class_id", label="Class", type=EntitySlotType.CLASS_SELECTOR, required=True
            )
        ],
        execution_prompt="Analyze {class_name} performance",
        output_hints=OutputHints(
            expected_artifacts=[ArtifactType.REPORT],
            tabs=[TabHint(key="overview", label="Overview")],
        ),
        source_conversation_id="conv-123",
    )

    assert blueprint.name == "Test Blueprint"
    assert len(blueprint.entity_slots) == 1
    assert blueprint.entity_slots[0].key == "class_id"
    assert "{class_name}" in blueprint.execution_prompt
    assert blueprint.output_hints.expected_artifacts == [ArtifactType.REPORT]

    # Test serialization
    data = blueprint.model_dump(by_alias=True)
    assert data["name"] == "Test Blueprint"
    assert data["entitySlots"][0]["key"] == "class_id"
    assert data["executionPrompt"] == "Analyze {class_name} performance"
    assert data["outputHints"]["expectedArtifacts"] == ["report"]


def test_soft_blueprint_minimal():
    """Test SoftBlueprint with minimal fields."""
    blueprint = SoftBlueprint(
        name="Minimal Blueprint",
        entity_slots=[
            EntitySlot(
                key="topic", label="Topic", type=EntitySlotType.TEXT_INPUT, required=True
            )
        ],
        execution_prompt="Generate quiz about {topic}",
    )

    assert blueprint.name == "Minimal Blueprint"
    assert blueprint.icon == "chart"  # default
    assert blueprint.tags == []  # default
    assert blueprint.description is None
    assert blueprint.source_conversation_id is None


def test_entity_slot_type_enum():
    """Test EntitySlotType enum values."""
    assert EntitySlotType.CLASS_SELECTOR.value == "class_selector"
    assert EntitySlotType.ASSIGNMENT_SELECTOR.value == "assignment_selector"
    assert EntitySlotType.STUDENT_SELECTOR.value == "student_selector"
    assert EntitySlotType.DATE_RANGE.value == "date_range"
    assert EntitySlotType.TEXT_INPUT.value == "text_input"
    assert EntitySlotType.NUMBER_INPUT.value == "number_input"


def test_artifact_type_enum():
    """Test ArtifactType enum values."""
    assert ArtifactType.REPORT.value == "report"
    assert ArtifactType.QUIZ.value == "quiz"
    assert ArtifactType.INTERACTIVE.value == "interactive"
    assert ArtifactType.DOCUMENT.value == "document"


def test_soft_blueprint_validation():
    """Test validation constraints."""
    # Test max_length on name
    with pytest.raises(Exception):  # Pydantic validation error
        SoftBlueprint(
            name="x" * 201,  # Exceeds max_length=200
            entity_slots=[
                EntitySlot(
                    key="test", label="Test", type=EntitySlotType.TEXT_INPUT, required=True
                )
            ],
            execution_prompt="Test prompt",
        )

    # Test max_length on execution_prompt
    with pytest.raises(Exception):  # Pydantic validation error
        SoftBlueprint(
            name="Test",
            entity_slots=[
                EntitySlot(
                    key="test", label="Test", type=EntitySlotType.TEXT_INPUT, required=True
                )
            ],
            execution_prompt="x" * 5001,  # Exceeds max_length=5000
        )
