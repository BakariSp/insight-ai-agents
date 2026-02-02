"""SSE event payload models for block-granular streaming (Phase 6).

Provides typed models for the three new SSE event types that enable
per-block content streaming:

- BLOCK_START:    Notify frontend that a block is being filled.
- SLOT_DELTA:     Push incremental text to a specific block + slot.
- BLOCK_COMPLETE: Notify frontend that a block is done.
"""

from __future__ import annotations

from models.base import CamelModel


class BlockStartEvent(CamelModel):
    """Emitted when the Executor begins filling an AI content block."""

    type: str = "BLOCK_START"
    block_id: str
    component_type: str


class SlotDeltaEvent(CamelModel):
    """Emitted to push content into a specific slot within a block."""

    type: str = "SLOT_DELTA"
    block_id: str
    slot_key: str
    delta_text: str


class BlockCompleteEvent(CamelModel):
    """Emitted when a block's content has been fully generated."""

    type: str = "BLOCK_COMPLETE"
    block_id: str
