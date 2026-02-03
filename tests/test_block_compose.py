"""Tests for per-block prompt builders."""

import pytest

from config.prompts.block_compose import (
    build_block_prompt,
    _build_data_summary,
    _build_markdown_prompt,
    _build_suggestion_prompt,
    _build_question_prompt,
)
from models.blueprint import ComponentSlot, ComponentType


def _make_slot(
    component_type: str = "markdown",
    slot_id: str = "test-slot",
    props: dict | None = None,
) -> ComponentSlot:
    """Create a ComponentSlot for testing."""
    return ComponentSlot(
        id=slot_id,
        component_type=ComponentType(component_type),
        props=props or {},
        ai_content_slot=True,
    )


# ── Data summary tests ────────────────────────────────────────


def test_build_data_summary_with_data():
    """_build_data_summary includes both data and compute sections."""
    data_context = {"submissions": {"count": 30, "scores": [85, 72]}}
    compute_results = {"stats": {"mean": 78.5}}

    summary = _build_data_summary(data_context, compute_results)

    assert "## Fetched Data" in summary
    assert "submissions" in summary
    assert "## Computed Statistics" in summary
    assert "stats" in summary
    assert "78.5" in summary


def test_build_data_summary_empty():
    """_build_data_summary returns fallback when no data."""
    summary = _build_data_summary({}, {})
    assert summary == "No data available."


def test_build_data_summary_only_data():
    """_build_data_summary with only data_context."""
    data_context = {"scores": [85, 72]}
    summary = _build_data_summary(data_context, {})

    assert "## Fetched Data" in summary
    assert "## Computed Statistics" not in summary


def test_build_data_summary_only_compute():
    """_build_data_summary with only compute_results."""
    compute_results = {"mean": 82.7}
    summary = _build_data_summary({}, compute_results)

    assert "## Fetched Data" not in summary
    assert "## Computed Statistics" in summary


# ── Markdown prompt tests ─────────────────────────────────────


def test_markdown_prompt_contains_data_summary():
    """Markdown prompt includes injected data summary."""
    slot = _make_slot("markdown", props={"variant": "insight"})
    data_context = {"scores": [85, 72, 91]}
    compute_results = {"mean": 82.7}

    prompt, fmt = build_block_prompt(slot, None, data_context, compute_results)

    assert fmt == "text"
    assert "82.7" in prompt
    assert "markdown" in prompt.lower()
    assert "insight" in prompt


def test_markdown_prompt_instructions():
    """Markdown prompt contains analysis instructions."""
    slot = _make_slot("markdown")

    prompt, _ = build_block_prompt(slot, None, {}, {})

    assert "EXACT numbers" in prompt
    assert "actionable" in prompt.lower()


def test_markdown_prompt_default_variant():
    """Markdown prompt uses default variant when not specified."""
    slot = _make_slot("markdown", props={})

    prompt, _ = build_block_prompt(slot, None, {}, {})

    assert "insight" in prompt  # default variant


# ── Suggestion prompt tests ───────────────────────────────────


def test_suggestion_prompt_requests_json_format():
    """Suggestion prompt specifies JSON output format."""
    slot = _make_slot("suggestion_list", props={"maxItems": 3})

    prompt, fmt = build_block_prompt(slot, None, {}, {})

    assert fmt == "json"
    assert "JSON array" in prompt
    assert '"title"' in prompt
    assert '"priority"' in prompt


def test_suggestion_prompt_uses_slot_props():
    """Suggestion prompt incorporates slot.props values."""
    slot = _make_slot(
        "suggestion_list",
        props={"maxItems": 7, "categories": ["focus", "celebrate"]},
    )

    prompt, _ = build_block_prompt(slot, None, {}, {})

    assert "7" in prompt
    assert "focus" in prompt
    assert "celebrate" in prompt


def test_suggestion_prompt_default_props():
    """Suggestion prompt uses defaults when props not specified."""
    slot = _make_slot("suggestion_list", props={})

    prompt, _ = build_block_prompt(slot, None, {}, {})

    assert "5" in prompt  # default maxItems
    assert "improvement" in prompt  # default category


# ── Question prompt tests ─────────────────────────────────────


def test_question_prompt_includes_slot_props():
    """Question prompt uses slot.props for configuration."""
    slot = _make_slot(
        "question_generator",
        props={
            "count": 10,
            "types": ["fill_in_blank"],
            "difficulty": "hard",
            "subject": "math",
        },
    )

    prompt, fmt = build_block_prompt(slot, None, {}, {})

    assert fmt == "json"
    assert "10 questions" in prompt
    assert "fill_in_blank" in prompt
    assert "hard" in prompt
    assert "math" in prompt


def test_question_prompt_example_structure():
    """Question prompt includes example JSON structure."""
    slot = _make_slot("question_generator")

    prompt, _ = build_block_prompt(slot, None, {}, {})

    assert '"id"' in prompt
    assert '"question"' in prompt
    assert '"answer"' in prompt


def test_question_prompt_default_props():
    """Question prompt uses defaults when props not specified."""
    slot = _make_slot("question_generator", props={})

    prompt, _ = build_block_prompt(slot, None, {}, {})

    assert "5 questions" in prompt  # default count
    assert "multiple_choice" in prompt  # default type
    assert "medium" in prompt  # default difficulty


# ── build_block_prompt dispatch tests ─────────────────────────


def test_build_block_prompt_unknown_type_fallback():
    """Unknown component type falls back to markdown prompt."""
    # Create slot with a known type first, then test fallback logic
    slot = _make_slot("markdown")

    prompt, fmt = build_block_prompt(slot, None, {}, {})

    assert fmt == "text"
    assert "markdown" in prompt.lower()


def test_build_block_prompt_includes_block_id():
    """Prompt includes the slot ID for context."""
    slot = _make_slot("markdown", slot_id="my-insight-block")

    prompt, _ = build_block_prompt(slot, None, {}, {})

    assert "my-insight-block" in prompt
