# Plan: Executor Phase C 重构 — 逐 Block 事件流 (Step 6.2)

**Goal:** Refactor Executor Phase C from single AI narrative generation to per-block streaming with BLOCK_START/SLOT_DELTA/BLOCK_COMPLETE SSE events.
**Architecture:** `ExecutorAgent.execute_blueprint_stream()` Phase C currently calls `_generate_ai_narrative()` once for all AI slots, then fills blocks via `_fill_ai_content()`. After this change, Phase C iterates each `ai_content_slot`, emits typed BLOCK events per slot, and fills each block independently via `_generate_block_content()` + `_fill_single_block()`.
**Tech Stack:** Python 3.9+, PydanticAI, pytest, AsyncGenerator
**Date:** 2026-02-03

---

## 1. Context and Constraints

### Current State

- `agents/executor.py` Phase C flow:
  1. `_build_page()` → deterministic blocks + AI placeholders
  2. `_generate_ai_narrative()` → single LLM call → one `ai_text` string
  3. `_fill_ai_content()` → fills all AI slots with the same `ai_text`
  4. Yields one `MESSAGE` event, then `COMPLETE`

- `models/sse_events.py` — `BlockStartEvent`, `SlotDeltaEvent`, `BlockCompleteEvent` already defined (Step 6.1)

- Sample blueprint fixture (`_sample_blueprint_args()`) has 1 AI slot: `insight` (markdown, `ai_content_slot=True`)

- 243 tests currently passing

### Constraints

- **No backward compatibility needed** — code not yet deployed (roadmap note)
- **Remove MESSAGE event** in Phase C — replaced by BLOCK events
- **Keep `_generate_ai_narrative()` and `_fill_ai_content()`** as dead code — 6.3 removes them
- **COMPLETE event** must still carry `chatResponse` (concatenation of all block AI texts)
- **Existing Phase A/B logic untouched**
- **SSE event keys use camelCase** (`blockId`, `componentType`, `slotKey`, `deltaText`) matching `sse-protocol.md`

### Risks

- Tests mocking `_generate_ai_narrative` will break → must update to mock `_generate_block_content`
- E2E tests checking for `MESSAGE` event type will break → must update assertions

---

## 2. Task Breakdown

### Task 1: Add `_get_slot_key()` helper + test

**Description:** Add module-level helper that maps `component_type` → SSE slot key name.

**Files:** `agents/executor.py`, `tests/test_executor.py`

**Test (Red):**

```python
# tests/test_executor.py — add import
from agents.executor import _get_slot_key

def test_get_slot_key_mapping():
    """_get_slot_key maps component types to correct slot keys."""
    assert _get_slot_key("markdown") == "content"
    assert _get_slot_key("suggestion_list") == "items"
    assert _get_slot_key("question_generator") == "questions"
    assert _get_slot_key("unknown_type") == "content"  # fallback
```

**Implementation:**

```python
# agents/executor.py — add after block builder functions

def _get_slot_key(component_type: str) -> str:
    """Map component_type to the slot key used in SLOT_DELTA events."""
    return {"markdown": "content", "suggestion_list": "items", "question_generator": "questions"}.get(component_type, "content")
```

**Verification:** `pytest tests/test_executor.py::test_get_slot_key_mapping -v`

---

### Task 2: Add `_fill_single_block()` static method + test

**Description:** Extract single-block fill logic from `_fill_ai_content()` into a standalone static method.

**Files:** `agents/executor.py`, `tests/test_executor.py`

**Test (Red):**

```python
# tests/test_executor.py — add import
from agents.executor import _fill_single_block

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
```

**Implementation:**

```python
# agents/executor.py — add as module-level function after _build_ai_placeholder

def _fill_single_block(block: dict[str, Any], component_type: str, ai_text: str) -> None:
    """Fill a single AI content block with generated text."""
    if component_type == "markdown":
        block["content"] = ai_text
    elif component_type == "suggestion_list":
        block["items"] = [
            {"title": "AI Analysis", "description": ai_text, "priority": "medium", "category": "insight"}
        ]
    elif component_type == "question_generator":
        block["questions"] = [
            {"id": "q1", "type": "short_answer", "question": ai_text, "answer": ""}
        ]
```

**Verification:** `pytest tests/test_executor.py::test_fill_single_block_markdown tests/test_executor.py::test_fill_single_block_suggestion_list tests/test_executor.py::test_fill_single_block_question_generator -v`

---

### Task 3: Add `_generate_block_content()` method + `_stream_ai_content()` generator

**Description:** Add the per-block AI generation entry point and the async generator that yields BLOCK_START/SLOT_DELTA/BLOCK_COMPLETE events for each AI slot.

**Files:** `agents/executor.py`

**Implementation:**

```python
# In ExecutorAgent class — new methods

async def _generate_block_content(
    self,
    slot: "ComponentSlot",
    blueprint: Blueprint,
    data_context: dict[str, Any],
    compute_results: dict[str, Any],
) -> str:
    """Generate AI content for a single block.

    In Phase 6.2 this uses the same compose prompt for all blocks.
    Phase 6.3 upgrades to per-block prompts via build_block_prompt().
    """
    prompt = build_compose_prompt(blueprint, data_context, compute_results)

    agent = Agent(
        model=self.model,
        system_prompt=blueprint.page_system_prompt
        or "You are an educational data analyst.",
        defer_model_check=True,
    )

    result = await agent.run(prompt)
    return str(result.output)

async def _stream_ai_content(
    self,
    page: dict[str, Any],
    blueprint: Blueprint,
    data_context: dict[str, Any],
    compute_results: dict[str, Any],
) -> AsyncGenerator[dict[str, Any], None]:
    """Yield BLOCK_START/SLOT_DELTA/BLOCK_COMPLETE events for each AI content slot."""
    for tab_spec, tab_data in zip(
        blueprint.ui_composition.tabs, page["tabs"]
    ):
        for slot, block in zip(tab_spec.slots, tab_data["blocks"]):
            if not slot.ai_content_slot:
                continue

            component = slot.component_type.value
            block_id = slot.id
            slot_key = _get_slot_key(component)

            yield {
                "type": "BLOCK_START",
                "blockId": block_id,
                "componentType": component,
            }

            ai_text = await self._generate_block_content(
                slot, blueprint, data_context, compute_results
            )

            yield {
                "type": "SLOT_DELTA",
                "blockId": block_id,
                "slotKey": slot_key,
                "deltaText": ai_text,
            }

            _fill_single_block(block, component, ai_text)

            yield {
                "type": "BLOCK_COMPLETE",
                "blockId": block_id,
            }
```

**Verification:** Compile check — no runtime test yet; the next task wires it in and tests the full flow.

---

### Task 4: Refactor Phase C in `execute_blueprint_stream()` + add new executor tests

**Description:** Replace the old Phase C logic (single `_generate_ai_narrative` + `_fill_ai_content` + `MESSAGE` event) with `_stream_ai_content()`. Add 4 new tests for BLOCK event behavior.

**Files:** `agents/executor.py`, `tests/test_executor.py`

**Implementation — executor.py Phase C replacement:**

Replace the Phase C section in `execute_blueprint_stream()` (lines 79-121) with:

```python
            # ── Phase C: AI Compose ──
            yield {
                "type": "PHASE",
                "phase": "compose",
                "message": "Composing page...",
            }

            all_contexts = {
                "context": ctx,
                "input": ctx.get("input", {}),
                "data": data_context,
                "compute": compute_results,
            }

            # Build deterministic page structure
            page = self._build_page(blueprint, all_contexts)

            # Stream AI content for ai_content_slots with BLOCK events
            all_ai_texts: list[str] = []
            async for event in self._stream_ai_content(
                page, blueprint, data_context, compute_results
            ):
                yield event
                if event.get("type") == "SLOT_DELTA":
                    all_ai_texts.append(event.get("deltaText", ""))

            combined_ai_text = "\n\n".join(all_ai_texts) if all_ai_texts else ""

            # Complete
            yield {
                "type": "COMPLETE",
                "message": "completed",
                "progress": 100,
                "result": {
                    "response": combined_ai_text,
                    "chatResponse": combined_ai_text,
                    "page": page,
                },
            }
```

**New tests (tests/test_executor.py):**

```python
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
    """BLOCK_START → SLOT_DELTA → BLOCK_COMPLETE ordering per block."""
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

    block_events = [e for e in events if e["type"] in ("BLOCK_START", "SLOT_DELTA", "BLOCK_COMPLETE")]
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
```

**Shared test helper (add near top of test_executor.py):**

```python
# Shared mock tool dispatcher for BLOCK event tests
async def _mock_tool_dispatch(name, arguments):
    if name == "get_assignment_submissions":
        return {"assignment_id": "a-001", "scores": [58, 85, 72, 91, 65]}
    if name == "calculate_stats":
        return {"mean": 74.2, "median": 72, "count": 5, "max": 91, "min": 58}
    raise ValueError(f"Unexpected tool: {name}")
```

**Verification:** `pytest tests/test_executor.py -v`

---

### Task 5: Update existing executor tests for new Phase C flow

**Description:** Update `test_full_stream_with_ai`, `test_full_stream_no_ai_slots`, `test_non_required_binding_error_dict_skips_gracefully` to mock `_generate_block_content` instead of `_generate_ai_narrative` and check for BLOCK events instead of MESSAGE.

**Files:** `tests/test_executor.py`

**Changes:**

1. `test_full_stream_with_ai`: mock `_generate_block_content` → check BLOCK_START/SLOT_DELTA/BLOCK_COMPLETE, no MESSAGE
2. `test_full_stream_no_ai_slots`: no changes needed (already checks no MESSAGE, now also no BLOCK events)
3. `test_non_required_binding_error_dict_skips_gracefully`: mock `_generate_block_content` instead of `_generate_ai_narrative`

**Verification:** `pytest tests/test_executor.py -v`

---

### Task 6: Update E2E tests for new BLOCK events

**Description:** Update all E2E tests in `test_e2e_page.py` to mock `_generate_block_content` instead of `_generate_ai_narrative`, and update assertions for BLOCK events replacing MESSAGE events.

**Files:** `tests/test_e2e_page.py`

**Changes to each test:**

1. `test_e2e_executor_with_real_tools`: mock `_generate_block_content`, check BLOCK events instead of MESSAGE
2. `test_e2e_page_content_from_real_tools`: mock `_generate_block_content`, page assertions unchanged
3. `test_e2e_sse_event_format`: add BLOCK_START/SLOT_DELTA/BLOCK_COMPLETE format validation, remove MESSAGE check
4. `test_e2e_http_sse_stream`: mock `_generate_block_content`, check BLOCK events
5. `test_e2e_java_backend_500_falls_back_to_mock`: mock `_generate_block_content`
6. `test_e2e_java_timeout_falls_back_to_mock`: mock `_generate_block_content`

**Verification:** `pytest tests/test_e2e_page.py -v`

---

### Task 7: Full test suite verification + SSE protocol doc update

**Description:** Run the full test suite to verify all 243+ tests pass. Update `docs/api/sse-protocol.md` to remove the backward-compat MESSAGE note.

**Verification:** `pytest tests/ -v`

---

## 3. Dependency Order

```
Task 1 (helper)  ─┐
Task 2 (fill)     ─┤
                   ├── Task 3 (generator methods) ── Task 4 (wire + new tests) ── Task 5 (update old tests) ── Task 6 (update E2E) ── Task 7 (verify all)
```

Tasks 1 and 2 are independent of each other and can run in parallel.
Tasks 3-7 are sequential.

---

## 4. Commit Strategy

| After Task | Commit Message |
|-----------|----------------|
| 1+2+3+4 | `feat(phase6.2): add per-block BLOCK_START/SLOT_DELTA/BLOCK_COMPLETE event stream` |
| 5+6 | `test(phase6.2): update executor and E2E tests for block event flow` |
| 7 | `docs(phase6.2): update SSE protocol and roadmap for block events` |
