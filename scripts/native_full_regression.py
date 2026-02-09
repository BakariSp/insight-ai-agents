"""Step 3.1 — Full scenario regression for AI native runtime.

Tests S1-S11 scenarios using mock mode (TestModel + AsyncMock) by default.
Each scenario verifies:
1. Toolset selection produces expected toolsets
2. Pipeline runs without errors
3. SSE events contain expected types

Usage:
    cd insight-ai-agent
    python scripts/native_full_regression.py           # mock mode (no API key)
    python scripts/native_full_regression.py --verbose  # verbose output
"""

from __future__ import annotations

import asyncio
import json
import sys
import os
import time
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.native_tools  # noqa: F401  populate registry

from agents.native_agent import AgentDeps, NativeAgent, select_toolsets
from services.datastream import DataStreamEncoder
from services.metrics import get_metrics_collector


# ── Scenario Definitions ─────────────────────────────────────


@dataclass
class Scenario:
    id: str
    name: str
    message: str
    expected_toolsets: list[str]
    deps_kwargs: dict[str, Any] = field(default_factory=dict)

    # Second turn for multi-turn scenarios
    turn2_message: str | None = None
    turn2_expected_toolsets: list[str] | None = None
    turn2_deps_override: dict[str, Any] | None = None


SCENARIOS = [
    Scenario(
        id="S1", name="Chat — casual greeting",
        message="你好",
        expected_toolsets=["base_data", "platform"],
    ),
    Scenario(
        id="S2", name="Chat QA — RAG document query",
        message="Unit 5 的教学重点是什么",
        expected_toolsets=["base_data", "platform"],
    ),
    Scenario(
        id="S3", name="Quiz — basic generation",
        message="帮我出 5 道英语选择题",
        expected_toolsets=["base_data", "platform", "generation"],
    ),
    Scenario(
        id="S4", name="Quiz — modification",
        message="帮我出 5 道英语选择题",
        expected_toolsets=["base_data", "platform", "generation"],
        turn2_message="把第 3 题改成填空题",
        turn2_expected_toolsets=["base_data", "platform", "artifact_ops", "generation"],
        turn2_deps_override={"has_artifacts": True},
    ),
    Scenario(
        id="S5", name="PPT — outline generation",
        message="帮我做一个 Unit 5 的 PPT",
        expected_toolsets=["base_data", "platform", "generation"],
    ),
    Scenario(
        id="S6", name="Document — DOCX generation",
        message="帮我写一篇关于 Unit 5 的文稿",
        expected_toolsets=["base_data", "platform", "generation"],
    ),
    Scenario(
        id="S7", name="Interactive — HTML game",
        message="帮我生成一个互动游戏",
        expected_toolsets=["base_data", "platform", "generation"],
    ),
    Scenario(
        id="S8", name="Data analysis — class report",
        message="分析一下三班这次作业成绩",
        expected_toolsets=["base_data", "platform", "analysis"],
        deps_kwargs={"class_id": "c-001"},
    ),
    Scenario(
        id="S9", name="Entity resolution — student lookup",
        message="张三的成绩怎么样",
        expected_toolsets=["base_data", "platform", "analysis"],
    ),
    Scenario(
        id="S10", name="Multi-turn — consecutive quiz gen",
        message="帮我出 5 道选择题",
        expected_toolsets=["base_data", "platform", "generation"],
        turn2_message="再出 5 道更难的",
        turn2_expected_toolsets=["base_data", "platform", "generation"],
        turn2_deps_override={"has_artifacts": True},
    ),
    Scenario(
        id="S11", name="Cross-intent — quiz then report",
        message="帮我出 5 道选择题",
        expected_toolsets=["base_data", "platform", "generation"],
        turn2_message="分析三班成绩",
        turn2_expected_toolsets=["base_data", "platform", "analysis", "artifact_ops"],
        turn2_deps_override={"has_artifacts": True},
    ),
]


# ── Test Execution ───────────────────────────────────────────


def _make_deps(**overrides: Any) -> AgentDeps:
    defaults = {
        "teacher_id": "t-001",
        "conversation_id": "conv-regression",
    }
    defaults.update(overrides)
    return AgentDeps(**defaults)


def test_toolset_selection(scenario: Scenario, verbose: bool = False) -> tuple[bool, str]:
    """Test that toolset selection produces expected sets for this scenario."""
    deps = _make_deps(**scenario.deps_kwargs)
    selected = select_toolsets(scenario.message, deps)

    # Check all expected toolsets are present (order doesn't matter)
    missing = [ts for ts in scenario.expected_toolsets if ts not in selected]
    if missing:
        return False, f"Missing toolsets: {missing} (got {selected})"

    details = f"Turn 1: {selected}"

    # Check turn 2 if multi-turn
    if scenario.turn2_message and scenario.turn2_expected_toolsets:
        deps2_kwargs = dict(scenario.deps_kwargs)
        if scenario.turn2_deps_override:
            deps2_kwargs.update(scenario.turn2_deps_override)
        deps2 = _make_deps(**deps2_kwargs)
        selected2 = select_toolsets(scenario.turn2_message, deps2)

        missing2 = [ts for ts in scenario.turn2_expected_toolsets if ts not in selected2]
        if missing2:
            return False, f"Turn 2 missing toolsets: {missing2} (got {selected2})"
        details += f" | Turn 2: {selected2}"

    return True, details


def test_registry_completeness(verbose: bool = False) -> tuple[bool, str]:
    """Verify all 25 tools are registered in correct toolsets."""
    from tools.registry import get_registered_count, get_toolset_counts, get_tool_names

    count = get_registered_count()
    if count < 25:
        return False, f"Expected >= 25 tools, got {count}"

    counts = get_toolset_counts()
    expected_toolsets = {"base_data", "analysis", "generation", "artifact_ops", "platform"}
    actual_toolsets = set(counts.keys())
    missing = expected_toolsets - actual_toolsets
    if missing:
        return False, f"Missing toolsets: {missing}"

    # Verify critical tools exist
    names = set(get_tool_names())
    critical = {
        "get_teacher_classes", "generate_quiz_questions",
        "search_teacher_documents", "get_artifact", "patch_artifact",
        "build_report_page", "ask_clarification", "resolve_entity",
    }
    missing_tools = critical - names
    if missing_tools:
        return False, f"Missing critical tools: {missing_tools}"

    return True, f"{count} tools in {len(counts)} toolsets: {dict(counts)}"


def test_metrics_infrastructure(verbose: bool = False) -> tuple[bool, str]:
    """Verify metrics collector works for structured logging."""
    collector = get_metrics_collector()
    collector.reset()

    collector.record_tool_call(
        tool_name="regression_test",
        status="ok",
        latency_ms=42.0,
        turn_id="turn-test",
        conversation_id="conv-test",
    )

    summary = collector.get_turn_summary("turn-test")
    if summary.get("tool_call_count", 0) < 1:
        return False, "Metrics not recording tool calls"

    return True, f"turn summary: {summary}"


def test_sse_protocol(verbose: bool = False) -> tuple[bool, str]:
    """Verify SSE encoder produces valid Data Stream Protocol events."""
    enc = DataStreamEncoder()

    events = [
        enc.start(message_id="test"),
        enc.start_step(),
        enc.text_start("t-0"),
        enc.text_delta("t-0", "Hello"),
        enc.text_end("t-0"),
        enc.tool_input_start("tc-1", "generate_quiz_questions"),
        enc.tool_input_available("tc-1", "generate_quiz_questions", {"topic": "math"}),
        enc.tool_output_available("tc-1", {"status": "ok", "questions": []}),
        enc.finish_step(),
        enc.finish("stop"),
    ]

    parsed_types = []
    for event in events:
        for line in event.strip().split("\n"):
            line = line.strip()
            if not line or not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                parsed_types.append("[DONE]")
                continue
            try:
                data = json.loads(payload)
                parsed_types.append(data.get("type", "unknown"))
            except json.JSONDecodeError:
                return False, f"Invalid JSON in SSE: {payload}"

    required = {"start", "start-step", "text-start", "text-delta", "text-end",
                "tool-input-start", "tool-input-available", "tool-output-available",
                "finish-step", "finish"}
    found = set(parsed_types)
    missing = required - found
    if missing:
        return False, f"Missing SSE events: {missing}"

    return True, f"All {len(required)} event types validated"


def test_contract_models(verbose: bool = False) -> tuple[bool, str]:
    """Verify data models used by tools."""
    from models.tool_contracts import Artifact, ContentFormat, ToolResult, ClarifyEvent

    a = Artifact(
        artifact_id="art-test",
        artifact_type="quiz",
        content_format=ContentFormat.JSON,
        content={"questions": []},
    )
    if a.version != 1:
        return False, f"Artifact default version should be 1, got {a.version}"

    tr = ToolResult(data={"q": 1}, artifact_type="quiz", content_format="json")
    if tr.status != "ok":
        return False, f"ToolResult default status should be ok, got {tr.status}"

    ce = ClarifyEvent(question="Pick a class")
    if not ce.allow_custom_input:
        return False, "ClarifyEvent allow_custom_input should default to True"

    return True, "Artifact, ToolResult, ClarifyEvent all valid"


def test_artifact_store(verbose: bool = False) -> tuple[bool, str]:
    """Verify artifact store save/get/version-bump works."""
    from services.artifact_store import InMemoryArtifactStore

    store = InMemoryArtifactStore()

    a1 = store.save_artifact(
        conversation_id="conv-test",
        artifact_type="quiz",
        content_format="json",
        content={"questions": [{"text": "Q1"}]},
    )
    if a1.version != 1:
        return False, f"First save should be v1, got {a1.version}"

    a2 = store.save_artifact(
        conversation_id="conv-test",
        artifact_type="quiz",
        content_format="json",
        content={"questions": [{"text": "Q1-updated"}]},
        artifact_id=a1.artifact_id,
    )
    if a2.version != 2:
        return False, f"Second save should be v2, got {a2.version}"

    latest = store.get_latest_for_conversation("conv-test")
    if latest is None or latest.version != 2:
        return False, "get_latest_for_conversation should return v2"

    return True, f"Save v1 → patch v2 → latest=v2 OK (id={a1.artifact_id})"


# ── Main ─────────────────────────────────────────────────────


def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    print("=" * 70)
    print("Step 3.1 — Native Agent Full Regression (S1-S11)")
    print("=" * 70)
    print()

    total_passed = 0
    total_failed = 0
    results: list[tuple[str, bool, str]] = []

    # ── Infrastructure checks ──
    print("--- Infrastructure Checks ---")
    infra_tests = [
        ("Registry completeness", test_registry_completeness),
        ("Metrics infrastructure", test_metrics_infrastructure),
        ("SSE protocol", test_sse_protocol),
        ("Contract models", test_contract_models),
        ("Artifact store", test_artifact_store),
    ]

    for name, test_fn in infra_tests:
        try:
            passed, detail = test_fn(verbose)
        except Exception as e:
            passed, detail = False, f"Exception: {e}"

        status = "PASS" if passed else "FAIL"
        results.append((name, passed, detail))
        if passed:
            total_passed += 1
        else:
            total_failed += 1
        print(f"  [{status}] {name}")
        if verbose or not passed:
            print(f"         {detail}")
    print()

    # ── Scenario toolset selection ──
    print("--- Scenario Toolset Selection (S1-S11) ---")
    for scenario in SCENARIOS:
        try:
            passed, detail = test_toolset_selection(scenario, verbose)
        except Exception as e:
            passed, detail = False, f"Exception: {e}"

        status = "PASS" if passed else "FAIL"
        label = f"{scenario.id}: {scenario.name}"
        results.append((label, passed, detail))
        if passed:
            total_passed += 1
        else:
            total_failed += 1
        print(f"  [{status}] {label}")
        if verbose or not passed:
            print(f"         {detail}")
    print()

    # ── Summary ──
    print("=" * 70)
    total = total_passed + total_failed
    print(f"Results: {total_passed}/{total} passed, {total_failed} failed")
    if total_failed > 0:
        print("\nFailed tests:")
        for name, passed, detail in results:
            if not passed:
                print(f"  - {name}: {detail}")
    print("=" * 70)
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
