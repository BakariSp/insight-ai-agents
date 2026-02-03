"""Tests for ExecutorAgent — three-phase Blueprint execution."""

from unittest.mock import AsyncMock, patch

import pytest

from agents.executor import (
    ExecutorAgent,
    _build_block,
    _build_chart_block,
    _build_kpi_block,
    _build_table_block,
    _fill_single_block,
    _get_slot_key,
    _topo_sort,
)
from errors.exceptions import DataFetchError
from models.blueprint import Blueprint
from tests.test_planner import _sample_blueprint_args


def _make_blueprint(**overrides) -> Blueprint:
    """Create a Blueprint with optional overrides."""
    args = _sample_blueprint_args()
    args.update(overrides)
    return Blueprint(**args)


# ── Shared mock tool dispatcher ──────────────────────────────


async def _mock_tool_dispatch(name, arguments):
    """Mock tool dispatcher for executor tests."""
    if name == "get_assignment_submissions":
        return {
            "assignment_id": "a-001",
            "scores": [58, 85, 72, 91, 65],
            "submissions": [
                {"student_id": "s-001", "name": "Alice", "score": 58, "submitted": True},
            ],
        }
    if name == "calculate_stats":
        return {"mean": 74.2, "median": 72, "count": 5, "max": 91, "min": 58}
    raise ValueError(f"Unexpected tool: {name}")


# ── Topological sort tests ───────────────────────────────────


class _Item:
    def __init__(self, id: str, deps: list[str] | None = None):
        self.id = id
        self.depends_on = deps or []


def test_topo_sort_no_deps():
    items = [_Item("a"), _Item("b"), _Item("c")]
    result = _topo_sort(items, lambda x: x.id, lambda x: x.depends_on)
    assert [r.id for r in result] == ["a", "b", "c"]


def test_topo_sort_with_deps():
    items = [_Item("c", ["a", "b"]), _Item("a"), _Item("b", ["a"])]
    result = _topo_sort(items, lambda x: x.id, lambda x: x.depends_on)
    ids = [r.id for r in result]
    assert ids.index("a") < ids.index("b")
    assert ids.index("b") < ids.index("c")


def test_topo_sort_circular():
    items = [_Item("a", ["b"]), _Item("b", ["a"])]
    with pytest.raises(ValueError, match="Circular dependency"):
        _topo_sort(items, lambda x: x.id, lambda x: x.depends_on)


# ── Block builder tests ─────────────────────────────────────


def test_build_kpi_block():
    data = {"mean": 74.2, "median": 72, "count": 5, "max": 91, "min": 58}
    block = _build_kpi_block(data, {})
    assert block["type"] == "kpi_grid"
    assert len(block["data"]) == 5
    labels = [item["label"] for item in block["data"]]
    assert "Average" in labels
    assert "Median" in labels
    values = {item["label"]: item["value"] for item in block["data"]}
    assert values["Average"] == "74.2"


def test_build_kpi_block_empty_data():
    block = _build_kpi_block(None, {})
    assert block["type"] == "kpi_grid"
    assert block["data"] == []


def test_build_chart_block_distribution():
    data = {
        "distribution": {
            "labels": ["0-39", "40-49", "50-59", "60-69", "70-79"],
            "counts": [0, 0, 1, 1, 2],
        }
    }
    block = _build_chart_block(data, {"variant": "bar", "title": "Distribution"})
    assert block["type"] == "chart"
    assert block["variant"] == "bar"
    assert block["xAxis"] == ["0-39", "40-49", "50-59", "60-69", "70-79"]
    assert block["series"][0]["data"] == [0, 0, 1, 1, 2]


def test_build_chart_block_direct_labels():
    data = {"labels": ["A", "B", "C"], "counts": [10, 20, 30]}
    block = _build_chart_block(data, {"variant": "pie"})
    assert block["xAxis"] == ["A", "B", "C"]
    assert block["series"][0]["data"] == [10, 20, 30]


def test_build_table_block_submissions():
    data = {
        "submissions": [
            {"name": "Alice", "score": 85, "submitted": "2025-01-01"},
            {"name": "Bob", "score": 55, "submitted": "2025-01-01"},
        ]
    }
    block = _build_table_block(data, {"title": "Scores"})
    assert block["type"] == "table"
    assert block["title"] == "Scores"
    assert block["headers"] == ["Student", "Score", "Submitted"]
    assert len(block["rows"]) == 2
    assert block["rows"][0]["status"] == "success"  # 85 >= 80
    assert block["rows"][1]["status"] == "warning"  # 55 < 60


def test_build_table_block_generic_list():
    data = [{"name": "X", "value": 1}, {"name": "Y", "value": 2}]
    block = _build_table_block(data, {})
    assert block["headers"] == ["name", "value"]
    assert len(block["rows"]) == 2


def test_build_block_dispatches():
    """_build_block routes to correct builder by component type."""
    stats = {"mean": 74.2, "count": 5}
    block = _build_block("kpi_grid", stats, {})
    assert block["type"] == "kpi_grid"

    dist = {"labels": ["A"], "counts": [1]}
    block = _build_block("chart", dist, {"variant": "bar"})
    assert block["type"] == "chart"


# ── Block-level helper tests (Phase 6.2) ─────────────────────


def test_get_slot_key_mapping():
    """_get_slot_key maps component types to correct slot keys."""
    assert _get_slot_key("markdown") == "content"
    assert _get_slot_key("suggestion_list") == "items"
    assert _get_slot_key("question_generator") == "questions"
    assert _get_slot_key("unknown_type") == "content"  # fallback


def test_fill_single_block_markdown():
    """_fill_single_block fills markdown block content."""
    block = {"type": "markdown", "content": "", "variant": "insight"}
    _fill_single_block(block, "markdown", "AI analysis text")
    assert block["content"] == "AI analysis text"


def test_fill_single_block_suggestion_list():
    """_fill_single_block fills suggestion_list items."""
    block = {"type": "suggestion_list", "title": "Recs", "items": []}
    _fill_single_block(block, "suggestion_list", "Some suggestion")
    assert len(block["items"]) == 1
    assert block["items"][0]["title"] == "AI Analysis"
    assert block["items"][0]["description"] == "Some suggestion"


def test_fill_single_block_question_generator():
    """_fill_single_block fills question_generator questions."""
    block = {"type": "question_generator", "title": "Quiz", "questions": []}
    _fill_single_block(block, "question_generator", "What is 2+2?")
    assert len(block["questions"]) == 1
    assert block["questions"][0]["question"] == "What is 2+2?"


# ── ExecutorAgent Phase A tests ──────────────────────────────


@pytest.mark.asyncio
async def test_phase_a_resolves_data():
    """Phase A fetches data via tools and populates data_context."""
    bp = _make_blueprint()
    executor = ExecutorAgent()
    data_context: dict = {}

    mock_result = {"assignment_id": "a-001", "scores": [58, 85]}

    with patch(
        "agents.executor.execute_mcp_tool",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        events = []
        async for event in executor._resolve_data_contract(
            bp, {"teacherId": "t-001", "input": {"assignment": "a-001"}}, data_context
        ):
            events.append(event)

    # Should have TOOL_CALL + TOOL_RESULT events
    assert any(e["type"] == "TOOL_CALL" for e in events)
    assert any(e["type"] == "TOOL_RESULT" for e in events)
    # data_context should be populated
    assert "submissions" in data_context
    assert data_context["submissions"]["scores"] == [58, 85]


# ── ExecutorAgent Phase B tests ──────────────────────────────


@pytest.mark.asyncio
async def test_phase_b_executes_compute_nodes():
    """Phase B executes tool compute nodes and stores results."""
    bp = _make_blueprint()
    executor = ExecutorAgent()

    data_context = {"submissions": {"scores": [58, 85, 72, 91, 65]}}
    compute_results: dict = {}

    mock_stats = {"mean": 74.2, "median": 72, "count": 5}

    with patch(
        "agents.executor.execute_mcp_tool",
        new_callable=AsyncMock,
        return_value=mock_stats,
    ):
        events = []
        async for event in executor._execute_compute_graph(
            bp, {"teacherId": "t-001"}, data_context, compute_results
        ):
            events.append(event)

    assert any(e["type"] == "TOOL_CALL" and e["tool"] == "calculate_stats" for e in events)
    assert any(e["type"] == "TOOL_RESULT" for e in events)
    assert "scoreStats" in compute_results
    assert compute_results["scoreStats"]["mean"] == 74.2


# ── ExecutorAgent Page builder tests ─────────────────────────


def test_build_page_structure():
    """_build_page produces correct page structure with meta and tabs."""
    bp = _make_blueprint()
    executor = ExecutorAgent()

    contexts = {
        "context": {},
        "input": {},
        "data": {},
        "compute": {
            "scoreStats": {"mean": 74.2, "median": 72, "count": 5, "max": 91, "min": 58}
        },
    }

    page = executor._build_page(bp, contexts)

    assert "meta" in page
    assert page["meta"]["pageTitle"] == "Test Analysis"
    assert page["layout"] == "tabs"
    assert len(page["tabs"]) == 1
    assert page["tabs"][0]["id"] == "overview"
    assert len(page["tabs"][0]["blocks"]) == 2

    # First block: kpi_grid (deterministic)
    kpi_block = page["tabs"][0]["blocks"][0]
    assert kpi_block["type"] == "kpi_grid"
    assert len(kpi_block["data"]) == 5

    # Second block: markdown (ai placeholder)
    md_block = page["tabs"][0]["blocks"][1]
    assert md_block["type"] == "markdown"
    assert md_block["content"] == ""  # placeholder


# ── ExecutorAgent full stream tests ──────────────────────────


@pytest.mark.asyncio
async def test_full_stream_with_ai():
    """Full execute_blueprint_stream with mocked tools and AI block content."""
    bp = _make_blueprint()
    executor = ExecutorAgent()

    ai_text = "The class average is 74.2."

    with patch(
        "agents.executor.execute_mcp_tool",
        side_effect=_mock_tool_dispatch,
    ), patch.object(
        ExecutorAgent,
        "_generate_block_content",
        new_callable=AsyncMock,
        return_value=ai_text,
    ):
        events = []
        async for event in executor.execute_blueprint_stream(
            bp,
            context={
                "teacherId": "t-001",
                "input": {"assignment": "a-001"},
            },
        ):
            events.append(event)

    # Check event sequence
    types = [e["type"] for e in events]
    assert types[0] == "PHASE"  # data phase
    assert "TOOL_CALL" in types
    assert "TOOL_RESULT" in types
    assert "BLOCK_START" in types
    assert "SLOT_DELTA" in types
    assert "BLOCK_COMPLETE" in types
    assert types[-1] == "COMPLETE"

    # Check COMPLETE event
    complete = events[-1]
    assert complete["message"] == "completed"
    assert complete["progress"] == 100
    page = complete["result"]["page"]
    assert page is not None
    assert page["meta"]["pageTitle"] == "Test Analysis"
    assert page["layout"] == "tabs"
    assert len(page["tabs"]) == 1
    # Markdown block should have AI content
    md_block = page["tabs"][0]["blocks"][1]
    assert md_block["type"] == "markdown"
    assert md_block["content"] == ai_text


@pytest.mark.asyncio
async def test_full_stream_error_handling():
    """Tool failure emits error COMPLETE event."""
    bp = _make_blueprint()
    executor = ExecutorAgent()

    with patch(
        "agents.executor.execute_mcp_tool",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Tool timeout"),
    ):
        events = []
        async for event in executor.execute_blueprint_stream(
            bp,
            context={"teacherId": "t-001", "input": {"assignment": "a-001"}},
        ):
            events.append(event)

    complete = events[-1]
    assert complete["type"] == "COMPLETE"
    assert complete["message"] == "error"
    assert complete["result"]["page"] is None
    assert "failed" in complete["result"]["chatResponse"].lower()


@pytest.mark.asyncio
async def test_full_stream_no_ai_slots():
    """Blueprint without ai_content_slots skips LLM call and BLOCK events."""
    bp_args = _sample_blueprint_args()
    # Remove the ai_content_slot from slots
    bp_args["ui_composition"]["tabs"][0]["slots"] = [
        {
            "id": "kpi",
            "component_type": "kpi_grid",
            "data_binding": "$compute.scoreStats",
            "props": {},
        },
    ]
    bp = Blueprint(**bp_args)
    executor = ExecutorAgent()

    with patch(
        "agents.executor.execute_mcp_tool",
        side_effect=_mock_tool_dispatch,
    ):
        events = []
        async for event in executor.execute_blueprint_stream(
            bp, context={"teacherId": "t-001", "input": {"assignment": "a-001"}},
        ):
            events.append(event)

    types = [e["type"] for e in events]
    # No BLOCK events (no AI content)
    assert "BLOCK_START" not in types
    assert "SLOT_DELTA" not in types
    assert "BLOCK_COMPLETE" not in types
    complete = events[-1]
    assert complete["type"] == "COMPLETE"
    assert complete["result"]["page"] is not None


# ── BLOCK event tests (Phase 6.2) ────────────────────────────


@pytest.mark.asyncio
async def test_stream_emits_block_start_for_ai_slots():
    """Each ai_content_slot produces a BLOCK_START event."""
    bp = _make_blueprint()
    executor = ExecutorAgent()
    ai_text = "Block AI text."

    with patch(
        "agents.executor.execute_mcp_tool",
        side_effect=_mock_tool_dispatch,
    ), patch.object(
        ExecutorAgent,
        "_generate_block_content",
        new_callable=AsyncMock,
        return_value=ai_text,
    ):
        events = []
        async for event in executor.execute_blueprint_stream(
            bp, context={"teacherId": "t-001", "input": {"assignment": "a-001"}},
        ):
            events.append(event)

    block_starts = [e for e in events if e["type"] == "BLOCK_START"]
    assert len(block_starts) == 1
    assert block_starts[0]["blockId"] == "insight"
    assert block_starts[0]["componentType"] == "markdown"


@pytest.mark.asyncio
async def test_stream_emits_slot_delta_with_content():
    """SLOT_DELTA event contains blockId, slotKey, and deltaText."""
    bp = _make_blueprint()
    executor = ExecutorAgent()
    ai_text = "Delta content here."

    with patch(
        "agents.executor.execute_mcp_tool",
        side_effect=_mock_tool_dispatch,
    ), patch.object(
        ExecutorAgent,
        "_generate_block_content",
        new_callable=AsyncMock,
        return_value=ai_text,
    ):
        events = []
        async for event in executor.execute_blueprint_stream(
            bp, context={"teacherId": "t-001", "input": {"assignment": "a-001"}},
        ):
            events.append(event)

    deltas = [e for e in events if e["type"] == "SLOT_DELTA"]
    assert len(deltas) == 1
    assert deltas[0]["blockId"] == "insight"
    assert deltas[0]["slotKey"] == "content"
    assert deltas[0]["deltaText"] == ai_text


@pytest.mark.asyncio
async def test_block_event_ordering():
    """BLOCK_START -> SLOT_DELTA -> BLOCK_COMPLETE ordering per block."""
    bp = _make_blueprint()
    executor = ExecutorAgent()

    with patch(
        "agents.executor.execute_mcp_tool",
        side_effect=_mock_tool_dispatch,
    ), patch.object(
        ExecutorAgent,
        "_generate_block_content",
        new_callable=AsyncMock,
        return_value="Ordered text.",
    ):
        events = []
        async for event in executor.execute_blueprint_stream(
            bp, context={"teacherId": "t-001", "input": {"assignment": "a-001"}},
        ):
            events.append(event)

    block_events = [
        e for e in events
        if e["type"] in ("BLOCK_START", "SLOT_DELTA", "BLOCK_COMPLETE")
    ]
    assert len(block_events) == 3
    assert block_events[0]["type"] == "BLOCK_START"
    assert block_events[1]["type"] == "SLOT_DELTA"
    assert block_events[2]["type"] == "BLOCK_COMPLETE"
    # All same blockId
    assert block_events[0]["blockId"] == block_events[1]["blockId"] == block_events[2]["blockId"]


@pytest.mark.asyncio
async def test_non_ai_slots_no_block_events():
    """Blueprints without ai_content_slots produce no BLOCK events."""
    bp_args = _sample_blueprint_args()
    bp_args["ui_composition"]["tabs"][0]["slots"] = [
        {"id": "kpi", "component_type": "kpi_grid", "data_binding": "$compute.scoreStats", "props": {}},
    ]
    bp = Blueprint(**bp_args)
    executor = ExecutorAgent()

    with patch(
        "agents.executor.execute_mcp_tool",
        side_effect=_mock_tool_dispatch,
    ):
        events = []
        async for event in executor.execute_blueprint_stream(
            bp, context={"teacherId": "t-001", "input": {"assignment": "a-001"}},
        ):
            events.append(event)

    block_types = {"BLOCK_START", "SLOT_DELTA", "BLOCK_COMPLETE"}
    assert not any(e["type"] in block_types for e in events)


# ── DATA_ERROR interception (Phase 4.5.4) ───────────────────


@pytest.mark.asyncio
async def test_required_binding_error_dict_emits_data_error():
    """Required binding returns {error: ...} -> DATA_ERROR + error COMPLETE."""
    bp = _make_blueprint()
    executor = ExecutorAgent()

    error_result = {"error": "Class class-2c not found", "teacher_id": "t-001"}

    with patch(
        "agents.executor.execute_mcp_tool",
        new_callable=AsyncMock,
        return_value=error_result,
    ):
        events = []
        async for event in executor.execute_blueprint_stream(
            bp,
            context={"teacherId": "t-001", "input": {"assignment": "a-001"}},
        ):
            events.append(event)

    types = [e["type"] for e in events]
    assert "DATA_ERROR" in types

    # DATA_ERROR event has expected shape
    data_error = next(e for e in events if e["type"] == "DATA_ERROR")
    assert data_error["entity"] == "submissions"  # binding.id
    assert "not found" in data_error["message"]
    assert isinstance(data_error["suggestions"], list)

    # COMPLETE event is error with data_error errorType
    complete = events[-1]
    assert complete["type"] == "COMPLETE"
    assert complete["message"] == "error"
    assert complete["result"]["page"] is None
    assert complete["result"]["errorType"] == "data_error"


@pytest.mark.asyncio
async def test_non_required_binding_error_dict_skips_gracefully():
    """Non-required binding returns {error: ...} -> TOOL_RESULT error, no DATA_ERROR."""
    bp_args = _sample_blueprint_args()
    # Make the binding non-required
    bp_args["data_contract"]["bindings"][0]["required"] = False
    bp = Blueprint(**bp_args)
    executor = ExecutorAgent()

    error_result = {"error": "Class not found", "teacher_id": "t-001"}
    mock_stats = {"mean": 0, "count": 0}

    async def mock_tool(name, arguments):
        if name == "get_assignment_submissions":
            return error_result
        if name == "calculate_stats":
            return mock_stats
        raise ValueError(f"Unexpected tool: {name}")

    with patch(
        "agents.executor.execute_mcp_tool",
        side_effect=mock_tool,
    ), patch.object(
        ExecutorAgent,
        "_generate_block_content",
        new_callable=AsyncMock,
        return_value="AI text",
    ):
        events = []
        async for event in executor.execute_blueprint_stream(
            bp,
            context={"teacherId": "t-001", "input": {"assignment": "a-001"}},
        ):
            events.append(event)

    types = [e["type"] for e in events]
    # No DATA_ERROR for non-required binding
    assert "DATA_ERROR" not in types
    # But TOOL_RESULT with error status
    error_results = [e for e in events if e.get("status") == "error"]
    assert len(error_results) >= 1
    # Stream completes successfully
    complete = events[-1]
    assert complete["type"] == "COMPLETE"
    assert complete["message"] == "completed"


# ── DataFetchError exception tests ──────────────────────────


def test_data_fetch_error_attributes():
    """DataFetchError carries tool_name, entity, suggestions."""
    err = DataFetchError(
        tool_name="get_class_detail",
        message="Class 2C not found",
        entity="class-2c",
        suggestions=["class-hk-f1a", "class-hk-f1b"],
    )
    assert err.tool_name == "get_class_detail"
    assert err.entity == "class-2c"
    assert err.suggestions == ["class-hk-f1a", "class-hk-f1b"]
    assert "get_class_detail" in str(err)
    assert "Class 2C not found" in str(err)


# ── Per-block AI generation tests (Phase 6.3) ────────────────


def test_parse_json_output_valid():
    """_parse_json_output parses valid JSON."""
    from agents.executor import _parse_json_output

    json_output = '[{"title": "Focus A", "description": "Do X", "priority": "high"}]'
    result = _parse_json_output(json_output)

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["title"] == "Focus A"


def test_parse_json_output_with_code_block():
    """_parse_json_output handles markdown code blocks."""
    from agents.executor import _parse_json_output

    raw = '```json\n[{"key": "value"}]\n```'
    result = _parse_json_output(raw)

    assert isinstance(result, list)
    assert result[0]["key"] == "value"


def test_parse_json_output_code_block_no_lang():
    """_parse_json_output handles code blocks without language tag."""
    from agents.executor import _parse_json_output

    raw = '```\n{"key": "value"}\n```'
    result = _parse_json_output(raw)

    assert isinstance(result, dict)
    assert result["key"] == "value"


def test_parse_json_output_fallback():
    """_parse_json_output falls back to raw string on invalid JSON."""
    from agents.executor import _parse_json_output

    raw = "This is not JSON at all"
    result = _parse_json_output(raw)

    assert result == raw


def test_fill_single_block_with_list():
    """_fill_single_block handles list input for suggestion_list."""
    block = {"type": "suggestion_list", "title": "Tips", "items": []}
    items = [
        {"title": "Tip 1", "description": "Do this", "priority": "high", "category": "action"},
        {"title": "Tip 2", "description": "Do that", "priority": "low", "category": "info"},
    ]

    _fill_single_block(block, "suggestion_list", items)

    assert len(block["items"]) == 2
    assert block["items"][0]["title"] == "Tip 1"
    assert block["items"][1]["priority"] == "low"


def test_fill_single_block_suggestion_fallback():
    """_fill_single_block wraps string as single item for suggestion_list."""
    block = {"type": "suggestion_list", "title": "Tips", "items": []}

    _fill_single_block(block, "suggestion_list", "Plain text suggestion")

    assert len(block["items"]) == 1
    assert block["items"][0]["description"] == "Plain text suggestion"


def test_fill_single_block_question_generator_list():
    """_fill_single_block handles list input for question_generator."""
    block = {"type": "question_generator", "title": "Quiz", "questions": []}
    questions = [
        {"id": "q1", "type": "multiple_choice", "question": "What is 2+2?", "answer": "4"},
    ]

    _fill_single_block(block, "question_generator", questions)

    assert len(block["questions"]) == 1
    assert block["questions"][0]["question"] == "What is 2+2?"


def test_fill_single_block_question_fallback():
    """_fill_single_block wraps string as single question for question_generator."""
    block = {"type": "question_generator", "title": "Quiz", "questions": []}

    _fill_single_block(block, "question_generator", "What is the capital?")

    assert len(block["questions"]) == 1
    assert block["questions"][0]["question"] == "What is the capital?"


@pytest.mark.asyncio
async def test_each_ai_slot_uses_per_block_prompt():
    """Each ai_content_slot triggers _generate_block_content call."""
    bp = _make_blueprint()
    executor = ExecutorAgent()

    call_count = 0

    async def mock_generate(slot, blueprint, data_ctx, compute_res):
        nonlocal call_count
        call_count += 1
        return f"Content for {slot.id}"

    with patch(
        "agents.executor.execute_mcp_tool",
        side_effect=_mock_tool_dispatch,
    ), patch.object(
        ExecutorAgent,
        "_generate_block_content",
        side_effect=mock_generate,
    ):
        events = []
        async for event in executor.execute_blueprint_stream(
            bp, context={"teacherId": "t-001", "input": {"assignment": "a-001"}},
        ):
            events.append(event)

    # One AI slot in sample blueprint = one call
    assert call_count == 1

    # SLOT_DELTA contains the generated content
    deltas = [e for e in events if e["type"] == "SLOT_DELTA"]
    assert len(deltas) == 1
    assert "Content for insight" in deltas[0]["deltaText"]


@pytest.mark.asyncio
async def test_slot_delta_serializes_list_as_json():
    """SLOT_DELTA converts list/dict content to JSON string."""
    bp = _make_blueprint()
    executor = ExecutorAgent()

    # Return a list to simulate JSON output from suggestion_list
    mock_list = [{"title": "Test", "priority": "high"}]

    with patch(
        "agents.executor.execute_mcp_tool",
        side_effect=_mock_tool_dispatch,
    ), patch.object(
        ExecutorAgent,
        "_generate_block_content",
        new_callable=AsyncMock,
        return_value=mock_list,
    ):
        events = []
        async for event in executor.execute_blueprint_stream(
            bp, context={"teacherId": "t-001", "input": {"assignment": "a-001"}},
        ):
            events.append(event)

    deltas = [e for e in events if e["type"] == "SLOT_DELTA"]
    assert len(deltas) == 1
    # Should be JSON string, not Python repr
    assert '"title"' in deltas[0]["deltaText"]
    assert '"Test"' in deltas[0]["deltaText"]
