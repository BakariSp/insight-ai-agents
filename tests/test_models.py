"""Tests for Blueprint Pydantic models — camelCase serialization, nested structure."""

import pytest

from models.blueprint import (
    Blueprint,
    CapabilityLevel,
    ComponentSlot,
    ComponentType,
    ComputeGraph,
    ComputeNode,
    ComputeNodeType,
    DataBinding,
    DataContract,
    DataInputSpec,
    DataSourceType,
    TabSpec,
    UIComposition,
)


def _make_sample_blueprint() -> Blueprint:
    """Build a minimal valid Blueprint for testing."""
    return Blueprint(
        id="bp-test-001",
        name="Test Blueprint",
        description="A test blueprint",
        capability_level=CapabilityLevel.LEVEL_1,
        source_prompt="test prompt",
        data_contract=DataContract(
            inputs=[
                DataInputSpec(id="class", type="class", label="Select Class"),
                DataInputSpec(
                    id="assignment",
                    type="assignment",
                    label="Select Assignment",
                    depends_on="class",
                ),
            ],
            bindings=[
                DataBinding(
                    id="class_detail",
                    source_type=DataSourceType.TOOL,
                    tool_name="get_class_detail",
                    param_mapping={
                        "teacher_id": "$context.teacherId",
                        "class_id": "$input.class",
                    },
                ),
            ],
        ),
        compute_graph=ComputeGraph(
            nodes=[
                ComputeNode(
                    id="score_stats",
                    type=ComputeNodeType.TOOL,
                    tool_name="calculate_stats",
                    tool_args={"data": "$data.submissions.scores"},
                    depends_on=["submissions"],
                    output_key="scoreStats",
                ),
            ]
        ),
        ui_composition=UIComposition(
            layout="tabs",
            tabs=[
                TabSpec(
                    id="overview",
                    label="Overview",
                    slots=[
                        ComponentSlot(
                            id="kpi",
                            component_type=ComponentType.KPI_GRID,
                            data_binding="$compute.scoreStats",
                        ),
                        ComponentSlot(
                            id="chart",
                            component_type=ComponentType.CHART,
                            data_binding="$compute.scoreStats.distribution",
                            props={"variant": "bar", "title": "Score Distribution"},
                        ),
                    ],
                )
            ],
        ),
    )


def test_blueprint_camel_case_serialization():
    bp = _make_sample_blueprint()
    data = bp.model_dump(by_alias=True)

    # Top-level camelCase keys
    assert "capabilityLevel" in data
    assert "sourcePrompt" in data
    assert "dataContract" in data
    assert "computeGraph" in data
    assert "uiComposition" in data

    # Nested camelCase
    assert "dependsOn" in data["dataContract"]["inputs"][1]
    assert data["dataContract"]["inputs"][1]["dependsOn"] == "class"

    binding = data["dataContract"]["bindings"][0]
    assert "sourceType" in binding
    assert "toolName" in binding
    assert "paramMapping" in binding

    node = data["computeGraph"]["nodes"][0]
    assert "toolName" in node
    assert "toolArgs" in node
    assert "outputKey" in node
    assert "dependsOn" in node

    slot = data["uiComposition"]["tabs"][0]["slots"][0]
    assert "componentType" in slot
    assert "dataBinding" in slot


def test_blueprint_round_trip():
    bp = _make_sample_blueprint()
    data = bp.model_dump(by_alias=True)
    bp2 = Blueprint(**data)
    assert bp2.id == bp.id
    assert bp2.data_contract.inputs[0].id == "class"
    assert bp2.compute_graph.nodes[0].tool_name == "calculate_stats"


def test_blueprint_from_camel_case_json():
    """Verify Blueprint can be constructed from camelCase input (as from frontend)."""
    camel_data = {
        "id": "bp-from-json",
        "name": "From JSON",
        "description": "Test from camelCase JSON",
        "capabilityLevel": 1,
        "dataContract": {
            "inputs": [{"id": "cls", "type": "class", "label": "Class"}],
            "bindings": [],
        },
        "computeGraph": {"nodes": []},
        "uiComposition": {
            "layout": "single_page",
            "tabs": [
                {
                    "id": "main",
                    "label": "Main",
                    "slots": [
                        {
                            "id": "md",
                            "componentType": "markdown",
                            "aiContentSlot": True,
                        }
                    ],
                }
            ],
        },
    }
    bp = Blueprint(**camel_data)
    assert bp.capability_level == CapabilityLevel.LEVEL_1
    assert bp.ui_composition.tabs[0].slots[0].ai_content_slot is True


def test_data_source_type_enum():
    assert DataSourceType.TOOL.value == "tool"
    assert DataSourceType.API.value == "api"
    assert DataSourceType.STATIC.value == "static"


def test_component_type_enum():
    assert ComponentType.KPI_GRID.value == "kpi_grid"
    assert ComponentType.CHART.value == "chart"
    assert ComponentType.TABLE.value == "table"
    assert ComponentType.MARKDOWN.value == "markdown"
    assert ComponentType.SUGGESTION_LIST.value == "suggestion_list"
    assert ComponentType.QUESTION_GENERATOR.value == "question_generator"
