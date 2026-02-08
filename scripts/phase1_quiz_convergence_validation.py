"""Phase-1 quiz convergence validation (legacy vs unified agent).

Runs real /api/conversation/stream requests and records:
- Time to first quiz question (TTFQ)
- Total duration
- SSE compatibility for frontend
- Tool-call evidence in unified mode
- Basic question-structure quality
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from main import app


TEST_MESSAGE = "请出5道一元二次方程选择题，附简短解析。"
LATENCY_REGRESSION_THRESHOLD_PCT = 20.0
TEST_BODY = {
    "message": TEST_MESSAGE,
    "language": "zh-CN",
    "teacherId": "t-phase1-validation",
}


@dataclass
class RunMetrics:
    mode: str
    success: bool = False
    http_status: int = 0
    total_ms: float = 0.0
    ttfq_ms: float = 0.0
    question_count: int = 0
    quiz_complete: bool = False
    action: str | None = None
    orchestrator: str | None = None
    event_types: list[str] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    quality_pass_count: int = 0
    quality_total_count: int = 0
    quality_pass_rate: float = 0.0
    error: str | None = None


def _set_unified_flags(*, unified_enabled: bool, quiz_enabled: bool) -> None:
    os.environ["AGENT_UNIFIED_ENABLED"] = "true" if unified_enabled else "false"
    os.environ["AGENT_UNIFIED_QUIZ_ENABLED"] = "true" if quiz_enabled else "false"
    get_settings.cache_clear()


def _is_question_structurally_valid(question: dict[str, Any]) -> bool:
    if not isinstance(question, dict):
        return False
    q_text = str(question.get("question", "")).strip()
    q_type = str(question.get("questionType", "")).strip().upper()
    if not q_text or not q_type:
        return False

    if q_type == "SINGLE_CHOICE":
        options = question.get("options")
        answer = str(question.get("correctAnswer", "")).strip()
        return isinstance(options, list) and len(options) >= 2 and bool(answer)

    return True


async def _run_once(mode: str) -> RunMetrics:
    if mode == "legacy_skill":
        _set_unified_flags(unified_enabled=False, quiz_enabled=False)
    elif mode == "unified_agent":
        _set_unified_flags(unified_enabled=True, quiz_enabled=True)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    metrics = RunMetrics(mode=mode)
    start = time.perf_counter()
    first_question_at: float | None = None

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        timeout=240.0,
    ) as client:
        try:
            async with client.stream(
                "POST",
                "/api/conversation/stream",
                json=TEST_BODY,
            ) as resp:
                metrics.http_status = resp.status_code
                if resp.status_code != 200:
                    metrics.error = f"http_status={resp.status_code}"
                    return metrics

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        break

                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type")
                    if isinstance(event_type, str):
                        metrics.event_types.append(event_type)

                    if event_type == "data-action":
                        data = event.get("data", {})
                        if isinstance(data, dict):
                            metrics.action = str(data.get("action")) if data.get("action") is not None else None
                            metrics.orchestrator = (
                                str(data.get("orchestrator"))
                                if data.get("orchestrator") is not None
                                else None
                            )

                    if event_type == "data-tool-progress":
                        data = event.get("data", {})
                        if isinstance(data, dict):
                            tool = data.get("tool")
                            if isinstance(tool, str) and tool:
                                metrics.tool_calls.append(tool)

                    if event_type == "data-quiz-question":
                        if first_question_at is None:
                            first_question_at = time.perf_counter()
                        metrics.question_count += 1
                        question = event.get("data", {}).get("question", {})
                        metrics.quality_total_count += 1
                        if isinstance(question, dict) and _is_question_structurally_valid(question):
                            metrics.quality_pass_count += 1

                    if event_type == "data-quiz-complete":
                        metrics.quiz_complete = True

                    if event_type == "error":
                        metrics.error = event.get("errorText", "stream_error")

        except Exception as exc:  # noqa: BLE001
            metrics.error = f"{type(exc).__name__}: {exc}"

    end = time.perf_counter()
    metrics.total_ms = (end - start) * 1000
    metrics.ttfq_ms = ((first_question_at - start) * 1000) if first_question_at else 0.0
    if metrics.quality_total_count > 0:
        metrics.quality_pass_rate = metrics.quality_pass_count / metrics.quality_total_count

    required_events = {"data-action", "data-quiz-question", "data-quiz-complete"}
    metrics.success = (
        metrics.http_status == 200
        and metrics.quiz_complete
        and metrics.question_count > 0
        and required_events.issubset(set(metrics.event_types))
        and (metrics.error is None)
    )
    return metrics


def _build_markdown_report(results: list[RunMetrics]) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []
    lines.append("# Phase 1 Quiz 收敛验收报告")
    lines.append("")
    lines.append(f"- 生成时间: {generated_at}")
    lines.append(f"- 测试请求: `{TEST_MESSAGE}`")
    lines.append("")
    lines.append("## 结果总览")
    lines.append("")
    lines.append("| 模式 | 成功 | 首题时延(ms) | 总时长(ms) | 题目数 | 结构质量通过率 | action | orchestrator |")
    lines.append("|---|---:|---:|---:|---:|---:|---|---|")
    for r in results:
        lines.append(
            f"| {r.mode} | {'Y' if r.success else 'N'} | "
            f"{r.ttfq_ms:.0f} | {r.total_ms:.0f} | {r.question_count} | "
            f"{r.quality_pass_rate:.0%} | {r.action or ''} | {r.orchestrator or ''} |"
        )

    lines.append("")
    lines.append("## 前端协议兼容性")
    lines.append("")
    for r in results:
        lines.append(f"### {r.mode}")
        lines.append(f"- 事件: `{', '.join(sorted(set(r.event_types)))}`")
        lines.append(f"- 工具调用: `{', '.join(r.tool_calls) if r.tool_calls else '(none)'}`")
        lines.append(f"- 错误: `{r.error or '(none)'}`")
        lines.append("")

    if len(results) >= 2:
        legacy = next((x for x in results if x.mode == "legacy_skill"), None)
        unified = next((x for x in results if x.mode == "unified_agent"), None)
        if legacy and unified and legacy.ttfq_ms > 0:
            delta = ((unified.ttfq_ms - legacy.ttfq_ms) / legacy.ttfq_ms) * 100
            lines.append("## 阶段1门槛判断")
            lines.append("")
            lines.append(
                f"- 首题时延变化: `{delta:+.1f}%`（门槛: 劣化 <= {LATENCY_REGRESSION_THRESHOLD_PCT:.0f}%）"
            )
            lines.append(
                f"- Quiz 成功率: `legacy={legacy.success}, unified={unified.success}`"
            )
            pass_latency = delta <= LATENCY_REGRESSION_THRESHOLD_PCT
            pass_quality = unified.quality_pass_rate >= legacy.quality_pass_rate
            lines.append(
                f"- 结论: `{'PASS' if pass_latency and pass_quality and unified.success else 'NEEDS_REVIEW'}`"
            )
            lines.append("")

    return "\n".join(lines)


async def main() -> None:
    out_dir = Path("docs") / "testing"
    out_dir.mkdir(parents=True, exist_ok=True)

    modes = ["legacy_skill", "unified_agent"]
    results = []
    for mode in modes:
        result = await _run_once(mode)
        results.append(result)
        await asyncio.sleep(1)

    report_md = _build_markdown_report(results)
    report_json = {
        "generated_at": datetime.now().isoformat(),
        "request": TEST_BODY,
        "results": [asdict(r) for r in results],
    }

    md_path = out_dir / "phase1-quiz-convergence-validation.md"
    json_path = out_dir / "phase1-quiz-convergence-validation.json"
    md_path.write_text(report_md, encoding="utf-8")
    json_path.write_text(
        json.dumps(report_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[OK] markdown: {md_path}")
    print(f"[OK] json: {json_path}")
    for r in results:
        print(
            f"[{r.mode}] success={r.success} ttfq_ms={r.ttfq_ms:.0f} "
            f"total_ms={r.total_ms:.0f} questions={r.question_count} "
            f"quality={r.quality_pass_rate:.0%} action={r.action} "
            f"orchestrator={r.orchestrator} tools={r.tool_calls}"
        )


if __name__ == "__main__":
    asyncio.run(main())
