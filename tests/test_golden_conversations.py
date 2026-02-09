"""Step 3.2.4 — pytest wrapper for golden conversation behavioral tests.

Parameterizes over all ``tests/golden/gc_*.json`` fixtures and validates:
1. Toolset selection includes expected toolsets
2. Expected tools are available in selected toolsets
3. Context overrides are applied correctly across multi-turn conversations

Run:
    cd insight-ai-agent
    pytest tests/test_golden_conversations.py -v
"""

from __future__ import annotations

import glob
import json
import os
from typing import Any

import pytest

import tools.native_tools  # noqa: F401  populate registry

from agents.native_agent import AgentDeps, select_toolsets
from tools.registry import get_tool_names

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
GOLDEN_FILES = sorted(glob.glob(os.path.join(GOLDEN_DIR, "gc_*.json")))


def _load_gc(filepath: str) -> dict[str, Any]:
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def _gc_id(filepath: str) -> str:
    return os.path.splitext(os.path.basename(filepath))[0]


# ── Parameterized Tests ──────────────────────────────────────


@pytest.mark.parametrize(
    "gc_file",
    GOLDEN_FILES,
    ids=[_gc_id(f) for f in GOLDEN_FILES],
)
def test_golden_toolset_selection(gc_file: str):
    """Each turn's message + context → correct toolsets selected."""
    gc = _load_gc(gc_file)
    context = gc.get("context", {})
    has_artifacts = context.get("hasArtifacts", False)

    for turn_idx, turn in enumerate(gc["turns"]):
        turn_key = f"turn_{turn_idx}"
        assertions = gc.get("assertions", {}).get(turn_key)
        if assertions is None:
            continue

        # Apply context overrides for multi-turn
        override = assertions.get("context_override", {})
        if "hasArtifacts" in override:
            has_artifacts = override["hasArtifacts"]

        deps = AgentDeps(
            teacher_id=context.get("teacherId", "t-001"),
            conversation_id=f"conv-{gc['id']}",
            class_id=context.get("classId") or None,
            has_artifacts=has_artifacts,
        )

        selected = select_toolsets(turn["message"], deps)
        expected = assertions.get("expected_toolsets", [])
        missing = [ts for ts in expected if ts not in selected]

        assert not missing, (
            f"[{gc['id']}] Turn {turn_idx} \"{turn['message'][:40]}\" — "
            f"missing toolsets {missing} (selected: {selected})"
        )

        # After a generation turn, mark artifacts as present
        if assertions.get("expected_artifact_type"):
            has_artifacts = True


@pytest.mark.parametrize(
    "gc_file",
    GOLDEN_FILES,
    ids=[_gc_id(f) for f in GOLDEN_FILES],
)
def test_golden_tools_available(gc_file: str):
    """Expected tools are available in the selected toolsets."""
    gc = _load_gc(gc_file)
    context = gc.get("context", {})
    has_artifacts = context.get("hasArtifacts", False)

    for turn_idx, turn in enumerate(gc["turns"]):
        turn_key = f"turn_{turn_idx}"
        assertions = gc.get("assertions", {}).get(turn_key)
        if assertions is None:
            continue

        override = assertions.get("context_override", {})
        if "hasArtifacts" in override:
            has_artifacts = override["hasArtifacts"]

        deps = AgentDeps(
            teacher_id=context.get("teacherId", "t-001"),
            conversation_id=f"conv-{gc['id']}",
            class_id=context.get("classId") or None,
            has_artifacts=has_artifacts,
        )

        selected = select_toolsets(turn["message"], deps)
        expected_tools = assertions.get("expected_tools", [])
        if not expected_tools:
            continue

        available = set(get_tool_names(selected))
        missing = [t for t in expected_tools if t not in available]
        assert not missing, (
            f"[{gc['id']}] Turn {turn_idx} — tools {missing} not available "
            f"in toolsets {selected} (available: {sorted(available)})"
        )

        if assertions.get("expected_artifact_type"):
            has_artifacts = True


@pytest.mark.parametrize(
    "gc_file",
    GOLDEN_FILES,
    ids=[_gc_id(f) for f in GOLDEN_FILES],
)
def test_golden_always_toolsets(gc_file: str):
    """base_data and platform are always present in every turn."""
    gc = _load_gc(gc_file)
    context = gc.get("context", {})
    has_artifacts = context.get("hasArtifacts", False)

    for turn_idx, turn in enumerate(gc["turns"]):
        turn_key = f"turn_{turn_idx}"
        assertions = gc.get("assertions", {}).get(turn_key)
        if assertions is None:
            continue

        override = assertions.get("context_override") or {}
        if "hasArtifacts" in override:
            has_artifacts = override["hasArtifacts"]

        deps = AgentDeps(
            teacher_id=context.get("teacherId", "t-001"),
            conversation_id=f"conv-{gc['id']}",
            class_id=context.get("classId") or None,
            has_artifacts=has_artifacts,
        )

        selected = select_toolsets(turn["message"], deps)
        assert "base_data" in selected, (
            f"[{gc['id']}] Turn {turn_idx} — base_data missing from {selected}"
        )
        assert "platform" in selected, (
            f"[{gc['id']}] Turn {turn_idx} — platform missing from {selected}"
        )

        if assertions.get("expected_artifact_type"):
            has_artifacts = True


@pytest.mark.parametrize(
    "gc_file",
    GOLDEN_FILES,
    ids=[_gc_id(f) for f in GOLDEN_FILES],
)
def test_golden_no_exclusive_routing(gc_file: str):
    """Toolset selection never returns fewer than ALWAYS_TOOLSETS."""
    gc = _load_gc(gc_file)
    context = gc.get("context", {})
    has_artifacts = context.get("hasArtifacts", False)

    for turn_idx, turn in enumerate(gc["turns"]):
        turn_key = f"turn_{turn_idx}"
        assertions = gc.get("assertions", {}).get(turn_key)
        if assertions is None:
            continue

        override = assertions.get("context_override") or {}
        if "hasArtifacts" in override:
            has_artifacts = override["hasArtifacts"]

        deps = AgentDeps(
            teacher_id=context.get("teacherId", "t-001"),
            conversation_id=f"conv-{gc['id']}",
            class_id=context.get("classId") or None,
            has_artifacts=has_artifacts,
        )

        selected = select_toolsets(turn["message"], deps)
        # Frozen constraint from Step 2: at least 2 toolsets always
        assert len(selected) >= 2, (
            f"[{gc['id']}] Turn {turn_idx} — only {len(selected)} toolsets: {selected}"
        )

        if assertions.get("expected_artifact_type"):
            has_artifacts = True
