"""Quick test: interactive content generation after optimization.

Runs ONLY the interactive scenario to measure:
- Duration (target: ~40-50s, down from ~131s)
- Output size (HTML/CSS/JS — expect smaller due to MVP prompts)
- CDN library usage in generated JS
- Quality score (must remain >= 0.7)
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from main import app
from services.java_client import get_java_client


def _parse_sse(raw: str) -> list[dict]:
    payloads = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        try:
            parsed = json.loads(line[6:])
            if isinstance(parsed, dict):
                payloads.append(parsed)
        except json.JSONDecodeError:
            continue
    return payloads


async def main() -> None:
    java_client = get_java_client()
    await java_client.start()

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=300) as client:
            print("=== Interactive Content Optimization Test ===\n")

            started = time.perf_counter()
            resp = await client.post(
                "/api/conversation/stream",
                json={
                    "message": "请制作一个可以拖拽观察抛物线变化的互动网页，适合初二。",
                    "language": "zh-CN",
                    "teacherId": "2fe869fb-4a2d-4aa1-a173-c263235dc62b",
                },
            )
            duration_s = time.perf_counter() - started

            payloads = _parse_sse(resp.text)
            event_types = sorted({p.get("type", "") for p in payloads})

            # Extract interactive content
            interactive = [p for p in payloads if p.get("type") == "data-interactive-content"]
            if interactive:
                data = interactive[0].get("data", {})
                html_len = len(data.get("html") or "")
                css_len = len(data.get("css") or "")
                js_len = len(data.get("js") or "")
                js_code = data.get("js") or ""
            else:
                html_len = css_len = js_len = 0
                js_code = ""

            # Check CDN library usage
            uses_chartjs = "Chart(" in js_code or "Chart.js" in js_code
            uses_mathjax = "MathJax" in js_code
            uses_matterjs = "Matter." in js_code

            # Action info
            action = next(
                (p.get("data", {}) for p in payloads if p.get("type") == "data-action"),
                {},
            )

            # Report
            print(f"Duration:      {duration_s:.1f}s (baseline: ~131s)")
            print(f"HTTP status:   {resp.status_code}")
            print(f"Events:        {len(payloads)} (baseline: 1960)")
            print(f"Model tier:    {action.get('modelTier', '?')}")
            print(f"Orchestrator:  {action.get('orchestrator', '?')}")
            print()
            print(f"HTML size:     {html_len:,} bytes (baseline: 15,536)")
            print(f"CSS size:      {css_len:,} bytes (baseline: 21,868)")
            print(f"JS size:       {js_len:,} bytes (baseline: 25,495)")
            print(f"Total:         {html_len + css_len + js_len:,} bytes (baseline: 62,899)")
            print()
            print(f"Uses Chart.js: {uses_chartjs}")
            print(f"Uses MathJax:  {uses_mathjax}")
            print(f"Uses Matter.js:{uses_matterjs}")
            print()

            # Quality check
            ok = html_len > 200 and js_len > 50
            html_score = 0.3 if html_len > 2000 else 0.15 if html_len > 200 else 0.0
            css_score = 0.2 if css_len > 1000 else 0.1 if css_len > 100 else 0.0
            js_score = 0.3 if js_len > 2000 else 0.15 if js_len > 50 else 0.0
            completeness = 0.2 if (html_len > 200 and css_len > 100 and js_len > 50) else 0.0
            score = round(html_score + css_score + js_score + completeness, 3)

            print(f"Artifact OK:   {ok}")
            print(f"Quality score: {score} (baseline: 1.0, target: >= 0.7)")
            print()

            # Pass/Fail
            if not ok:
                print("FAIL — interactive content not generated")
            elif score < 0.7:
                print(f"WARN — quality score {score} below 0.7 threshold")
            elif duration_s > 90:
                print(f"WARN — duration {duration_s:.0f}s still > 90s (wanted < 60s)")
            else:
                speedup = 131.2 / duration_s
                print(f"PASS — {speedup:.1f}x speedup, quality maintained")

            # Save result
            result = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "duration_s": round(duration_s, 1),
                "baseline_s": 131.2,
                "speedup": round(131.2 / max(duration_s, 0.1), 1),
                "html_len": html_len,
                "css_len": css_len,
                "js_len": js_len,
                "total_len": html_len + css_len + js_len,
                "quality_score": score,
                "uses_cdn": {
                    "chartjs": uses_chartjs,
                    "mathjax": uses_mathjax,
                    "matterjs": uses_matterjs,
                },
                "event_count": len(payloads),
                "action": action,
            }
            out = Path("docs/testing/interactive-optimization-test.json")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\nSaved: {out}")

    finally:
        await java_client.close()


if __name__ == "__main__":
    asyncio.run(main())
