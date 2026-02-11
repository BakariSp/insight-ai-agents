"""Re-run D2+D8 comparison for reconfigured models.

Targets GPT-5 and Gemini models that were previously failing
due to API issues (enable_thinking param / quota exhaustion).

Usage:
    cd insight-ai-agent
    python tests/test_tool_calling_qa/run_revalidation.py
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

# Fix Windows GBK encoding (line_buffering=True to avoid swallowing -u flag)
if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "").startswith("gbk"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

import tools.native_tools  # noqa: F401

from tests.test_tool_calling_qa.conftest import (
    MODELS_TO_TEST,
    run_agent_phase1,
    build_injected_prompt,
    _tool_registry,
    MOCK_RETURNS,
)
from tests.test_tool_calling_qa.test_d2_boundary import ALL_BOUNDARY_CASES
from tests.test_tool_calling_qa.test_d8_pressure import (
    VERBOSE_INTERACTIVE,
    VERBOSE_QUIZ,
    VERBOSE_PPT,
    INJECTION_LENGTHS,
    INJECTION_MESSAGE,
)


# Target GPT + Gemini models (reconfigured, previously had API issues)
TARGET_MODELS = {"gpt-5.2", "gpt-5-mini", "gemini-3-pro", "gemini-3-flash"}
VALID_MODELS = [m for m in MODELS_TO_TEST if m["label"] in TARGET_MODELS]

REPORT_PATH = Path(__file__).resolve().parents[2] / "revalidation_report.txt"


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


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    tools: list[str]
    detail: str
    latency_ms: float
    output_preview: str = ""
    error: str = ""


async def run_d2_for_model(model_id: str, label: str) -> list[CaseResult]:
    results = []
    for case in ALL_BOUNDARY_CASES:
        try:
            result = await run_agent_phase1(case.message, model_id)
            tools = result.tool_names_list

            if case.should_call_tool:
                passed = result.called_any_tool and (
                    not case.expected_tools
                    or bool(result.tool_names & set(case.expected_tools))
                )
                detail = f"tools={tools}" if passed else f"MISS tools={tools} expected_any={case.expected_tools}"
            else:
                non_clarify = [t for t in tools if t != "ask_clarification"]
                passed = len(non_clarify) == 0
                detail = "clean" if passed else f"TRIGGERED {tools}"

            cr = CaseResult(
                case_id=case.id, passed=passed, tools=tools,
                detail=detail, latency_ms=result.latency_ms,
                output_preview=result.output_text[:150].replace("\n", " "),
                error=result.error,
            )
        except Exception as e:
            cr = CaseResult(
                case_id=case.id, passed=False, tools=[],
                detail=f"EXCEPTION", latency_ms=0,
                error=str(e)[:100],
            )

        tag = "PASS" if cr.passed else "FAIL"
        print(f"  [{label:>14}] {cr.case_id:<10} [{tag}] {cr.detail} ({cr.latency_ms:.0f}ms)")
        results.append(cr)
    return results


async def run_d8_for_model(model_id: str, label: str) -> list[CaseResult]:
    results = []

    # D8a: Verbose interactive
    for tag, message in VERBOSE_INTERACTIVE:
        case_id = f"d8a-html-{tag}"
        try:
            result = await run_agent_phase1(message, model_id)
            passed = "generate_interactive_html" in result.tool_names
            cr = CaseResult(
                case_id=case_id, passed=passed, tools=result.tool_names_list,
                detail=f"{len(message)}ch", latency_ms=result.latency_ms,
                output_preview=result.output_text[:100].replace("\n", " "),
                error=result.error,
            )
        except Exception as e:
            cr = CaseResult(case_id=case_id, passed=False, tools=[], detail="EXCEPTION",
                            latency_ms=0, error=str(e)[:100])
        tag_str = "PASS" if cr.passed else "FAIL"
        print(f"  [{label:>14}] {cr.case_id:<14} [{tag_str}] tools={cr.tools} ({cr.latency_ms:.0f}ms)")
        results.append(cr)

    # D8a: Verbose quiz
    for tag, message in VERBOSE_QUIZ:
        case_id = f"d8a-quiz-{tag}"
        try:
            result = await run_agent_phase1(message, model_id)
            passed = "generate_quiz_questions" in result.tool_names
            cr = CaseResult(
                case_id=case_id, passed=passed, tools=result.tool_names_list,
                detail=f"{len(message)}ch", latency_ms=result.latency_ms,
                output_preview=result.output_text[:100].replace("\n", " "),
                error=result.error,
            )
        except Exception as e:
            cr = CaseResult(case_id=case_id, passed=False, tools=[], detail="EXCEPTION",
                            latency_ms=0, error=str(e)[:100])
        tag_str = "PASS" if cr.passed else "FAIL"
        print(f"  [{label:>14}] {cr.case_id:<14} [{tag_str}] tools={cr.tools} ({cr.latency_ms:.0f}ms)")
        results.append(cr)

    # D8a: Verbose PPT
    for tag, message in VERBOSE_PPT:
        case_id = f"d8a-ppt-{tag}"
        try:
            result = await run_agent_phase1(message, model_id)
            acceptable = {"propose_pptx_outline", "ask_clarification"}
            passed = bool(result.tool_names & acceptable)
            cr = CaseResult(
                case_id=case_id, passed=passed, tools=result.tool_names_list,
                detail=f"{len(message)}ch", latency_ms=result.latency_ms,
                output_preview=result.output_text[:100].replace("\n", " "),
                error=result.error,
            )
        except Exception as e:
            cr = CaseResult(case_id=case_id, passed=False, tools=[], detail="EXCEPTION",
                            latency_ms=0, error=str(e)[:100])
        tag_str = "PASS" if cr.passed else "FAIL"
        print(f"  [{label:>14}] {cr.case_id:<14} [{tag_str}] tools={cr.tools} ({cr.latency_ms:.0f}ms)")
        results.append(cr)

    # D8c: File injection
    for doc_chars in INJECTION_LENGTHS:
        case_id = f"d8c-{doc_chars}ch"
        try:
            user_prompt = build_injected_prompt(doc_chars, INJECTION_MESSAGE)
            result = await run_agent_phase1(INJECTION_MESSAGE, model_id, user_prompt=user_prompt)
            acceptable = {"generate_quiz_questions", "ask_clarification"}
            passed = bool(result.tool_names & acceptable)
            cr = CaseResult(
                case_id=case_id, passed=passed, tools=result.tool_names_list,
                detail=f"{doc_chars}doc", latency_ms=result.latency_ms,
                output_preview=result.output_text[:100].replace("\n", " "),
                error=result.error,
            )
            if result.error and ("timed out" in result.error.lower() or "connection" in result.error.lower()):
                cr.detail = f"INFRA_TIMEOUT {doc_chars}doc"
        except Exception as e:
            cr = CaseResult(case_id=case_id, passed=False, tools=[], detail=f"EXCEPTION {doc_chars}doc",
                            latency_ms=0, error=str(e)[:100])
        tag_str = "PASS" if cr.passed else "FAIL"
        print(f"  [{label:>14}] {cr.case_id:<14} [{tag_str}] tools={cr.tools} ({cr.latency_ms:.0f}ms)")
        results.append(cr)

    return results


def generate_report(
    all_d2: dict[str, list[CaseResult]],
    all_d8: dict[str, list[CaseResult]],
) -> str:
    lines = []
    lines.append("=" * 100)
    lines.append("  REVALIDATION REPORT — D2 + D8 (GPT + Gemini retest)")
    lines.append("=" * 100)

    # Overall ranking
    lines.append("\n  OVERALL RANKING:")
    lines.append(f"  {'Model':>16} | {'D2':>8} | {'D8':>8} | {'Total':>8} | {'Rate':>6} | {'Tier':>4}")
    lines.append("  " + "-" * 60)

    scores = []
    for label in all_d2:
        d2 = all_d2[label]
        d8 = all_d8.get(label, [])
        d2_pass = sum(1 for r in d2 if r.passed)
        d8_pass = sum(1 for r in d8 if r.passed)
        total = len(d2) + len(d8)
        total_pass = d2_pass + d8_pass
        rate = total_pass / total * 100 if total else 0
        tier = "S" if rate >= 85 else "A" if rate >= 70 else "B" if rate >= 55 else "C"
        scores.append((label, d2_pass, len(d2), d8_pass, len(d8), total_pass, total, rate, tier))

    scores.sort(key=lambda x: -x[7])
    for label, d2p, d2t, d8p, d8t, tp, tt, rate, tier in scores:
        lines.append(
            f"  {label:>16} | {d2p:>3}/{d2t:<4} | {d8p:>3}/{d8t:<4} | {tp:>3}/{tt:<4} | {rate:>5.0f}% | {tier:>4}"
        )

    # D2 detail
    lines.append(f"\n{'='*100}")
    lines.append("  D2: BOUNDARY CONFUSION — Detailed Results")
    lines.append(f"{'='*100}")

    # Per-case comparison
    all_cases = [c.id for c in ALL_BOUNDARY_CASES]
    header = f"  {'Case':<12} {'Type':<6}"
    for label in all_d2:
        header += f" {label:>14}"
    lines.append(header)
    lines.append("  " + "-" * (18 + 15 * len(all_d2)))

    for case in ALL_BOUNDARY_CASES:
        ctype = "TRAP" if not case.should_call_tool else "IMPL"
        row = f"  {case.id:<12} {ctype:<6}"
        for label in all_d2:
            match = [r for r in all_d2[label] if r.case_id == case.id]
            if match:
                r = match[0]
                status = "PASS" if r.passed else "FAIL"
                tools_short = ",".join(r.tools)[:12] if r.tools else "(none)"
                row += f" {status:>4} {tools_short:<9}"
            else:
                row += f" {'SKIP':>4}          "
        lines.append(row)

    # D2 failure detail
    lines.append(f"\n  D2 FAILURE DETAILS:")
    for label in all_d2:
        fails = [r for r in all_d2[label] if not r.passed]
        if fails:
            lines.append(f"\n  [{label}] — {len(fails)} failures:")
            for r in fails:
                lines.append(f"    {r.case_id}: tools={r.tools} | {r.output_preview[:100]}")

    # D8 detail
    lines.append(f"\n{'='*100}")
    lines.append("  D8: CONTEXT PRESSURE — Detailed Results")
    lines.append(f"{'='*100}")

    header = f"  {'Case':<16}"
    for label in all_d8:
        header += f" {label:>14}"
    lines.append(header)
    lines.append("  " + "-" * (16 + 15 * len(all_d8)))

    # Collect all D8 case IDs from first model
    first_label = list(all_d8.keys())[0] if all_d8 else None
    if first_label:
        for r in all_d8[first_label]:
            row = f"  {r.case_id:<16}"
            for label in all_d8:
                match = [x for x in all_d8[label] if x.case_id == r.case_id]
                if match:
                    x = match[0]
                    status = "PASS" if x.passed else "FAIL"
                    tools_short = ",".join(x.tools)[:12] if x.tools else "(none)"
                    row += f" {status:>4} {x.latency_ms:>6.0f}ms"
                else:
                    row += f" {'?':>4}         "
            lines.append(row)

    lines.append("")
    return "\n".join(lines)


async def main():
    setup_mocks()

    print(f"\n{'='*100}")
    print(f"  REVALIDATION — {len(VALID_MODELS)} target models: {TARGET_MODELS}")
    print(f"{'='*100}")
    for m in VALID_MODELS:
        print(f"    {m['label']:>16} -> {m['id']}")
    print()

    all_d2: dict[str, list[CaseResult]] = {}
    all_d8: dict[str, list[CaseResult]] = {}

    # Run all models concurrently
    async def _run_model(m):
        model_id = m["id"]
        label = m["label"]
        d2_results = await run_d2_for_model(model_id, label)
        d8_results = await run_d8_for_model(model_id, label)
        return label, d2_results, d8_results

    tasks = [_run_model(m) for m in VALID_MODELS]
    completed = await asyncio.gather(*tasks, return_exceptions=True)

    for item in completed:
        if isinstance(item, Exception):
            print(f"  MODEL ERROR: {item}")
            continue
        label, d2_results, d8_results = item
        all_d2[label] = d2_results
        all_d8[label] = d8_results

    # Generate report
    report = generate_report(all_d2, all_d8)
    print(report)

    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"\n  Report saved: {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
