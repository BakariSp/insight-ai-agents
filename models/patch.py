"""Patch models — incremental page modification support.

Defines the data contracts for Phase 6.4's Patch mechanism:
- PatchType: what kind of modification (update_props, reorder, add_block, etc.)
- RefineScope: how much of the page needs changing (patch_layout, patch_compose, full_rebuild)
- PatchInstruction: a single patch operation
- PatchPlan: collection of patches to apply
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from models.base import CamelModel


class PatchType(str, Enum):
    """Types of patch operations."""

    UPDATE_PROPS = "update_props"  # Change block properties (color, title, etc.)
    REORDER = "reorder"  # Change block order within a tab
    ADD_BLOCK = "add_block"  # Add a new block
    REMOVE_BLOCK = "remove_block"  # Remove an existing block
    RECOMPOSE = "recompose"  # Regenerate AI content for a block


class RefineScope(str, Enum):
    """Scope of refinement — determines execution path."""

    PATCH_LAYOUT = "patch_layout"  # UI-only changes, no LLM needed
    PATCH_COMPOSE = "patch_compose"  # Re-generate AI content for affected blocks
    FULL_REBUILD = "full_rebuild"  # Regenerate entire Blueprint


class PatchInstruction(CamelModel):
    """A single patch operation to apply to the page."""

    type: PatchType
    target_block_id: str
    changes: dict = Field(default_factory=dict)
    # For ADD_BLOCK: changes contains the new block spec
    # For UPDATE_PROPS: changes contains {prop_key: new_value}
    # For REORDER: changes contains {new_index: int}
    # For RECOMPOSE: changes may contain {instruction: "..."} for AI guidance


class PatchPlan(CamelModel):
    """A plan for incremental page modification."""

    scope: RefineScope
    instructions: list[PatchInstruction] = Field(default_factory=list)
    affected_block_ids: list[str] = Field(default_factory=list)
    # Additional context for PATCH_COMPOSE
    compose_instruction: str | None = None
