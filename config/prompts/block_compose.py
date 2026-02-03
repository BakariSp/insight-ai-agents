"""Per-block AI prompt builders for ExecutorAgent Phase C.

Each ai_content_slot gets a customized prompt based on its component_type:
- markdown: narrative analysis prompt
- suggestion_list: structured JSON suggestions prompt
- question_generator: structured JSON questions prompt
"""

from __future__ import annotations

import json
from typing import Any, Literal

from models.blueprint import Blueprint, ComponentSlot


OutputFormat = Literal["text", "json"]


def build_block_prompt(
    slot: ComponentSlot,
    blueprint: Blueprint | None,
    data_context: dict[str, Any],
    compute_results: dict[str, Any],
) -> tuple[str, OutputFormat]:
    """Build a customized prompt for a single AI content block.

    Args:
        slot: The ComponentSlot to generate content for.
        blueprint: The Blueprint being executed.
        data_context: Data fetched in Phase A.
        compute_results: Results from Phase B compute nodes.

    Returns:
        Tuple of (prompt_string, output_format).
        output_format is "text" for markdown, "json" for structured types.
    """
    component_type = slot.component_type.value
    data_summary = _build_data_summary(data_context, compute_results)

    if component_type == "markdown":
        return _build_markdown_prompt(slot, blueprint, data_summary), "text"
    if component_type == "suggestion_list":
        return _build_suggestion_prompt(slot, blueprint, data_summary), "json"
    if component_type == "question_generator":
        return _build_question_prompt(slot, blueprint, data_summary), "json"

    # Fallback to markdown-style prompt
    return _build_markdown_prompt(slot, blueprint, data_summary), "text"


def _build_data_summary(
    data_context: dict[str, Any],
    compute_results: dict[str, Any],
) -> str:
    """Build a summary of available data for injection into prompts."""
    sections: list[str] = []

    if data_context:
        data_lines = []
        for key, value in data_context.items():
            data_lines.append(
                f"### {key}\n```json\n"
                f"{json.dumps(value, indent=2, ensure_ascii=False, default=str)}\n```"
            )
        sections.append("## Fetched Data\n\n" + "\n\n".join(data_lines))

    if compute_results:
        compute_lines = []
        for key, value in compute_results.items():
            compute_lines.append(
                f"### {key}\n```json\n"
                f"{json.dumps(value, indent=2, ensure_ascii=False, default=str)}\n```"
            )
        sections.append("## Computed Statistics\n\n" + "\n\n".join(compute_lines))

    return "\n\n".join(sections) if sections else "No data available."


def _build_markdown_prompt(
    slot: ComponentSlot,
    blueprint: Blueprint | None,
    data_summary: str,
) -> str:
    """Build prompt for markdown narrative content."""
    slot_props = slot.props or {}
    variant = slot_props.get("variant", "insight")

    return f"""\
Based on the following data and statistics, write an analytical narrative.

{data_summary}

## Block: {slot.id}
- Type: markdown
- Variant: {variant}

## Instructions

Write a concise, data-driven analysis that:
1. Highlights key findings from the computed statistics (use EXACT numbers)
2. Identifies notable patterns, strengths, and areas for improvement
3. Provides specific, actionable teaching recommendations

Important rules:
- Use the EXACT numbers from the statistics. Do NOT make up numbers.
- Reference specific data points when making claims.
- Keep the response under 300 words.
- Use markdown formatting (headings, bold, lists).
- Write in a professional but approachable tone suitable for teachers."""


def _build_suggestion_prompt(
    slot: ComponentSlot,
    blueprint: Blueprint | None,
    data_summary: str,
) -> str:
    """Build prompt for suggestion_list JSON content."""
    slot_props = slot.props or {}
    max_items = slot_props.get("maxItems", 5)
    categories = slot_props.get("categories", ["improvement", "strength", "action"])

    return f"""\
Based on the following data and statistics, generate actionable teaching suggestions.

{data_summary}

## Block: {slot.id}
- Type: suggestion_list
- Max items: {max_items}
- Categories: {", ".join(categories)}

## Output Format

Return a JSON array of suggestion objects. Each object must have:
- "title": short title (under 50 characters)
- "description": detailed description (1-2 sentences)
- "priority": one of "high", "medium", "low"
- "category": one of {categories}

Example:
```json
[
  {{"title": "Focus on vocabulary gaps", "description": "Students scored lowest on vocabulary questions. Consider adding more vocabulary exercises.", "priority": "high", "category": "improvement"}},
  {{"title": "Maintain reading comprehension", "description": "Reading scores are strong. Continue current approach.", "priority": "low", "category": "strength"}}
]
```

Important rules:
- Generate {max_items} or fewer suggestions.
- Base suggestions on ACTUAL data, not hypothetical scenarios.
- Each suggestion must be specific and actionable.
- Return ONLY the JSON array, no additional text."""


def _build_question_prompt(
    slot: ComponentSlot,
    blueprint: Blueprint | None,
    data_summary: str,
) -> str:
    """Build prompt for question_generator JSON content."""
    slot_props = slot.props or {}
    question_count = slot_props.get("count", 5)
    question_types = slot_props.get("types", ["multiple_choice", "short_answer"])
    difficulty = slot_props.get("difficulty", "medium")
    subject = slot_props.get("subject", "general")

    return f"""\
Based on the following data, generate practice questions for students.

{data_summary}

## Block: {slot.id}
- Type: question_generator
- Count: {question_count} questions
- Types: {", ".join(question_types)}
- Difficulty: {difficulty}
- Subject: {subject}

## Output Format

Return a JSON array of question objects. Each object must have:
- "id": unique identifier (e.g., "q1", "q2")
- "type": one of {question_types}
- "question": the question text
- "options": (for multiple_choice only) array of 4 options
- "answer": the correct answer
- "explanation": brief explanation of the answer

Example:
```json
[
  {{"id": "q1", "type": "multiple_choice", "question": "What is the main idea of the passage?", "options": ["A. ...", "B. ...", "C. ...", "D. ..."], "answer": "B", "explanation": "The passage focuses on..."}},
  {{"id": "q2", "type": "short_answer", "question": "Explain why...", "answer": "Because...", "explanation": "This tests understanding of..."}}
]
```

Important rules:
- Generate exactly {question_count} questions.
- Questions should target areas where students need improvement (based on the data).
- Each question must have a clear, unambiguous answer.
- Return ONLY the JSON array, no additional text."""
