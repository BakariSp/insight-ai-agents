"""Tests for SSE block/slot event models — camelCase serialization."""

from models.sse_events import BlockCompleteEvent, BlockStartEvent, SlotDeltaEvent


def test_block_start_camel_case():
    """BlockStartEvent serializes to camelCase keys."""
    event = BlockStartEvent(block_id="tab1-md", component_type="markdown")
    data = event.model_dump(by_alias=True)

    assert data == {
        "type": "BLOCK_START",
        "blockId": "tab1-md",
        "componentType": "markdown",
    }


def test_slot_delta_camel_case():
    """SlotDeltaEvent serializes to camelCase keys."""
    event = SlotDeltaEvent(
        block_id="tab1-md",
        slot_key="content",
        delta_text="Key findings: average score is 74.2.",
    )
    data = event.model_dump(by_alias=True)

    assert data == {
        "type": "SLOT_DELTA",
        "blockId": "tab1-md",
        "slotKey": "content",
        "deltaText": "Key findings: average score is 74.2.",
    }


def test_block_complete_camel_case():
    """BlockCompleteEvent serializes to camelCase keys."""
    event = BlockCompleteEvent(block_id="tab1-md")
    data = event.model_dump(by_alias=True)

    assert data == {
        "type": "BLOCK_COMPLETE",
        "blockId": "tab1-md",
    }


def test_slot_delta_empty_text():
    """SlotDeltaEvent accepts empty delta text."""
    event = SlotDeltaEvent(block_id="b1", slot_key="content", delta_text="")
    data = event.model_dump(by_alias=True)
    assert data["deltaText"] == ""


def test_block_start_suggestion_list():
    """BlockStartEvent works with suggestion_list component type."""
    event = BlockStartEvent(block_id="tab1-suggest", component_type="suggestion_list")
    data = event.model_dump(by_alias=True)
    assert data["componentType"] == "suggestion_list"
