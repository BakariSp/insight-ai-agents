"""PatchAgent — analyzes refine requests and generates PatchPlans.

Determines the minimal set of changes needed to satisfy a refine request,
avoiding full Blueprint regeneration when possible.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from models.blueprint import Blueprint
from models.patch import (
    PatchInstruction,
    PatchPlan,
    PatchType,
    RefineScope,
)

logger = logging.getLogger(__name__)


async def analyze_refine(
    message: str,
    blueprint: Blueprint,
    page: dict[str, Any] | None,
    refine_scope: str | None,
) -> PatchPlan:
    """Analyze a refine request and generate a PatchPlan.

    Args:
        message: The user's refine request.
        blueprint: The current Blueprint.
        page: The current page structure (if available).
        refine_scope: The scope from RouterAgent ("patch_layout", "patch_compose", etc.)

    Returns:
        A PatchPlan with instructions for modifying the page.
    """
    scope = RefineScope(refine_scope) if refine_scope else RefineScope.FULL_REBUILD

    if scope == RefineScope.FULL_REBUILD:
        # No patch needed — caller should use PlannerAgent
        return PatchPlan(scope=scope)

    if scope == RefineScope.PATCH_LAYOUT:
        return _analyze_layout_patch(message, blueprint, page)

    if scope == RefineScope.PATCH_COMPOSE:
        return _analyze_compose_patch(message, blueprint, page)

    return PatchPlan(scope=RefineScope.FULL_REBUILD)


def _analyze_layout_patch(
    message: str,
    blueprint: Blueprint,
    page: dict[str, Any] | None,
) -> PatchPlan:
    """Analyze layout-only changes (no AI regeneration needed)."""
    instructions: list[PatchInstruction] = []
    affected_ids: list[str] = []

    # Color change detection
    color_match = re.search(
        r"(?:颜色|color|colour).*?(?:换成|改成|变成|change to|to)\s*(\w+)",
        message,
        re.IGNORECASE,
    )
    if color_match:
        new_color = color_match.group(1)
        # Apply to all chart blocks
        for tab in blueprint.ui_composition.tabs:
            for slot in tab.slots:
                if slot.component_type.value == "chart":
                    instructions.append(
                        PatchInstruction(
                            type=PatchType.UPDATE_PROPS,
                            target_block_id=slot.id,
                            changes={"color": new_color},
                        )
                    )
                    affected_ids.append(slot.id)

    # Title change detection
    title_match = re.search(
        r"(?:标题|title).*?(?:换成|改成|改为|change to)\s*[\"']?([^\"']+)[\"']?",
        message,
        re.IGNORECASE,
    )
    if title_match:
        new_title = title_match.group(1).strip()
        # Apply to first block or all blocks with titles
        for tab in blueprint.ui_composition.tabs:
            for slot in tab.slots:
                if slot.props.get("title"):
                    instructions.append(
                        PatchInstruction(
                            type=PatchType.UPDATE_PROPS,
                            target_block_id=slot.id,
                            changes={"title": new_title},
                        )
                    )
                    affected_ids.append(slot.id)
                    break  # Only first match

    return PatchPlan(
        scope=RefineScope.PATCH_LAYOUT,
        instructions=instructions,
        affected_block_ids=list(set(affected_ids)),
    )


def _analyze_compose_patch(
    message: str,
    blueprint: Blueprint,
    page: dict[str, Any] | None,
) -> PatchPlan:
    """Analyze content changes that need AI regeneration."""
    instructions: list[PatchInstruction] = []
    affected_ids: list[str] = []

    # Find all ai_content_slot blocks
    for tab in blueprint.ui_composition.tabs:
        for slot in tab.slots:
            if slot.ai_content_slot:
                instructions.append(
                    PatchInstruction(
                        type=PatchType.RECOMPOSE,
                        target_block_id=slot.id,
                        changes={"instruction": message},
                    )
                )
                affected_ids.append(slot.id)

    return PatchPlan(
        scope=RefineScope.PATCH_COMPOSE,
        instructions=instructions,
        affected_block_ids=affected_ids,
        compose_instruction=message,
    )
