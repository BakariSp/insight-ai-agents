"""Diagnostic: API connectivity + tool calling sanity check for all models.

For each model, runs 4 probes:
  1. Chinese tool call  — "帮我出5道数学选择题" (should call generate_quiz_questions)
  2. English tool call  — "Generate 5 math quiz questions" (same intent, English)
  3. Chinese no-tool    — "你好" (should NOT call tools)
  4. English no-tool    — "Hello" (should NOT call tools)

This tells us:
  - Is the API key valid / model reachable?
  - Does tool calling work at all for this model/provider?
  - Is failure Chinese-specific or universal?
  - Raw output text to see what the model actually produces

Usage:
    cd insight-ai-agent
    python tests/test_tool_calling_qa/run_diagnostic.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import os
import time
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("NATIVE_AGENT_ENABLED", "true")

# Fix Windows GBK encoding for console output
if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "").startswith("gbk"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import tools.native_tools  # noqa: F401

from tests.test_tool_calling_qa.conftest import (
    MODELS_TO_TEST,
    run_agent_phase1,
    _tool_registry,
    MOCK_RETURNS,
    QAResult,
)


def _mock_tool_func(tool_name: str, mock_return: dict):
    async def _mock(ctx, **kwargs):
        return mock_return
    _mock.__name__ = tool_name
    _mock.__qualname__ = tool_name
    return _mock


def setup_mocks():
    for name, rt in _tool_registry.items():
        mock_return = MOCK_RETURNS.get(name, {"status": "ok"})
        rt.func = _mock_tool_func(name, mock_return)


# ── Probes ──

PROBES = [
    {
        "id": "zh-tool",
        "message": "帮我出5道数学选择题",
        "expect_tool": True,
        "expected_tools": {"generate_quiz_questions", "ask_clarification"},
        "label": "中文-应调工具",
    },
    {
        "id": "en-tool",
        "message": "Generate 5 math multiple choice quiz questions for my students",
        "expect_tool": True,
        "expected_tools": {"generate_quiz_questions", "ask_clarification"},
        "label": "English-should call tool",
    },
    {
        "id": "zh-chat",
        "message": "你好",
        "expect_tool": False,
        "expected_tools": set(),
        "label": "中文-不应调工具",
    },
    {
        "id": "en-chat",
        "message": "Hello",
        "expect_tool": False,
        "expected_tools": set(),
        "label": "English-should NOT call tool",
    },
]


@dataclass
class ProbeResult:
    model_label: str
    probe_id: str
    probe_label: str
    message: str
    expect_tool: bool
    # results
    tool_calls_made: list[str] = field(default_factory=list)
    output_text: str = ""
    error: str = ""
    latency_ms: float = 0
    verdict: str = ""  # PASS / FAIL / ERROR / API_DEAD


async def run_probe(model_info: dict, probe: dict) -> ProbeResult:
    model_id = model_info["id"]
    label = model_info["label"]

    pr = ProbeResult(
        model_label=label,
        probe_id=probe["id"],
        probe_label=probe["label"],
        message=probe["message"],
        expect_tool=probe["expect_tool"],
    )

    try:
        result = await run_agent_phase1(probe["message"], model_id)
        pr.tool_calls_made = result.tool_names_list
        pr.output_text = result.output_text
        pr.error = result.error
        pr.latency_ms = result.latency_ms

        if result.error:
            pr.verdict = "ERROR"
        elif probe["expect_tool"]:
            if result.called_any_tool:
                if result.tool_names & probe["expected_tools"]:
                    pr.verdict = "PASS"
                else:
                    pr.verdict = "WRONG_TOOL"
            else:
                pr.verdict = "NO_TOOL_CALL"
        else:
            # Should not call tools
            non_clarify = [t for t in result.tool_names_list if t != "ask_clarification"]
            if not non_clarify:
                pr.verdict = "PASS"
            else:
                pr.verdict = "UNEXPECTED_TOOL"

    except Exception as e:
        pr.error = f"{type(e).__name__}: {e}"
        pr.verdict = "API_DEAD"
        pr.latency_ms = 0

    return pr


async def run_all_probes(model_info: dict) -> list[ProbeResult]:
    results = []
    for probe in PROBES:
        pr = await run_probe(model_info, probe)
        results.append(pr)

        # Print immediately
        icon = {
            "PASS": "✓", "FAIL": "✗", "ERROR": "⚠",
            "API_DEAD": "☠", "NO_TOOL_CALL": "∅",
            "WRONG_TOOL": "⚡", "UNEXPECTED_TOOL": "!",
        }.get(pr.verdict, "?")

        tools_str = ", ".join(pr.tool_calls_made) if pr.tool_calls_made else "(none)"
        out_preview = pr.output_text[:120].replace("\n", "↵") if pr.output_text else "(empty)"
        err_str = f" ERR={pr.error[:80]}" if pr.error else ""

        print(f"  [{icon}] {pr.model_label:>14} | {pr.probe_id:<8} | {pr.verdict:<14} | "
              f"tools=[{tools_str}] | {pr.latency_ms:.0f}ms{err_str}")
        if pr.verdict not in ("PASS",):
            print(f"      output: {out_preview}")

    return results


def generate_report(all_results: dict[str, list[ProbeResult]]) -> str:
    """Generate plain-text diagnostic report."""
    lines = []
    lines.append("=" * 90)
    lines.append("  TOOL CALLING DIAGNOSTIC REPORT")
    lines.append("=" * 90)

    # Summary table
    lines.append("")
    header = f"  {'Model':>16} | {'zh-tool':>10} | {'en-tool':>10} | {'zh-chat':>10} | {'en-chat':>10} | {'Diagnosis':>20}"
    lines.append(header)
    lines.append("  " + "-" * 86)

    for label, results in all_results.items():
        verdicts = {r.probe_id: r.verdict for r in results}
        zh_tool = verdicts.get("zh-tool", "?")
        en_tool = verdicts.get("en-tool", "?")
        zh_chat = verdicts.get("zh-chat", "?")
        en_chat = verdicts.get("en-chat", "?")

        # Diagnosis
        if zh_tool in ("API_DEAD", "ERROR") and en_tool in ("API_DEAD", "ERROR"):
            diagnosis = "API DEAD"
        elif zh_tool == "NO_TOOL_CALL" and en_tool == "NO_TOOL_CALL":
            diagnosis = "TOOL CALLING BROKEN"
        elif zh_tool == "NO_TOOL_CALL" and en_tool == "PASS":
            diagnosis = "CHINESE PROMPT ISSUE"
        elif zh_tool == "PASS" and en_tool == "NO_TOOL_CALL":
            diagnosis = "ENGLISH PROMPT ISSUE"
        elif zh_tool == "PASS" and en_tool == "PASS":
            diagnosis = "ALL GOOD"
        elif zh_tool == "WRONG_TOOL" or en_tool == "WRONG_TOOL":
            diagnosis = "WRONG TOOL SELECTION"
        else:
            diagnosis = f"MIXED ({zh_tool}/{en_tool})"

        lines.append(
            f"  {label:>16} | {zh_tool:>10} | {en_tool:>10} | {zh_chat:>10} | {en_chat:>10} | {diagnosis:>20}"
        )

    lines.append("")

    # Detailed per-model output
    lines.append("=" * 90)
    lines.append("  DETAILED OUTPUT")
    lines.append("=" * 90)

    for label, results in all_results.items():
        lines.append(f"\n  ── {label} ──")
        for r in results:
            lines.append(f"    [{r.probe_id}] {r.verdict}")
            lines.append(f"      message: {r.message}")
            if r.tool_calls_made:
                lines.append(f"      tools:   {', '.join(r.tool_calls_made)}")
            if r.output_text:
                preview = r.output_text[:200].replace("\n", "↵")
                lines.append(f"      output:  {preview}")
            if r.error:
                lines.append(f"      error:   {r.error[:200]}")
            lines.append(f"      latency: {r.latency_ms:.0f}ms")

    lines.append("")
    return "\n".join(lines)


async def main():
    setup_mocks()

    models = MODELS_TO_TEST
    print(f"\n{'='*90}")
    print(f"  TOOL CALLING DIAGNOSTIC — {len(models)} models × {len(PROBES)} probes = {len(models) * len(PROBES)} tests")
    print(f"{'='*90}")
    print(f"  Models:")
    for m in models:
        print(f"    {m['label']:>16} -> {m['id']}")
    print()

    all_results: dict[str, list[ProbeResult]] = {}

    # Run models concurrently, probes sequentially per model
    async def _run_model(m):
        results = await run_all_probes(m)
        return m["label"], results

    tasks = [_run_model(m) for m in models]
    completed = await asyncio.gather(*tasks, return_exceptions=True)

    for item in completed:
        if isinstance(item, Exception):
            print(f"  MODEL ERROR: {item}")
            continue
        label, results = item
        all_results[label] = results

    # Generate and save report
    report = generate_report(all_results)
    print(report)

    report_path = Path(__file__).resolve().parents[2] / "diagnostic_report.txt"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n  Report saved: {report_path}\n")


if __name__ == "__main__":
    asyncio.run(main())
