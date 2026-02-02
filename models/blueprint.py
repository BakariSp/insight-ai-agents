"""Blueprint — the three-layer executable plan for structured page generation.

Layer A: DataContract  — what data is needed and how to get it
Layer B: ComputeGraph  — deterministic tool calcs + AI narrative nodes
Layer C: UIComposition — registered components + layout specification
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from models.base import CamelModel


# ── Layer A: Data Contract ──────────────────────────────────


class DataSourceType(str, Enum):
    TOOL = "tool"
    API = "api"
    STATIC = "static"


class DataInputSpec(CamelModel):
    """User-visible data selection item (class, assignment, etc.)."""

    id: str
    type: str
    label: str
    required: bool = True
    depends_on: str | None = None


class DataBinding(CamelModel):
    """Single data requirement: what to get and how to get it."""

    id: str
    source_type: DataSourceType = DataSourceType.TOOL
    tool_name: str | None = None
    api_path: str | None = None
    param_mapping: dict[str, str] = Field(default_factory=dict)
    description: str = ""
    required: bool = True
    depends_on: list[str] = Field(default_factory=list)


class DataContract(CamelModel):
    """Layer A: declares all data the Blueprint needs."""

    inputs: list[DataInputSpec]
    bindings: list[DataBinding]


# ── Layer B: Compute Graph ──────────────────────────────────


class ComputeNodeType(str, Enum):
    TOOL = "tool"
    AI = "ai"


class ComputeNode(CamelModel):
    """A single node in the compute graph."""

    id: str
    type: ComputeNodeType
    # TOOL node fields
    tool_name: str | None = None
    tool_args: dict | None = None
    # AI node fields
    prompt_template: str | None = None
    # Common
    depends_on: list[str] = Field(default_factory=list)
    output_key: str = ""


class ComputeGraph(CamelModel):
    """Layer B: defines compute steps and execution order."""

    nodes: list[ComputeNode]


# ── Layer C: UI Composition ─────────────────────────────────


class ComponentType(str, Enum):
    KPI_GRID = "kpi_grid"
    CHART = "chart"
    TABLE = "table"
    MARKDOWN = "markdown"
    SUGGESTION_LIST = "suggestion_list"
    QUESTION_GENERATOR = "question_generator"


class ComponentSlot(CamelModel):
    """A component position in the layout."""

    id: str
    component_type: ComponentType
    data_binding: str | None = None
    props: dict = Field(default_factory=dict)
    ai_content_slot: bool = False


class TabSpec(CamelModel):
    id: str
    label: str
    slots: list[ComponentSlot]


class UIComposition(CamelModel):
    """Layer C: declares how to compose the UI from registered components."""

    layout: str = "tabs"
    tabs: list[TabSpec]


# ── Blueprint (top-level) ──────────────────────────────────


class CapabilityLevel(int, Enum):
    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3


class Blueprint(CamelModel):
    """Executable blueprint — the complete execution plan for a page."""

    # Metadata
    id: str
    name: str
    description: str
    icon: str = "chart"
    category: str = "analytics"
    version: int = 1
    capability_level: CapabilityLevel = CapabilityLevel.LEVEL_1
    source_prompt: str = ""
    created_at: str = ""

    # Three layers
    data_contract: DataContract
    compute_graph: ComputeGraph
    ui_composition: UIComposition

    # ExecutorAgent context
    page_system_prompt: str = ""
