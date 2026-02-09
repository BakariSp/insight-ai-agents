"""Phase2 live content-quality validation for unified agent flows.

Runs real `/api/conversation/stream` calls for:
- quiz
- ppt outline
- docx
- interactive content

Validates:
- Artifact presence and quality scoring
- Unified Agent protocol compliance (orchestrator, finish event, tool-progress)
- Retry health metrics (RetryNeeded / SoftRetryNeeded from captured logs)
- Quiz context-awareness (BUG-1 regression guard)

Outputs:
- docs/testing/phase2-live-content-quality-report.json
- docs/testing/phase2-live-content-quality-report.md
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

from config.settings import get_settings
from main import app
from services.java_client import get_java_client

# ---------------------------------------------------------------------------
# Log capture — intercept retry warnings from the unified agent loop
# ---------------------------------------------------------------------------

_RETRY_LOG_PREFIX_HARD = "[UnifiedAgent] terminal-state retry:"
_RETRY_LOG_PREFIX_SOFT = "[UnifiedAgent] soft validation retry:"
_RETRY_LOG_PREFIX_EXHAUSTED = "[UnifiedAgent] soft validation exhausted"


class _RetryLogCapture(logging.Handler):
    """Captures UnifiedAgent retry warnings emitted during a single scenario."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.hard_retries: list[str] = []
        self.soft_retries: list[str] = []
        self.exhausted: bool = False

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if _RETRY_LOG_PREFIX_HARD in msg:
            self.hard_retries.append(msg)
        elif _RETRY_LOG_PREFIX_SOFT in msg:
            self.soft_retries.append(msg)
        elif _RETRY_LOG_PREFIX_EXHAUSTED in msg:
            self.exhausted = True

    def summary(self) -> dict[str, Any]:
        return {
            "hard_retry_count": len(self.hard_retries),
            "soft_retry_count": len(self.soft_retries),
            "soft_retry_exhausted": self.exhausted,
            "retry_messages": self.hard_retries + self.soft_retries,
        }

    def reset(self) -> None:
        self.hard_retries.clear()
        self.soft_retries.clear()
        self.exhausted = False


# ---------------------------------------------------------------------------
# Expected artifact event mapping (mirrors agent_validation.py)
# ---------------------------------------------------------------------------

_EXPECTED_ARTIFACT_EVENTS: dict[str, set[str]] = {
    "quiz": {"data-quiz-question", "data-quiz-complete"},
    "ppt": {"data-pptx-outline", "data-file-ready"},
    "docx": {"data-file-ready"},
    "interactive": {"data-interactive-content"},
}


@dataclass
class Scenario:
    name: str
    message: str
    expected: str


# ---------------------------------------------------------------------------
# Protocol compliance checks
# ---------------------------------------------------------------------------

@dataclass
class ProtocolCheck:
    """Unified Agent protocol compliance result for a single scenario."""
    has_finish_event: bool = False
    finish_reason: str | None = None
    has_data_action: bool = False
    orchestrator: str | None = None
    orchestrator_ok: bool = False
    has_tool_progress: bool = False
    tool_progress_count: int = 0
    has_expected_artifact_events: bool = False
    missing_artifact_events: list[str] = field(default_factory=list)
    used_legacy_path: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_finish_event": self.has_finish_event,
            "finish_reason": self.finish_reason,
            "has_data_action": self.has_data_action,
            "orchestrator": self.orchestrator,
            "orchestrator_ok": self.orchestrator_ok,
            "has_tool_progress": self.has_tool_progress,
            "tool_progress_count": self.tool_progress_count,
            "has_expected_artifact_events": self.has_expected_artifact_events,
            "missing_artifact_events": self.missing_artifact_events,
            "used_legacy_path": self.used_legacy_path,
        }

    @property
    def passed(self) -> bool:
        return (
            self.has_finish_event
            and self.orchestrator_ok
            and self.has_expected_artifact_events
            and not self.used_legacy_path
        )


def _check_protocol(
    events: list[dict[str, Any]],
    expected: str,
) -> ProtocolCheck:
    check = ProtocolCheck()
    event_types = {e.get("type") for e in events if isinstance(e, dict)}

    # 1. finish event
    finish_events = [e for e in events if e.get("type") == "finish"]
    if finish_events:
        check.has_finish_event = True
        check.finish_reason = finish_events[-1].get("finishReason")

    # 2. data-action → orchestrator
    action_events = [e for e in events if e.get("type") == "data-action"]
    if action_events:
        check.has_data_action = True
        action_data = action_events[0].get("data", {})
        if isinstance(action_data, dict):
            check.orchestrator = action_data.get("orchestrator")
            check.orchestrator_ok = check.orchestrator == "unified_agent"
            # If orchestrator is missing or not unified_agent, might be legacy path
            if check.orchestrator and check.orchestrator != "unified_agent":
                check.used_legacy_path = True
    else:
        # No data-action at all — could be error or legacy fallback
        check.used_legacy_path = True

    # 3. tool-progress events (ToolTracker telemetry)
    tool_progress = [e for e in events if e.get("type") == "data-tool-progress"]
    check.has_tool_progress = len(tool_progress) > 0
    check.tool_progress_count = len(tool_progress)

    # 4. Expected artifact events present
    expected_events = _EXPECTED_ARTIFACT_EVENTS.get(expected, set())
    present = event_types & expected_events
    missing = expected_events - event_types
    check.has_expected_artifact_events = len(present) > 0
    check.missing_artifact_events = sorted(missing)

    return check


# ---------------------------------------------------------------------------
# Quiz context-awareness check (BUG-1 regression guard)
# ---------------------------------------------------------------------------

# Indicators that quiz generation used data tools to get class/student context
_CONTEXT_TOOL_NAMES = {
    "get_teacher_classes", "get_class_detail", "get_student_grades",
    "get_assignment_submissions", "analyze_student_weakness",
    "get_student_error_patterns",
}


def _check_url_ascii_safe(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Check that all file URLs in events are ASCII-safe (no Chinese chars).

    Regression guard: previously file tools embedded Chinese characters in URL
    paths like ``/api/files/generated/{uuid}_初一数学教案.docx``, which breaks
    proxies and percent-encoding-sensitive middleware.
    """
    file_events = [
        e for e in events
        if e.get("type") == "data-file-ready" and isinstance(e.get("data"), dict)
    ]
    results: list[dict[str, Any]] = []
    all_ascii = True
    for e in file_events:
        url = e["data"].get("url", "")
        try:
            url.encode("ascii")
            ascii_ok = True
        except UnicodeEncodeError:
            ascii_ok = False
            all_ascii = False
        results.append({"url": url, "ascii_safe": ascii_ok})
    return {
        "all_ascii_safe": all_ascii,
        "checked_urls": results,
    }


def _check_quiz_context_awareness(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check whether quiz generation attempted to use data tools.

    If BUG-1 regresses (base tools filtered out), tool-progress events for
    data tools will be absent even though the Agent should call them.
    """
    tool_progress = [
        e for e in events
        if e.get("type") == "data-tool-progress" and isinstance(e.get("data"), dict)
    ]
    data_tools_seen = set()
    all_tools_seen = set()
    for e in tool_progress:
        tool_name = e.get("data", {}).get("tool") or ""
        all_tools_seen.add(tool_name)
        if tool_name in _CONTEXT_TOOL_NAMES:
            data_tools_seen.add(tool_name)

    return {
        "data_tools_called": sorted(data_tools_seen),
        "data_tools_count": len(data_tools_seen),
        "all_tools_called": sorted(all_tools_seen),
        "base_tools_available": len(data_tools_seen) > 0,
    }


# ---------------------------------------------------------------------------
# Quality evaluators (unchanged logic, minor additions)
# ---------------------------------------------------------------------------

def _parse_sse_payloads(raw_text: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        body = line[6:]
        if body == "[DONE]":
            continue
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            payloads.append(parsed)
    return payloads


def _quality_for_quiz(events: list[dict[str, Any]]) -> dict[str, Any]:
    qs = [e for e in events if e.get("type") == "data-quiz-question"]
    complete = [e for e in events if e.get("type") == "data-quiz-complete"]
    valid_count = 0
    for e in qs:
        q = e.get("data", {}).get("question", {})
        if not isinstance(q, dict):
            continue
        stem = q.get("question") or q.get("stem")
        answer = q.get("correctAnswer") or q.get("answer")
        if stem and answer:
            valid_count += 1
    total = len(qs)
    completeness = (valid_count / total) if total else 0.0
    score = round(min(1.0, total / 5) * 0.5 + completeness * 0.5, 3)
    return {
        "artifact_ok": bool(complete and total > 0),
        "total_questions": total,
        "valid_questions": valid_count,
        "completeness_ratio": round(completeness, 3),
        "quality_score": score,
    }


def _quality_for_ppt(events: list[dict[str, Any]]) -> dict[str, Any]:
    outlines = [e for e in events if e.get("type") == "data-pptx-outline"]
    files = [
        e for e in events
        if e.get("type") == "data-file-ready"
        and isinstance(e.get("data"), dict)
        and e["data"].get("type") == "pptx"
    ]
    if files:
        data = files[0].get("data", {})
        has_url = bool(data.get("url"))
        return {
            "artifact_ok": has_url,
            "mode": "pptx_file",
            "filename": data.get("filename"),
            "quality_score": 0.8 if has_url else 0.0,
        }
    if not outlines:
        return {
            "artifact_ok": False,
            "outline_count": 0,
            "quality_score": 0.0,
        }
    data = outlines[0].get("data", {})
    outline = data.get("outline", [])
    total_slides = data.get("totalSlides", 0) or len(outline)
    sections = len(outline) if isinstance(outline, list) else 0
    score = round(min(1.0, total_slides / 10) * 0.6 + min(1.0, sections / 5) * 0.4, 3)
    return {
        "artifact_ok": True,
        "outline_count": sections,
        "total_slides": total_slides,
        "quality_score": score,
    }


def _quality_for_docx(events: list[dict[str, Any]]) -> dict[str, Any]:
    files = [
        e for e in events
        if e.get("type") == "data-file-ready"
        and isinstance(e.get("data"), dict)
        and e["data"].get("type") == "docx"
    ]
    if not files:
        return {
            "artifact_ok": False,
            "quality_score": 0.0,
        }
    data = files[0]["data"]
    has_url = bool(data.get("url"))
    has_name = bool(data.get("filename"))
    file_size = data.get("size", 0) or 0

    # Score breakdown:
    #   0.4 — has downloadable URL
    #   0.2 — has display filename
    #   0.2 — file size >= 10 KB (non-trivial content)
    #   0.2 — URL is ASCII-safe (no Chinese chars in path)
    url_str = data.get("url", "")
    try:
        url_str.encode("ascii")
        url_ascii = True
    except UnicodeEncodeError:
        url_ascii = False

    score = round(
        (0.4 if has_url else 0.0)
        + (0.2 if has_name else 0.0)
        + (0.2 if file_size >= 10240 else 0.1 if file_size > 0 else 0.0)
        + (0.2 if url_ascii else 0.0),
        3,
    )
    return {
        "artifact_ok": has_url,
        "filename": data.get("filename"),
        "file_size": file_size,
        "url_ascii_safe": url_ascii,
        "quality_score": score,
    }


def _quality_for_interactive(events: list[dict[str, Any]]) -> dict[str, Any]:
    full = [e for e in events if e.get("type") == "data-interactive-content"]
    if full:
        data = full[0].get("data", {})
        html_len = len(data.get("html") or "")
        css_len = len(data.get("css") or "")
        js_len = len(data.get("js") or "")
        total_len = html_len + css_len + js_len

        # Score breakdown:
        #   0.3 — HTML has substance (> 2 KB)
        #   0.2 — CSS has substance (> 1 KB)
        #   0.3 — JS has substance (> 2 KB)
        #   0.2 — All three streams present and non-trivial
        html_score = 0.3 if html_len > 2000 else 0.15 if html_len > 200 else 0.0
        css_score = 0.2 if css_len > 1000 else 0.1 if css_len > 100 else 0.0
        js_score = 0.3 if js_len > 2000 else 0.15 if js_len > 50 else 0.0
        completeness = 0.2 if (html_len > 200 and css_len > 100 and js_len > 50) else 0.0
        score = round(html_score + css_score + js_score + completeness, 3)

        return {
            "artifact_ok": html_len > 200 and js_len > 50,
            "html_len": html_len,
            "css_len": css_len,
            "js_len": js_len,
            "total_len": total_len,
            "quality_score": score,
        }

    deltas = [e for e in events if str(e.get("type", "")).startswith("data-interactive-")]
    return {
        "artifact_ok": len(deltas) > 0,
        "delta_events": len(deltas),
        "quality_score": 0.4 if deltas else 0.0,
    }


def _evaluate(expected: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    if expected == "quiz":
        return _quality_for_quiz(events)
    if expected == "ppt":
        return _quality_for_ppt(events)
    if expected == "docx":
        return _quality_for_docx(events)
    if expected == "interactive":
        return _quality_for_interactive(events)
    return {"artifact_ok": False, "quality_score": 0.0}


async def _extract_artifact_snapshot(
    events: list[dict[str, Any]],
    client: AsyncClient,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}

    quiz_items = [e.get("data", {}) for e in events if e.get("type") == "data-quiz-question"]
    if quiz_items:
        sample = []
        for item in quiz_items[:2]:
            q = item.get("question", {})
            if isinstance(q, dict):
                sample.append(
                    {
                        "question": q.get("question") or q.get("stem"),
                        "answer": q.get("correctAnswer") or q.get("answer"),
                        "options": q.get("options"),
                    }
                )
        snapshot["quiz_sample"] = sample

    outlines = [e.get("data", {}) for e in events if e.get("type") == "data-pptx-outline"]
    if outlines:
        first = outlines[0]
        outline = first.get("outline", [])
        snapshot["ppt_outline_sample"] = outline[:3] if isinstance(outline, list) else outline

    interactive = [e.get("data", {}) for e in events if e.get("type") == "data-interactive-content"]
    if interactive:
        data = interactive[0]
        snapshot["interactive_sample"] = {
            "title": data.get("title"),
            "html_preview": (data.get("html") or "")[:300],
            "css_preview": (data.get("css") or "")[:200],
            "js_preview": (data.get("js") or "")[:200],
        }

    files = [
        e.get("data", {})
        for e in events
        if e.get("type") == "data-file-ready" and isinstance(e.get("data"), dict)
    ]
    if files:
        snapshot["files"] = files
        docx_file = next((f for f in files if f.get("type") == "docx"), None)
        if docx_file and docx_file.get("url"):
            try:
                docx_resp = await client.get(str(docx_file["url"]))
                if docx_resp.status_code == 200:
                    from docx import Document  # type: ignore

                    doc = Document(io.BytesIO(docx_resp.content))
                    paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
                    snapshot["docx_text_preview"] = "\n".join(paras[:12])[:1200]
                else:
                    snapshot["docx_text_preview"] = (
                        f"[download_failed status={docx_resp.status_code}]"
                    )
            except Exception as exc:
                snapshot["docx_text_preview"] = f"[extract_failed {type(exc).__name__}: {exc}]"

    return snapshot


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def _run() -> dict[str, Any]:
    settings = get_settings()
    scenarios = [
        Scenario(
            name="quiz",
            message="请生成5道关于一次函数的选择题，适合初二，附答案解析。",
            expected="quiz",
        ),
        Scenario(
            name="ppt_outline",
            message="请给我一份《牛顿第一定律》初中物理课件PPT大纲。",
            expected="ppt",
        ),
        Scenario(
            name="docx_lesson_plan",
            message="请生成一份初一数学《整式加减》45分钟教案，并导出为docx。",
            expected="docx",
        ),
        Scenario(
            name="interactive_page",
            message="请制作一个可以拖拽观察抛物线变化的互动网页，适合初二。",
            expected="interactive",
        ),
    ]

    java_client = get_java_client()
    await java_client.start()

    # Attach log capture to the conversation module logger
    conv_logger = logging.getLogger("api.conversation")
    log_capture = _RetryLogCapture()
    conv_logger.addHandler(log_capture)

    results: list[dict[str, Any]] = []
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=300) as client:
            for item in scenarios:
                log_capture.reset()
                started = time.perf_counter()
                resp = await client.post(
                    "/api/conversation/stream",
                    json={
                        "message": item.message,
                        "language": "zh-CN",
                        "teacherId": "2fe869fb-4a2d-4aa1-a173-c263235dc62b",
                    },
                )
                duration_ms = (time.perf_counter() - started) * 1000
                payloads = _parse_sse_payloads(resp.text)
                quality = _evaluate(item.expected, payloads)
                types = sorted({p.get("type", "") for p in payloads if isinstance(p, dict)})
                action_payload = next(
                    (p.get("data", {}) for p in payloads if p.get("type") == "data-action"),
                    {},
                )
                full_text = "".join(
                    p.get("delta", "") for p in payloads if p.get("type") == "text-delta"
                ).strip()
                text_preview = full_text[:240]
                artifact_snapshot = await _extract_artifact_snapshot(payloads, client)

                # --- Enhanced checks ---
                protocol = _check_protocol(payloads, item.expected)
                retry_info = log_capture.summary()
                url_check = _check_url_ascii_safe(payloads)
                context_info = (
                    _check_quiz_context_awareness(payloads)
                    if item.expected == "quiz"
                    else None
                )

                results.append(
                    {
                        "scenario": item.name,
                        "expected": item.expected,
                        "duration_ms": round(duration_ms, 2),
                        "http_status": resp.status_code,
                        "event_count": len(payloads),
                        "event_types": types,
                        "action": action_payload,
                        "assistant_text": full_text[:1500],
                        "text_preview": text_preview,
                        "artifact_snapshot": artifact_snapshot,
                        "quality": quality,
                        "protocol": protocol.to_dict(),
                        "protocol_passed": protocol.passed,
                        "retry": retry_info,
                        "url_ascii_safe": url_check,
                        **({"quiz_context": context_info} if context_info else {}),
                    }
                )
    finally:
        conv_logger.removeHandler(log_capture)
        await java_client.close()

    overall_score = round(
        sum(float(r["quality"].get("quality_score", 0.0)) for r in results) / max(len(results), 1),
        3,
    )
    passed = sum(1 for r in results if r["quality"].get("artifact_ok"))
    protocol_passed = sum(1 for r in results if r.get("protocol_passed"))
    total_hard_retries = sum(r["retry"]["hard_retry_count"] for r in results)
    total_soft_retries = sum(r["retry"]["soft_retry_count"] for r in results)
    urls_all_ascii = all(
        r.get("url_ascii_safe", {}).get("all_ascii_safe", True) for r in results
    )

    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "unified_flags": {
            "agent_unified_enabled": settings.agent_unified_enabled,
            "agent_unified_quiz_enabled": settings.agent_unified_quiz_enabled,
            "agent_unified_content_enabled": settings.agent_unified_content_enabled,
        },
        "total_scenarios": len(results),
        "artifact_passed": passed,
        "artifact_pass_ratio": round(passed / max(len(results), 1), 3),
        "protocol_passed": protocol_passed,
        "protocol_pass_ratio": round(protocol_passed / max(len(results), 1), 3),
        "overall_quality_score": overall_score,
        "retry_summary": {
            "total_hard_retries": total_hard_retries,
            "total_soft_retries": total_soft_retries,
        },
        "urls_all_ascii_safe": urls_all_ascii,
        "results": results,
    }


def _to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase2 Live Content Quality Report",
        "",
        f"- Timestamp: {report['timestamp']}",
        f"- Unified flags: {report['unified_flags']}",
        f"- Artifact pass: {report['artifact_passed']}/{report['total_scenarios']} "
        f"({report['artifact_pass_ratio']})",
        f"- Protocol pass: {report['protocol_passed']}/{report['total_scenarios']} "
        f"({report['protocol_pass_ratio']})",
        f"- Overall quality score: {report['overall_quality_score']}",
        f"- Retries: hard={report['retry_summary']['total_hard_retries']} "
        f"soft={report['retry_summary']['total_soft_retries']}",
        f"- URLs ASCII-safe: {report.get('urls_all_ascii_safe', 'N/A')}",
        "",
        "## Scenario Results",
    ]
    for row in report["results"]:
        q = row["quality"]
        p = row.get("protocol", {})
        r = row.get("retry", {})
        lines.extend(
            [
                "",
                f"### `{row['scenario']}` ({row['expected']})",
                f"- artifact_ok={q.get('artifact_ok')} "
                f"score={q.get('quality_score')} "
                f"duration_ms={row['duration_ms']}",
                f"- protocol_passed={row.get('protocol_passed')} "
                f"orchestrator={p.get('orchestrator')} "
                f"finish={p.get('has_finish_event')}",
                f"- tool_progress_count={p.get('tool_progress_count', 0)} "
                f"missing_artifacts={p.get('missing_artifact_events', [])}",
                f"- retries: hard={r.get('hard_retry_count', 0)} "
                f"soft={r.get('soft_retry_count', 0)} "
                f"exhausted={r.get('soft_retry_exhausted', False)}",
                f"- action={row.get('action')}",
                f"- event_count={row['event_count']} status={row['http_status']}",
                f"- text_preview={row.get('text_preview', '')}",
            ]
        )
        url_info = row.get("url_ascii_safe", {})
        if url_info.get("checked_urls"):
            lines.append(
                f"- url_ascii_safe={url_info.get('all_ascii_safe')} "
                f"urls={url_info.get('checked_urls', [])}"
            )
        if "quiz_context" in row:
            ctx = row["quiz_context"]
            lines.append(
                f"- quiz_context: base_tools_available={ctx.get('base_tools_available')} "
                f"data_tools={ctx.get('data_tools_called', [])}"
            )
        lines.extend(
            [
                f"- artifact_snapshot={row.get('artifact_snapshot', {})}",
                f"- quality_details={q}",
            ]
        )
    return "\n".join(lines) + "\n"


async def main() -> None:
    report = await _run()
    out_dir = Path("docs/testing")
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "phase2-live-content-quality-report.json"
    md_path = out_dir / "phase2-live-content-quality-report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_to_markdown(report), encoding="utf-8")
    print(f"Saved: {json_path}")
    print(f"Saved: {md_path}")

    # Summary to stdout
    print(f"\nArtifact: {report['artifact_passed']}/{report['total_scenarios']}")
    print(f"Protocol: {report['protocol_passed']}/{report['total_scenarios']}")
    print(f"Quality:  {report['overall_quality_score']}")
    retries = report["retry_summary"]
    if retries["total_hard_retries"] or retries["total_soft_retries"]:
        print(
            f"Retries:  hard={retries['total_hard_retries']} "
            f"soft={retries['total_soft_retries']}"
        )


if __name__ == "__main__":
    asyncio.run(main())
