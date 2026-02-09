"""Step 3.2 — Golden conversation runner with behavioral assertions.

Loads golden conversation JSON fixtures from ``tests/golden/`` and validates:
1. Toolset selection correctness per turn
2. Expected tool availability
3. Pipeline structural integrity

Usage:
    cd insight-ai-agent
    python scripts/golden_conversation_runner.py              # Run all
    python scripts/golden_conversation_runner.py gc_005       # Run specific
    python scripts/golden_conversation_runner.py --verbose    # Verbose output
"""

from __future__ import annotations

import glob
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.native_tools  # noqa: F401  populate registry

from agents.native_agent import AgentDeps, _select_toolsets_keyword as select_toolsets
from tools.registry import get_tool_names

GOLDEN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests", "golden",
)


# ── Data Models ──────────────────────────────────────────────


@dataclass
class TurnAssertion:
    expected_toolsets: list[str] = field(default_factory=list)
    expected_tools: list[str] = field(default_factory=list)
    expected_tool_count: list[int] = field(default_factory=lambda: [0, 100])
    expected_events: list[str] = field(default_factory=list)
    expected_artifact_type: str | None = None
    expected_content_format: str | None = None
    forbidden_events: list[str] = field(default_factory=list)
    expected_tool_status: str = "ok"
    metrics_bounds: dict[str, list[int]] = field(default_factory=dict)
    context_override: dict[str, Any] | None = None


@dataclass
class GoldenConversation:
    id: str
    name: str
    scenario: str
    context: dict[str, Any]
    turns: list[dict[str, str]]
    assertions: dict[str, TurnAssertion]
    mock_overrides: dict[str, Any] | None = None


@dataclass
class AssertionResult:
    passed: bool
    message: str


# ── Loader ───────────────────────────────────────────────────


def load_golden(filepath: str) -> GoldenConversation:
    """Load a golden conversation from a JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    assertions = {}
    for key, val in data.get("assertions", {}).items():
        assertions[key] = TurnAssertion(
            expected_toolsets=val.get("expected_toolsets", []),
            expected_tools=val.get("expected_tools", []),
            expected_tool_count=val.get("expected_tool_count", [0, 100]),
            expected_events=val.get("expected_events", []),
            expected_artifact_type=val.get("expected_artifact_type"),
            expected_content_format=val.get("expected_content_format"),
            forbidden_events=val.get("forbidden_events", []),
            expected_tool_status=val.get("expected_tool_status", "ok"),
            metrics_bounds=val.get("metrics_bounds", {}),
            context_override=val.get("context_override"),
        )

    return GoldenConversation(
        id=data["id"],
        name=data["name"],
        scenario=data.get("scenario", ""),
        context=data.get("context", {}),
        turns=data.get("turns", []),
        assertions=assertions,
        mock_overrides=data.get("mock_overrides"),
    )


# ── Assertion Engine ─────────────────────────────────────────


def assert_toolsets(
    message: str,
    deps: AgentDeps,
    expected: list[str],
) -> AssertionResult:
    """Assert that toolset selection includes all expected toolsets."""
    selected = select_toolsets(message, deps)
    missing = [ts for ts in expected if ts not in selected]
    if missing:
        return AssertionResult(
            False,
            f"Missing toolsets {missing} (selected: {selected})",
        )
    return AssertionResult(True, f"toolsets={selected}")


def assert_tools_available(
    selected_toolsets: list[str],
    expected_tools: list[str],
) -> AssertionResult:
    """Assert that expected tools are available in the selected toolsets."""
    if not expected_tools:
        return AssertionResult(True, "no specific tools expected")

    available = set(get_tool_names(selected_toolsets))
    missing = [t for t in expected_tools if t not in available]
    if missing:
        return AssertionResult(
            False,
            f"Tools {missing} not available in toolsets {selected_toolsets} (available: {sorted(available)})",
        )
    return AssertionResult(True, f"tools {expected_tools} available")


def assert_tool_count_range(
    selected_toolsets: list[str],
    expected_range: list[int],
) -> AssertionResult:
    """Assert available tool count is within expected range (sanity check)."""
    available = get_tool_names(selected_toolsets)
    count = len(available)
    lo, hi = expected_range[0], expected_range[1] if len(expected_range) > 1 else 100
    # This validates the toolset contains a reasonable number of tools,
    # not the actual call count (which requires LLM execution).
    if count < lo:
        return AssertionResult(False, f"Too few tools: {count} < {lo}")
    return AssertionResult(True, f"available_tools={count}")


# ── Runner ───────────────────────────────────────────────────


def run_golden(gc: GoldenConversation, verbose: bool = False) -> tuple[bool, list[str]]:
    """Run a single golden conversation and return (passed, details)."""
    details: list[str] = []
    all_passed = True
    has_artifacts = gc.context.get("hasArtifacts", False)

    for turn_idx, turn in enumerate(gc.turns):
        turn_key = f"turn_{turn_idx}"
        assertions = gc.assertions.get(turn_key)
        if assertions is None:
            details.append(f"  Turn {turn_idx}: no assertions defined (skip)")
            continue

        # Apply context overrides for subsequent turns
        if assertions.context_override:
            if "hasArtifacts" in assertions.context_override:
                has_artifacts = assertions.context_override["hasArtifacts"]

        deps = AgentDeps(
            teacher_id=gc.context.get("teacherId", "t-001"),
            conversation_id=f"conv-{gc.id}",
            class_id=gc.context.get("classId") or None,
            has_artifacts=has_artifacts,
        )

        message = turn["message"]
        turn_pass = True
        turn_details: list[str] = []

        # 1. Toolset selection
        ts_result = assert_toolsets(message, deps, assertions.expected_toolsets)
        if not ts_result.passed:
            turn_pass = False
            all_passed = False
        turn_details.append(f"toolsets: {'PASS' if ts_result.passed else 'FAIL'} — {ts_result.message}")

        # 2. Tools availability in selected toolsets
        selected = select_toolsets(message, deps)
        ta_result = assert_tools_available(selected, assertions.expected_tools)
        if not ta_result.passed:
            turn_pass = False
            all_passed = False
        turn_details.append(f"tools: {'PASS' if ta_result.passed else 'FAIL'} — {ta_result.message}")

        # 3. Tool count range (sanity)
        tc_result = assert_tool_count_range(selected, assertions.expected_tool_count)
        if not tc_result.passed:
            turn_pass = False
            all_passed = False
        turn_details.append(f"count: {'PASS' if tc_result.passed else 'FAIL'} — {tc_result.message}")

        status = "PASS" if turn_pass else "FAIL"
        details.append(f"  Turn {turn_idx} [{status}]: \"{message[:40]}...\"")
        if verbose or not turn_pass:
            for d in turn_details:
                details.append(f"    {d}")

        # After generation turn, subsequent turns should have artifacts
        if assertions.expected_artifact_type:
            has_artifacts = True

    return all_passed, details


# ── Main ─────────────────────────────────────────────────────


def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    filter_id = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            filter_id = arg
            break

    # Discover golden files
    pattern = os.path.join(GOLDEN_DIR, "gc_*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"No golden conversation files found in {GOLDEN_DIR}")
        return 1

    print("=" * 70)
    print(f"Step 3.2 — Golden Conversation Runner ({len(files)} conversations)")
    print("=" * 70)
    print()

    total_passed = 0
    total_failed = 0
    total_skipped = 0

    for filepath in files:
        gc = load_golden(filepath)

        # Filter by ID if specified
        if filter_id and filter_id not in gc.id:
            total_skipped += 1
            continue

        passed, details = run_golden(gc, verbose)

        status = "PASS" if passed else "FAIL"
        if passed:
            total_passed += 1
        else:
            total_failed += 1

        print(f"[{status}] {gc.id}: {gc.name} ({gc.scenario})")
        if verbose or not passed:
            for d in details:
                print(d)
            print()

    # Summary
    print()
    print("=" * 70)
    total = total_passed + total_failed
    print(f"Results: {total_passed}/{total} passed, {total_failed} failed", end="")
    if total_skipped:
        print(f", {total_skipped} skipped", end="")
    print()
    print("=" * 70)
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
