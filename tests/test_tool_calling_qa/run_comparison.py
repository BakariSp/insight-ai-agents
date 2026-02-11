"""Live multi-model comparison runner with HTML dashboard.

Runs D2 + D8 across all available models concurrently.
Writes live-updating HTML to `comparison_report.html`.

Usage:
    cd insight-ai-agent
    python tests/test_tool_calling_qa/run_comparison.py
    # Then open comparison_report.html in browser
"""

from __future__ import annotations

import asyncio
import json
import sys
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("NATIVE_AGENT_ENABLED", "true")

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
    INJECTION_LENGTHS,
    INJECTION_MESSAGE,
)

REPORT_PATH = Path(__file__).resolve().parents[2] / "comparison_report.html"

# ── State ──

@dataclass
class CellResult:
    status: str = "pending"  # pending | running | pass | fail | error | skip
    detail: str = ""
    latency_ms: float = 0

@dataclass
class LiveState:
    started: float = field(default_factory=time.monotonic)
    models: list[str] = field(default_factory=list)
    d2_cases: list[str] = field(default_factory=list)
    d8_cases: list[str] = field(default_factory=list)
    # grid[model_label][case_id] = CellResult
    grid: dict[str, dict[str, CellResult]] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

STATE = LiveState()


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


# ── HTML renderer ──

def render_html() -> str:
    elapsed = time.monotonic() - STATE.started
    mins, secs = divmod(int(elapsed), 60)

    total = sum(
        1 for m in STATE.grid.values() for c in m.values()
    )
    done = sum(
        1 for m in STATE.grid.values() for c in m.values()
        if c.status in ("pass", "fail", "error", "skip")
    )
    running = sum(
        1 for m in STATE.grid.values() for c in m.values()
        if c.status == "running"
    )
    pct = (done / total * 100) if total else 0

    status_colors = {
        "pending": "#2a2a3e",
        "running": "#1a3a5c",
        "pass": "#1a4a2a",
        "fail": "#5a1a1a",
        "error": "#5a3a1a",
        "skip": "#3a3a2a",
    }
    status_emoji = {
        "pending": "⏳",
        "running": "🔄",
        "pass": "✅",
        "fail": "❌",
        "error": "⚠️",
        "skip": "⏭️",
    }

    def _cell(cr: CellResult) -> str:
        bg = status_colors.get(cr.status, "#2a2a3e")
        emoji = status_emoji.get(cr.status, "")
        lat = f'<div class="lat">{cr.latency_ms/1000:.1f}s</div>' if cr.latency_ms > 0 else ""
        title = cr.detail.replace('"', '&quot;') if cr.detail else cr.status
        return f'<td class="cell" style="background:{bg}" title="{title}">{emoji}{lat}</td>'

    # Build model score summary
    model_scores = {}
    for label in STATE.models:
        cells = STATE.grid.get(label, {})
        passed = sum(1 for c in cells.values() if c.status == "pass")
        finished = sum(1 for c in cells.values() if c.status in ("pass", "fail", "error"))
        model_scores[label] = (passed, finished)

    # D2 table
    d2_rows = ""
    for case_id in STATE.d2_cases:
        row = f'<td class="case-id">{case_id}</td>'
        for label in STATE.models:
            cr = STATE.grid.get(label, {}).get(case_id, CellResult())
            row += _cell(cr)
        d2_rows += f"<tr>{row}</tr>\n"

    # D8 table
    d8_rows = ""
    for case_id in STATE.d8_cases:
        row = f'<td class="case-id">{case_id}</td>'
        for label in STATE.models:
            cr = STATE.grid.get(label, {}).get(case_id, CellResult())
            row += _cell(cr)
        d8_rows += f"<tr>{row}</tr>\n"

    model_headers = "".join(
        f'<th class="model-hdr">{label}<br>'
        f'<span class="sc-pass">{ model_scores.get(label, (0,0))[0] }</span>'
        f'/<span class="sc-total">{ model_scores.get(label, (0,0))[1] }</span></th>'
        for label in STATE.models
    )

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="3">
<title>Tool Calling QA — Model Comparison</title>
<style>
  * {{ box-sizing:border-box; }}
  body {{ background:#12121f; color:#e8e8e8; font-family:-apple-system,'Segoe UI',Roboto,sans-serif; margin:0; padding:24px 32px; }}
  h1 {{ color:#4fc3f7; font-size:28px; margin:0 0 4px; }}
  h2 {{ color:#81c784; font-size:22px; margin:32px 0 12px; }}
  .meta {{ color:#777; font-size:15px; margin-bottom:16px; }}
  table {{ border-collapse:collapse; margin:8px 0; width:auto; }}
  th {{ background:#0d0d1a; position:sticky; top:0; z-index:2; }}
  td {{ border:1px solid #333; }}
  .model-hdr {{ padding:10px 14px; font-size:14px; font-weight:600; text-align:center; white-space:nowrap; min-width:100px; }}
  .sc-pass {{ color:#8f8; font-size:16px; }}
  .sc-total {{ color:#aaa; font-size:14px; }}
  .case-id {{ padding:8px 14px; font-size:15px; font-weight:500; white-space:nowrap; background:#0d0d1a; position:sticky; left:0; z-index:1; }}
  .cell {{ padding:6px 10px; text-align:center; font-size:22px; min-width:100px; }}
  .lat {{ font-size:12px; color:#aaa; margin-top:2px; }}
  .bar {{ background:#333; border-radius:6px; height:36px; margin:12px 0; overflow:hidden; }}
  .bar-fill {{ background:linear-gradient(90deg,#4fc3f7,#81c784); height:100%; transition:width 0.5s; display:flex; align-items:center; justify-content:center; font-size:16px; font-weight:700; color:#000; }}
  .stats {{ display:flex; gap:16px; font-size:16px; margin:12px 0; }}
  .stats span {{ padding:6px 16px; border-radius:6px; font-weight:500; }}
  .summary td, .summary th {{ padding:10px 20px; font-size:16px; }}
  .summary th {{ text-align:left; }}
  .rate-good {{ color:#8f8; font-weight:700; }}
  .rate-bad {{ color:#f88; font-weight:700; }}
</style>
</head><body>
<h1>Tool Calling QA — Multi-Model Comparison</h1>
<p class="meta">Started: {datetime.now().strftime('%H:%M:%S')} | Elapsed: {mins}m {secs}s | Auto-refresh: 3s</p>

<div class="bar"><div class="bar-fill" style="width:{pct:.0f}%">{done}/{total} ({pct:.0f}%)</div></div>

<div class="stats">
  <span style="background:#1a4a2a">Done: {done}</span>
  <span style="background:#1a3a5c">Running: {running}</span>
  <span style="background:#2a2a3e">Pending: {total - done - running}</span>
</div>

<h2>D2: Boundary Confusion (traps + implicit)</h2>
<div style="overflow-x:auto">
<table>
<tr><th class="case-id" style="text-align:left">Case</th>{model_headers}</tr>
{d2_rows}
</table>
</div>

<h2>D8: Context Pressure (verbose + injection)</h2>
<div style="overflow-x:auto">
<table>
<tr><th class="case-id" style="text-align:left">Case</th>{model_headers}</tr>
{d8_rows}
</table>
</div>

<h2>Score Summary</h2>
<table class="summary">
<tr><th>Model</th><th>Passed</th><th>Total</th><th>Rate</th></tr>
{"".join(
    f'<tr><td>{label}</td>'
    f'<td style="text-align:center">{model_scores.get(label,(0,0))[0]}</td>'
    f'<td style="text-align:center">{model_scores.get(label,(0,0))[1]}</td>'
    f'<td style="text-align:center" class="{"rate-good" if model_scores.get(label,(0,0))[1] > 0 and model_scores.get(label,(0,0))[0]/model_scores.get(label,(0,0))[1] >= 0.8 else "rate-bad"}">'
    f'{(model_scores.get(label,(0,0))[0]/model_scores.get(label,(0,0))[1]*100) if model_scores.get(label,(0,0))[1] > 0 else 0:.0f}%</td></tr>'
    for label in STATE.models
)}
</table>

</body></html>"""


async def write_report():
    async with STATE.lock:
        REPORT_PATH.write_text(render_html(), encoding="utf-8")


# ── Test runners ──

async def run_d2_for_model(model_id: str, label: str):
    for case in ALL_BOUNDARY_CASES:
        case_id = case.id
        async with STATE.lock:
            STATE.grid[label][case_id] = CellResult(status="running")
        await write_report()

        try:
            result = await run_agent_phase1(case.message, model_id)
            tools = result.tool_names_list

            if case.should_call_tool:
                passed = result.called_any_tool and (
                    not case.expected_tools
                    or bool(result.tool_names & set(case.expected_tools))
                )
                detail = f"tools={tools}" if passed else f"MISS tools={tools}"
            else:
                non_clarify = [t for t in tools if t != "ask_clarification"]
                passed = len(non_clarify) == 0
                detail = "clean" if passed else f"TRIGGERED {tools}"

            status = "pass" if passed else "fail"
            async with STATE.lock:
                STATE.grid[label][case_id] = CellResult(
                    status=status, detail=detail, latency_ms=result.latency_ms,
                )
            tag = "PASS" if passed else "FAIL"
            print(f"  [{label:>14}] {case_id}: [{tag}] {detail} ({result.latency_ms:.0f}ms)")

        except Exception as e:
            async with STATE.lock:
                STATE.grid[label][case_id] = CellResult(
                    status="error", detail=str(e)[:80],
                )
            print(f"  [{label:>14}] {case_id}: [ERROR] {e}")

        await write_report()


async def run_d8_for_model(model_id: str, label: str):
    # D8a interactive
    for tag, message in VERBOSE_INTERACTIVE:
        case_id = f"d8a-html-{tag}"
        async with STATE.lock:
            STATE.grid[label][case_id] = CellResult(status="running")
        await write_report()

        try:
            result = await run_agent_phase1(message, model_id)
            passed = "generate_interactive_html" in result.tool_names
            detail = f"{len(message)}ch tools={result.tool_names_list}"
            async with STATE.lock:
                STATE.grid[label][case_id] = CellResult(
                    status="pass" if passed else "fail",
                    detail=detail, latency_ms=result.latency_ms,
                )
            s = "PASS" if passed else "FAIL"
            print(f"  [{label:>14}] {case_id}: [{s}] {detail} ({result.latency_ms:.0f}ms)")
        except Exception as e:
            async with STATE.lock:
                STATE.grid[label][case_id] = CellResult(status="error", detail=str(e)[:80])
            print(f"  [{label:>14}] {case_id}: [ERROR] {e}")
        await write_report()

    # D8a quiz
    for tag, message in VERBOSE_QUIZ:
        case_id = f"d8a-quiz-{tag}"
        async with STATE.lock:
            STATE.grid[label][case_id] = CellResult(status="running")
        await write_report()

        try:
            result = await run_agent_phase1(message, model_id)
            passed = "generate_quiz_questions" in result.tool_names
            detail = f"{len(message)}ch tools={result.tool_names_list}"
            async with STATE.lock:
                STATE.grid[label][case_id] = CellResult(
                    status="pass" if passed else "fail",
                    detail=detail, latency_ms=result.latency_ms,
                )
            s = "PASS" if passed else "FAIL"
            print(f"  [{label:>14}] {case_id}: [{s}] {detail} ({result.latency_ms:.0f}ms)")
        except Exception as e:
            async with STATE.lock:
                STATE.grid[label][case_id] = CellResult(status="error", detail=str(e)[:80])
            print(f"  [{label:>14}] {case_id}: [ERROR] {e}")
        await write_report()

    # D8c injection
    for doc_chars in INJECTION_LENGTHS:
        case_id = f"d8c-{doc_chars}ch"
        async with STATE.lock:
            STATE.grid[label][case_id] = CellResult(status="running")
        await write_report()

        try:
            user_prompt = build_injected_prompt(doc_chars, INJECTION_MESSAGE)
            result = await run_agent_phase1(INJECTION_MESSAGE, model_id, user_prompt=user_prompt)
            acceptable = {"generate_quiz_questions", "ask_clarification"}
            passed = bool(result.tool_names & acceptable)
            detail = f"{doc_chars}doc tools={result.tool_names_list}"
            async with STATE.lock:
                STATE.grid[label][case_id] = CellResult(
                    status="pass" if passed else "fail",
                    detail=detail, latency_ms=result.latency_ms,
                )
            s = "PASS" if passed else "FAIL"
            print(f"  [{label:>14}] {case_id}: [{s}] {detail} ({result.latency_ms:.0f}ms)")
        except Exception as e:
            async with STATE.lock:
                STATE.grid[label][case_id] = CellResult(status="error", detail=str(e)[:80])
            print(f"  [{label:>14}] {case_id}: [ERROR] {e}")
        await write_report()


async def main():
    setup_mocks()

    models = MODELS_TO_TEST
    print(f"\n  Models: {len(models)}")
    for m in models:
        print(f"    {m['label']:>16} -> {m['id']}")

    # Init state
    STATE.models = [m["label"] for m in models]
    STATE.d2_cases = [c.id for c in ALL_BOUNDARY_CASES]
    STATE.d8_cases = (
        [f"d8a-html-{tag}" for tag, _ in VERBOSE_INTERACTIVE]
        + [f"d8a-quiz-{tag}" for tag, _ in VERBOSE_QUIZ]
        + [f"d8c-{c}ch" for c in INJECTION_LENGTHS]
    )

    for m in models:
        STATE.grid[m["label"]] = {}
        for cid in STATE.d2_cases + STATE.d8_cases:
            STATE.grid[m["label"]][cid] = CellResult()

    await write_report()
    print(f"\n  Dashboard: {REPORT_PATH}")
    print(f"  Open in browser to monitor progress (auto-refreshes every 3s)\n")

    # Run all models concurrently
    tasks = []
    for m in models:
        tasks.append(run_d2_for_model(m["id"], m["label"]))
        tasks.append(run_d8_for_model(m["id"], m["label"]))

    await asyncio.gather(*tasks, return_exceptions=True)

    # Final report
    await write_report()

    # Print summary
    print(f"\n{'='*70}")
    print(f"  FINAL RESULTS")
    print(f"{'='*70}")
    for label in STATE.models:
        cells = STATE.grid[label]
        passed = sum(1 for c in cells.values() if c.status == "pass")
        total = sum(1 for c in cells.values() if c.status in ("pass", "fail"))
        errors = sum(1 for c in cells.values() if c.status == "error")
        pct = (passed / total * 100) if total else 0
        err_str = f" ({errors} errors)" if errors else ""
        print(f"  {label:>16}: {passed}/{total} ({pct:.0f}%){err_str}")
    print(f"{'='*70}")
    print(f"\n  Full report: {REPORT_PATH}\n")


if __name__ == "__main__":
    asyncio.run(main())
