"""ExecutorAgent compose prompt — guides LLM to generate analytical narrative.

The compose prompt is used in Phase C of Blueprint execution to generate
AI content for ai_content_slot components (markdown insights, etc.).
"""

from __future__ import annotations

import json
from typing import Any

from models.blueprint import Blueprint


def build_compose_prompt(
    blueprint: Blueprint,
    data_context: dict[str, Any],
    compute_results: dict[str, Any],
) -> str:
    """Build the prompt for AI narrative generation in the compose phase.

    Injects fetched data and computed statistics so the LLM can write a
    data-driven analysis. The LLM should use exact numbers from compute
    results and avoid hallucinating data.

    Args:
        blueprint: The Blueprint being executed.
        data_context: Data fetched in Phase A (binding_id → result).
        compute_results: Results from Phase B compute nodes (output_key → result).

    Returns:
        Complete compose prompt string.
    """
    # Data summary
    data_lines: list[str] = []
    for key, value in data_context.items():
        data_lines.append(
            f"### {key}\n```json\n"
            f"{json.dumps(value, indent=2, ensure_ascii=False, default=str)}\n```"
        )
    data_summary = "\n\n".join(data_lines) if data_lines else "No data fetched."

    # Compute summary
    compute_lines: list[str] = []
    for key, value in compute_results.items():
        compute_lines.append(
            f"### {key}\n```json\n"
            f"{json.dumps(value, indent=2, ensure_ascii=False, default=str)}\n```"
        )
    compute_summary = (
        "\n\n".join(compute_lines) if compute_lines else "No computations performed."
    )

    # AI content slots
    ai_slot_lines: list[str] = []
    for tab in blueprint.ui_composition.tabs:
        for slot in tab.slots:
            if slot.ai_content_slot:
                ai_slot_lines.append(
                    f"- Tab \"{tab.label}\", Slot \"{slot.id}\" "
                    f"(type: {slot.component_type.value})"
                )
    ai_slots_text = "\n".join(ai_slot_lines) if ai_slot_lines else "None"

    return f"""\
Based on the following data and computed statistics, generate an analytical
narrative for a teacher.

## Fetched Data

{data_summary}

## Computed Statistics

{compute_summary}

## AI Content Slots

{ai_slots_text}

## Instructions

Write a concise, data-driven analytical narrative that:
1. Highlights key findings from the computed statistics (use exact numbers)
2. Identifies notable patterns, strengths, and areas for improvement
3. Provides specific, actionable teaching recommendations

Important rules:
- Use the EXACT numbers from the computed statistics. Do NOT make up numbers.
- Reference specific data points when making claims.
- Be concise — keep the response under 500 words.
- Use markdown formatting (headings, bold, lists).
- Write in a professional but approachable tone suitable for teachers."""
