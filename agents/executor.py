"""ExecutorAgent — executes a Blueprint through three phases to build a page.

Phase A (Data):    Resolve DataContract bindings, fetch data via tools.
Phase B (Compute): Execute ComputeGraph tool nodes for deterministic analytics.
Phase C (Compose): Build page structure + AI narrative for content slots.

Yields SSE-compatible event dicts throughout execution.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncGenerator

from pydantic_ai import Agent

if TYPE_CHECKING:
    from models.patch import PatchPlan

from agents.provider import create_model, execute_mcp_tool
from agents.resolver import resolve_ref, resolve_refs
from config.prompts.block_compose import build_block_prompt
from config.settings import get_settings
from errors.exceptions import DataFetchError
from models.blueprint import (
    Blueprint,
    ComponentSlot,
    ComputeNode,
    ComputeNodeType,
    DataBinding,
    DataSourceType,
)

logger = logging.getLogger(__name__)


class ExecutorAgent:
    """Executes a Blueprint and streams SSE events."""

    def __init__(self) -> None:
        settings = get_settings()
        self.model = create_model(settings.executor_model)

    async def execute_blueprint_stream(
        self,
        blueprint: Blueprint,
        context: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute a Blueprint through three phases, yielding SSE events.

        Args:
            blueprint: The Blueprint to execute.
            context: Runtime context (e.g. ``{"teacherId": "t-001"}``).

        Yields:
            SSE event dicts with ``type`` key (PHASE, TOOL_CALL, TOOL_RESULT,
            MESSAGE, COMPLETE, ERROR).
        """
        ctx = context or {}

        try:
            # ── Phase A: Resolve Data Contract ──
            yield {"type": "PHASE", "phase": "data", "message": "Fetching data..."}
            data_context: dict[str, Any] = {}
            async for event in self._resolve_data_contract(
                blueprint, ctx, data_context
            ):
                yield event

            # ── Phase B: Execute Compute Graph ──
            yield {
                "type": "PHASE",
                "phase": "compute",
                "message": "Computing analytics...",
            }
            compute_results: dict[str, Any] = {}
            async for event in self._execute_compute_graph(
                blueprint, ctx, data_context, compute_results
            ):
                yield event

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

            # Stream AI content with BLOCK_START/SLOT_DELTA/BLOCK_COMPLETE
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

        except DataFetchError as exc:
            logger.warning("Data fetch error: %s", exc)
            yield {
                "type": "COMPLETE",
                "message": "error",
                "progress": 100,
                "result": {
                    "response": "",
                    "chatResponse": str(exc),
                    "page": None,
                    "errorType": "data_error",
                    "entity": exc.entity,
                    "suggestions": exc.suggestions,
                },
            }
        except Exception as exc:
            logger.exception("Blueprint execution failed")
            yield {
                "type": "COMPLETE",
                "message": "error",
                "progress": 100,
                "result": {
                    "response": "",
                    "chatResponse": f"Page generation failed: {exc}",
                    "page": None,
                },
            }

    # ── Phase A: Data Contract ───────────────────────────────

    async def _resolve_data_contract(
        self,
        blueprint: Blueprint,
        context: dict[str, Any],
        data_context: dict[str, Any],
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Resolve data bindings in dependency order."""
        all_contexts = {
            "context": context,
            "input": context.get("input", {}),
            "data": data_context,
        }

        sorted_bindings = _topo_sort(
            blueprint.data_contract.bindings,
            get_id=lambda b: b.id,
            get_deps=lambda b: b.depends_on,
        )

        for binding in sorted_bindings:
            if binding.source_type != DataSourceType.TOOL or not binding.tool_name:
                continue

            resolved_params = resolve_refs(binding.param_mapping, all_contexts)
            yield {
                "type": "TOOL_CALL",
                "tool": binding.tool_name,
                "args": resolved_params,
            }

            try:
                result = await execute_mcp_tool(binding.tool_name, resolved_params)

                # Check for error dicts returned by tools (e.g. entity not found)
                if isinstance(result, dict) and "error" in result:
                    error_msg = result["error"]
                    logger.warning(
                        "Tool %s returned error: %s", binding.tool_name, error_msg
                    )
                    if binding.required:
                        yield {
                            "type": "DATA_ERROR",
                            "entity": binding.id,
                            "message": error_msg,
                            "suggestions": [],
                        }
                        raise DataFetchError(
                            tool_name=binding.tool_name,
                            message=error_msg,
                            entity=binding.id,
                        )
                    # Non-required binding — log and skip
                    yield {
                        "type": "TOOL_RESULT",
                        "tool": binding.tool_name,
                        "status": "error",
                        "error": error_msg,
                    }
                    continue

                data_context[binding.id] = result
                yield {
                    "type": "TOOL_RESULT",
                    "tool": binding.tool_name,
                    "status": "success",
                }
            except DataFetchError:
                raise  # Re-raise without wrapping
            except Exception as exc:
                logger.warning(
                    "Tool %s failed: %s", binding.tool_name, exc
                )
                yield {
                    "type": "TOOL_RESULT",
                    "tool": binding.tool_name,
                    "status": "error",
                    "error": str(exc),
                }
                if binding.required:
                    raise

    # ── Phase B: Compute Graph ───────────────────────────────

    async def _execute_compute_graph(
        self,
        blueprint: Blueprint,
        context: dict[str, Any],
        data_context: dict[str, Any],
        compute_results: dict[str, Any],
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute TOOL compute nodes in dependency order."""
        all_contexts = {
            "context": context,
            "input": context.get("input", {}),
            "data": data_context,
            "compute": compute_results,
        }

        tool_nodes = [
            n
            for n in blueprint.compute_graph.nodes
            if n.type == ComputeNodeType.TOOL
        ]
        sorted_nodes = _topo_sort(
            tool_nodes,
            get_id=lambda n: n.id,
            get_deps=lambda n: n.depends_on,
        )

        for node in sorted_nodes:
            if not node.tool_name:
                continue

            resolved_args = resolve_refs(node.tool_args or {}, all_contexts)
            yield {
                "type": "TOOL_CALL",
                "tool": node.tool_name,
                "args": resolved_args,
            }

            try:
                result = await execute_mcp_tool(node.tool_name, resolved_args)
                compute_results[node.output_key] = result
                yield {
                    "type": "TOOL_RESULT",
                    "tool": node.tool_name,
                    "status": "success",
                    "result": result,
                }
            except Exception as exc:
                logger.warning("Compute node %s failed: %s", node.id, exc)
                yield {
                    "type": "TOOL_RESULT",
                    "tool": node.tool_name,
                    "status": "error",
                    "error": str(exc),
                }
                raise

    # ── Phase C: Compose ─────────────────────────────────────

    def _build_page(
        self,
        blueprint: Blueprint,
        contexts: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the page JSON structure from Blueprint + resolved data."""
        tabs: list[dict[str, Any]] = []

        for tab in blueprint.ui_composition.tabs:
            blocks: list[dict[str, Any]] = []
            for slot in tab.slots:
                if slot.ai_content_slot:
                    # Placeholder — filled later by _fill_ai_content
                    blocks.append(
                        _build_ai_placeholder(slot.component_type.value, slot.props)
                    )
                else:
                    resolved_data = None
                    if slot.data_binding:
                        resolved_data = resolve_ref(slot.data_binding, contexts)
                    blocks.append(
                        _build_block(
                            slot.component_type.value, resolved_data, slot.props
                        )
                    )
            tabs.append({"id": tab.id, "label": tab.label, "blocks": blocks})

        return {
            "meta": {
                "pageTitle": blueprint.name,
                "summary": blueprint.description,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "dataSource": "tool",
            },
            "layout": blueprint.ui_composition.layout,
            "tabs": tabs,
        }

    async def _generate_ai_narrative(
        self,
        blueprint: Blueprint,
        data_context: dict[str, Any],
        compute_results: dict[str, Any],
    ) -> str:
        """Generate AI narrative text for ai_content_slots."""
        prompt = build_compose_prompt(blueprint, data_context, compute_results)

        agent = Agent(
            model=self.model,
            system_prompt=blueprint.page_system_prompt
            or "You are an educational data analyst.",
            defer_model_check=True,
        )

        result = await agent.run(prompt)
        return str(result.output)

    @staticmethod
    def _fill_ai_content(
        page: dict[str, Any],
        blueprint: Blueprint,
        ai_text: str,
    ) -> None:
        """Fill AI-generated text into ai_content_slot blocks in the page."""
        for tab_spec, tab_data in zip(
            blueprint.ui_composition.tabs, page["tabs"]
        ):
            for slot, block in zip(tab_spec.slots, tab_data["blocks"]):
                if not slot.ai_content_slot:
                    continue
                component = slot.component_type.value
                if component == "markdown":
                    block["content"] = ai_text
                elif component == "suggestion_list":
                    block["items"] = [
                        {
                            "title": "AI Analysis",
                            "description": ai_text,
                            "priority": "medium",
                            "category": "insight",
                        }
                    ]

    # ── Phase C: Per-block streaming (Phase 6.3) ─────────────

    async def _generate_block_content(
        self,
        slot: ComponentSlot,
        blueprint: Blueprint,
        data_context: dict[str, Any],
        compute_results: dict[str, Any],
    ) -> str | list | dict:
        """Generate AI content for a single block using per-block prompt.

        Returns:
            For markdown: str (the narrative text)
            For suggestion_list/question_generator: parsed JSON (list/dict)
            Falls back to str if JSON parsing fails.
        """
        prompt, output_format = build_block_prompt(
            slot, blueprint, data_context, compute_results
        )

        agent = Agent(
            model=self.model,
            system_prompt=blueprint.page_system_prompt
            or "You are an educational data analyst.",
            defer_model_check=True,
        )

        result = await agent.run(prompt)
        raw_output = str(result.output)

        if output_format == "json":
            return _parse_json_output(raw_output)

        return raw_output

    async def _stream_ai_content(
        self,
        page: dict[str, Any],
        blueprint: Blueprint,
        data_context: dict[str, Any],
        compute_results: dict[str, Any],
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield BLOCK_START/SLOT_DELTA/BLOCK_COMPLETE events per AI slot."""
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

                ai_content = await self._generate_block_content(
                    slot, blueprint, data_context, compute_results
                )

                # For SLOT_DELTA, convert list/dict to JSON string
                delta_text = (
                    json.dumps(ai_content, ensure_ascii=False)
                    if isinstance(ai_content, (list, dict))
                    else str(ai_content)
                )

                yield {
                    "type": "SLOT_DELTA",
                    "blockId": block_id,
                    "slotKey": slot_key,
                    "deltaText": delta_text,
                }

                _fill_single_block(block, component, ai_content)

                yield {
                    "type": "BLOCK_COMPLETE",
                    "blockId": block_id,
                }

    # ── Patch execution (Phase 6.4) ─────────────────────────────

    async def execute_patch(
        self,
        old_page: dict[str, Any],
        blueprint: Blueprint,
        patch_plan: "PatchPlan",
        data_context: dict[str, Any] | None = None,
        compute_results: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute a PatchPlan to incrementally modify a page.

        Args:
            old_page: The existing page to modify.
            blueprint: The Blueprint (for context).
            patch_plan: The PatchPlan with instructions.
            data_context: Data from Phase A (for PATCH_COMPOSE).
            compute_results: Results from Phase B (for PATCH_COMPOSE).

        Yields:
            SSE events: BLOCK_START/SLOT_DELTA/BLOCK_COMPLETE for AI regeneration,
            or just COMPLETE for layout-only changes.
        """
        from copy import deepcopy
        from models.patch import PatchType, RefineScope

        page = deepcopy(old_page)

        try:
            if patch_plan.scope == RefineScope.PATCH_LAYOUT:
                # Layout-only: apply prop changes directly
                yield {"type": "PHASE", "phase": "patch", "message": "Applying layout changes..."}

                for instruction in patch_plan.instructions:
                    block = _find_block_by_id(page, blueprint, instruction.target_block_id)
                    if block and instruction.type == PatchType.UPDATE_PROPS:
                        _apply_prop_patch(block, instruction.changes)

                yield {
                    "type": "COMPLETE",
                    "message": "completed",
                    "progress": 100,
                    "result": {
                        "response": "Layout updated",
                        "chatResponse": "Layout updated",
                        "page": page,
                    },
                }

            elif patch_plan.scope == RefineScope.PATCH_COMPOSE:
                # Compose: regenerate AI content for affected blocks
                yield {"type": "PHASE", "phase": "patch", "message": "Regenerating content..."}

                data_ctx = data_context or {}
                compute_res = compute_results or {}

                for instruction in patch_plan.instructions:
                    if instruction.type != PatchType.RECOMPOSE:
                        continue

                    block_id = instruction.target_block_id
                    slot = _find_slot(blueprint, block_id)
                    block = _find_block_by_id(page, blueprint, block_id)

                    if not slot or not block:
                        continue

                    component = slot.component_type.value
                    slot_key = _get_slot_key(component)

                    yield {
                        "type": "BLOCK_START",
                        "blockId": block_id,
                        "componentType": component,
                    }

                    # Generate new content with patch instruction context
                    ai_content = await self._generate_block_content(
                        slot, blueprint, data_ctx, compute_res
                    )

                    delta_text = (
                        json.dumps(ai_content, ensure_ascii=False)
                        if isinstance(ai_content, (list, dict))
                        else str(ai_content)
                    )

                    yield {
                        "type": "SLOT_DELTA",
                        "blockId": block_id,
                        "slotKey": slot_key,
                        "deltaText": delta_text,
                    }

                    _fill_single_block(block, component, ai_content)

                    yield {
                        "type": "BLOCK_COMPLETE",
                        "blockId": block_id,
                    }

                yield {
                    "type": "COMPLETE",
                    "message": "completed",
                    "progress": 100,
                    "result": {
                        "response": "Content regenerated",
                        "chatResponse": "Content regenerated",
                        "page": page,
                    },
                }

            else:
                # FULL_REBUILD: caller should use execute_blueprint_stream instead
                yield {
                    "type": "COMPLETE",
                    "message": "error",
                    "progress": 100,
                    "result": {
                        "response": "",
                        "chatResponse": "Full rebuild required — use execute_blueprint_stream",
                        "page": None,
                    },
                }

        except Exception as exc:
            logger.exception("Patch execution failed")
            yield {
                "type": "COMPLETE",
                "message": "error",
                "progress": 100,
                "result": {
                    "response": "",
                    "chatResponse": f"Patch failed: {exc}",
                    "page": None,
                },
            }


# ── Block builders ───────────────────────────────────────────


def _build_ai_placeholder(component_type: str, props: dict) -> dict[str, Any]:
    """Create a placeholder block for an AI content slot."""
    if component_type == "markdown":
        return {
            "type": "markdown",
            "content": "",
            "variant": props.get("variant", "default"),
        }
    if component_type == "suggestion_list":
        return {
            "type": "suggestion_list",
            "title": props.get("title", "Recommendations"),
            "items": [],
        }
    if component_type == "question_generator":
        return {
            "type": "question_generator",
            "title": props.get("title", "Practice Questions"),
            "questions": [],
        }
    return {"type": component_type, **props}


def _build_block(
    component_type: str,
    data: Any,
    props: dict,
) -> dict[str, Any]:
    """Build a deterministic block from component type + resolved data."""
    if component_type == "kpi_grid":
        return _build_kpi_block(data, props)
    if component_type == "chart":
        return _build_chart_block(data, props)
    if component_type == "table":
        return _build_table_block(data, props)
    if component_type == "markdown":
        return {
            "type": "markdown",
            "content": str(data) if data else "",
            "variant": props.get("variant", "default"),
        }
    return {"type": component_type, **props}


def _build_kpi_block(data: Any, props: dict) -> dict[str, Any]:
    """Build a kpi_grid block from statistics data."""
    items: list[dict[str, Any]] = []

    if isinstance(data, dict):
        kpi_fields = [
            ("mean", "Average"),
            ("median", "Median"),
            ("count", "Total Students"),
            ("max", "Highest Score"),
            ("min", "Lowest Score"),
        ]
        for key, label in kpi_fields:
            if key in data:
                items.append(
                    {
                        "label": label,
                        "value": str(data[key]),
                        "status": "neutral",
                        "subtext": "",
                    }
                )

    return {"type": "kpi_grid", "data": items}


def _build_chart_block(data: Any, props: dict) -> dict[str, Any]:
    """Build a chart block from distribution or series data."""
    block: dict[str, Any] = {
        "type": "chart",
        "variant": props.get("variant", "bar"),
        "title": props.get("title", "Chart"),
        "xAxis": [],
        "series": [],
    }

    if isinstance(data, dict):
        if "labels" in data and "counts" in data:
            # Direct distribution data (e.g. $compute.stats.distribution)
            block["xAxis"] = data["labels"]
            block["series"] = [{"name": "Count", "data": data["counts"]}]
        elif "distribution" in data:
            # Stats dict with nested distribution
            dist = data["distribution"]
            block["xAxis"] = dist.get("labels", [])
            block["series"] = [
                {"name": "Count", "data": dist.get("counts", [])}
            ]

    return block


def _build_table_block(data: Any, props: dict) -> dict[str, Any]:
    """Build a table block from submissions or generic list data."""
    block: dict[str, Any] = {
        "type": "table",
        "title": props.get("title", "Data"),
        "headers": [],
        "rows": [],
        "highlightRules": [],
    }

    if isinstance(data, dict) and "submissions" in data:
        block["headers"] = ["Student", "Score", "Submitted"]
        for sub in data["submissions"]:
            score = sub.get("score", 0)
            if score < 60:
                status = "warning"
            elif score >= 80:
                status = "success"
            else:
                status = "normal"
            block["rows"].append(
                {
                    "cells": [
                        sub.get("name", ""),
                        score,
                        sub.get("submitted", ""),
                    ],
                    "status": status,
                }
            )
    elif isinstance(data, list) and data and isinstance(data[0], dict):
        block["headers"] = list(data[0].keys())
        for item in data:
            block["rows"].append(
                {"cells": list(item.values()), "status": "normal"}
            )

    return block


# ── Block-level helpers (Phase 6.2) ──────────────────────────


def _get_slot_key(component_type: str) -> str:
    """Map component_type to the slot key used in SLOT_DELTA events."""
    return {
        "markdown": "content",
        "suggestion_list": "items",
        "question_generator": "questions",
    }.get(component_type, "content")


def _fill_single_block(
    block: dict[str, Any],
    component_type: str,
    ai_content: str | list | dict,
) -> None:
    """Fill a single AI content block with generated content.

    Args:
        block: The page block dict to fill.
        component_type: The component type (markdown, suggestion_list, etc.).
        ai_content: The AI-generated content (str, list, or dict).
    """
    if component_type == "markdown":
        block["content"] = str(ai_content) if ai_content else ""
    elif component_type == "suggestion_list":
        if isinstance(ai_content, list):
            block["items"] = ai_content
        else:
            # Fallback: wrap as single item
            block["items"] = [
                {
                    "title": "AI Analysis",
                    "description": str(ai_content),
                    "priority": "medium",
                    "category": "insight",
                }
            ]
    elif component_type == "question_generator":
        if isinstance(ai_content, list):
            block["questions"] = ai_content
        else:
            # Fallback: wrap as single question
            block["questions"] = [
                {
                    "id": "q1",
                    "type": "short_answer",
                    "question": str(ai_content),
                    "answer": "",
                }
            ]


def _parse_json_output(raw_output: str) -> list | dict | str:
    """Parse JSON from LLM output, with fallback to raw string.

    Handles common LLM quirks like markdown code blocks around JSON.
    """
    text = raw_output.strip()

    # Remove markdown code blocks if present
    code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if code_block_match:
        text = code_block_match.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse JSON output, using raw text: %s", text[:100])
        return raw_output


# ── Patch helpers (Phase 6.4) ─────────────────────────────────


def _find_slot(blueprint: Blueprint, slot_id: str) -> ComponentSlot | None:
    """Find a ComponentSlot in the Blueprint by ID."""
    for tab in blueprint.ui_composition.tabs:
        for slot in tab.slots:
            if slot.id == slot_id:
                return slot
    return None


def _find_block_by_id(
    page: dict[str, Any],
    blueprint: Blueprint,
    block_id: str,
) -> dict[str, Any] | None:
    """Find a block in the page by matching slot ID from Blueprint."""
    for tab_idx, tab in enumerate(blueprint.ui_composition.tabs):
        for slot_idx, slot in enumerate(tab.slots):
            if slot.id == block_id:
                try:
                    return page["tabs"][tab_idx]["blocks"][slot_idx]
                except (IndexError, KeyError):
                    return None
    return None


def _apply_prop_patch(block: dict[str, Any], changes: dict[str, Any]) -> None:
    """Apply property changes to a block."""
    for key, value in changes.items():
        block[key] = value


# ── Topological sort ─────────────────────────────────────────


def _topo_sort(
    items: list,
    get_id: Any,
    get_deps: Any,
) -> list:
    """Topological sort for items with dependency lists.

    Args:
        items: Items to sort.
        get_id: Callable returning item ID.
        get_deps: Callable returning list of dependency IDs.

    Returns:
        Items sorted so dependencies come first.

    Raises:
        ValueError: If circular dependency is detected.
    """
    id_map = {get_id(item): item for item in items}
    result: list = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(item_id: str) -> None:
        if item_id in visited:
            return
        if item_id in visiting:
            raise ValueError(f"Circular dependency detected: {item_id}")
        visiting.add(item_id)
        item = id_map.get(item_id)
        if item:
            for dep_id in get_deps(item):
                visit(dep_id)
        visiting.discard(item_id)
        visited.add(item_id)
        if item:
            result.append(item)

    for item in items:
        visit(get_id(item))

    return result
