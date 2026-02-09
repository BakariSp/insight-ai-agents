"""Phase-1 quiz convergence acceptance (multi-run statistical validation)."""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import sys

from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from main import app


REQUEST_BODY = {
    "message": "请出5道一元二次方程选择题，附简短解析。",
    "language": "zh-CN",
    "teacherId": "t-phase1-acceptance",
}

ROUNDS_PER_MODE = 10
MAX_REGRESSION_PCT = 20.0
MIN_SUCCESS_RATE = 0.95


@dataclass
class RunResult:
    mode: str
    round_idx: int
    success: bool
    http_status: int
    ttfq_ms: float
    total_ms: float
    question_count: int
    quiz_complete: bool
    action_events: list[dict[str, Any]]
    fallback_detected: bool
    error: str | None


@dataclass
class ModeSummary:
    mode: str
    rounds: int
    success_rate: float
    fallback_rate: float
    ttfq_p50_ms: float
    ttfq_p95_ms: float
    total_p50_ms: float
    total_p95_ms: float
    avg_question_count: float


def _set_flags(mode: str) -> None:
    if mode == "legacy_skill":
        os.environ["AGENT_UNIFIED_ENABLED"] = "false"
        os.environ["AGENT_UNIFIED_QUIZ_ENABLED"] = "false"
    elif mode == "unified_agent":
        os.environ["AGENT_UNIFIED_ENABLED"] = "true"
        os.environ["AGENT_UNIFIED_QUIZ_ENABLED"] = "true"
    else:
        raise ValueError(f"unknown mode={mode}")
    get_settings.cache_clear()


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[94]


async def _run_one(mode: str, round_idx: int) -> RunResult:
    _set_flags(mode)
    start = time.perf_counter()
    first_question = None
    question_count = 0
    quiz_complete = False
    error: str | None = None
    http_status = 0
    action_events: list[dict[str, Any]] = []

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=240.0) as client:
        try:
            async with client.stream("POST", "/api/conversation/stream", json=REQUEST_BODY) as resp:
                http_status = resp.status_code
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw == "[DONE]":
                        break
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type")
                    if event_type == "data-action":
                        data = event.get("data", {})
                        if isinstance(data, dict):
                            action_events.append(data)
                    elif event_type == "data-quiz-question":
                        question_count += 1
                        if first_question is None:
                            first_question = time.perf_counter()
                    elif event_type == "data-quiz-complete":
                        quiz_complete = True
                    elif event_type == "error":
                        error = event.get("errorText", "stream_error")
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"

    end = time.perf_counter()
    ttfq_ms = (first_question - start) * 1000 if first_question is not None else 0.0
    total_ms = (end - start) * 1000

    success = http_status == 200 and quiz_complete and question_count > 0 and error is None
    fallback_detected = False
    if mode == "unified_agent":
        has_unified_action = any(a.get("orchestrator") == "unified_agent" for a in action_events)
        has_legacy_action = any(a.get("action") == "quiz_generate" and "orchestrator" not in a for a in action_events)
        fallback_detected = has_unified_action and has_legacy_action

    return RunResult(
        mode=mode,
        round_idx=round_idx,
        success=success,
        http_status=http_status,
        ttfq_ms=ttfq_ms,
        total_ms=total_ms,
        question_count=question_count,
        quiz_complete=quiz_complete,
        action_events=action_events,
        fallback_detected=fallback_detected,
        error=error,
    )


def _summarize(mode: str, results: list[RunResult]) -> ModeSummary:
    ttfq_values = [r.ttfq_ms for r in results if r.success and r.ttfq_ms > 0]
    total_values = [r.total_ms for r in results if r.success and r.total_ms > 0]
    success_rate = sum(1 for r in results if r.success) / max(1, len(results))
    fallback_rate = sum(1 for r in results if r.fallback_detected) / max(1, len(results))
    avg_q = sum(r.question_count for r in results) / max(1, len(results))
    return ModeSummary(
        mode=mode,
        rounds=len(results),
        success_rate=success_rate,
        fallback_rate=fallback_rate,
        ttfq_p50_ms=statistics.median(ttfq_values) if ttfq_values else 0.0,
        ttfq_p95_ms=_p95(ttfq_values),
        total_p50_ms=statistics.median(total_values) if total_values else 0.0,
        total_p95_ms=_p95(total_values),
        avg_question_count=avg_q,
    )


def _build_markdown(
    legacy: ModeSummary,
    unified: ModeSummary,
    legacy_runs: list[RunResult],
    unified_runs: list[RunResult],
) -> str:
    reg_p50 = ((unified.ttfq_p50_ms - legacy.ttfq_p50_ms) / legacy.ttfq_p50_ms * 100) if legacy.ttfq_p50_ms else 0.0
    reg_p95 = ((unified.ttfq_p95_ms - legacy.ttfq_p95_ms) / legacy.ttfq_p95_ms * 100) if legacy.ttfq_p95_ms else 0.0

    pass_success = unified.success_rate >= min(MIN_SUCCESS_RATE, legacy.success_rate)
    pass_latency = reg_p50 <= MAX_REGRESSION_PCT and reg_p95 <= MAX_REGRESSION_PCT
    overall = pass_success and pass_latency

    lines: list[str] = []
    lines.append("# Phase 1 Quiz 多轮验收报告")
    lines.append("")
    lines.append(f"- 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 每模式轮次: {ROUNDS_PER_MODE}")
    lines.append(f"- 请求: `{REQUEST_BODY['message']}`")
    lines.append("")
    lines.append("## 汇总指标")
    lines.append("")
    lines.append("| 模式 | 成功率 | fallback率 | TTFQ P50(ms) | TTFQ P95(ms) | Total P50(ms) | Total P95(ms) | 平均题数 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for s in (legacy, unified):
        lines.append(
            f"| {s.mode} | {s.success_rate:.0%} | {s.fallback_rate:.0%} | "
            f"{s.ttfq_p50_ms:.0f} | {s.ttfq_p95_ms:.0f} | {s.total_p50_ms:.0f} | "
            f"{s.total_p95_ms:.0f} | {s.avg_question_count:.2f} |"
        )
    lines.append("")
    lines.append("## 对比判定")
    lines.append("")
    lines.append(f"- TTFQ P50 劣化: `{reg_p50:+.1f}%`（阈值 <= {MAX_REGRESSION_PCT:.0f}%）")
    lines.append(f"- TTFQ P95 劣化: `{reg_p95:+.1f}%`（阈值 <= {MAX_REGRESSION_PCT:.0f}%）")
    lines.append(f"- Unified 成功率: `{unified.success_rate:.0%}`（阈值 >= {MIN_SUCCESS_RATE:.0%}）")
    lines.append(f"- 结论: `{'PASS' if overall else 'FAIL'}`")
    lines.append("")
    lines.append("## 明细")
    lines.append("")
    for title, rows in (("legacy_skill", legacy_runs), ("unified_agent", unified_runs)):
        lines.append(f"### {title}")
        lines.append("| 轮次 | success | ttfq_ms | total_ms | question_count | fallback | error |")
        lines.append("|---:|---|---:|---:|---:|---|---|")
        for r in rows:
            lines.append(
                f"| {r.round_idx} | {r.success} | {r.ttfq_ms:.0f} | {r.total_ms:.0f} | "
                f"{r.question_count} | {r.fallback_detected} | {r.error or ''} |"
            )
        lines.append("")
    return "\n".join(lines)


async def main() -> None:
    legacy_runs: list[RunResult] = []
    unified_runs: list[RunResult] = []

    for i in range(1, ROUNDS_PER_MODE + 1):
        legacy_runs.append(await _run_one("legacy_skill", i))
    for i in range(1, ROUNDS_PER_MODE + 1):
        unified_runs.append(await _run_one("unified_agent", i))

    legacy_summary = _summarize("legacy_skill", legacy_runs)
    unified_summary = _summarize("unified_agent", unified_runs)

    md_text = _build_markdown(legacy_summary, unified_summary, legacy_runs, unified_runs)
    json_obj = {
        "generated_at": datetime.now().isoformat(),
        "request": REQUEST_BODY,
        "rounds_per_mode": ROUNDS_PER_MODE,
        "thresholds": {
            "max_regression_pct": MAX_REGRESSION_PCT,
            "min_success_rate": MIN_SUCCESS_RATE,
        },
        "summary": {
            "legacy_skill": asdict(legacy_summary),
            "unified_agent": asdict(unified_summary),
        },
        "runs": {
            "legacy_skill": [asdict(r) for r in legacy_runs],
            "unified_agent": [asdict(r) for r in unified_runs],
        },
    }

    out_dir = Path("docs") / "testing"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "phase1-quiz-convergence-acceptance.md"
    json_path = out_dir / "phase1-quiz-convergence-acceptance.json"
    md_path.write_text(md_text, encoding="utf-8")
    json_path.write_text(json.dumps(json_obj, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] markdown: {md_path}")
    print(f"[OK] json: {json_path}")
    print(
        f"[summary] legacy success={legacy_summary.success_rate:.0%} "
        f"ttfq_p50={legacy_summary.ttfq_p50_ms:.0f} ttfq_p95={legacy_summary.ttfq_p95_ms:.0f}"
    )
    print(
        f"[summary] unified success={unified_summary.success_rate:.0%} fallback={unified_summary.fallback_rate:.0%} "
        f"ttfq_p50={unified_summary.ttfq_p50_ms:.0f} ttfq_p95={unified_summary.ttfq_p95_ms:.0f}"
    )


if __name__ == "__main__":
    asyncio.run(main())
