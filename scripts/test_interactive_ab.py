"""A/B test: Interactive JS generation — GLM-4.7 vs qwen3-coder-plus.

Directly patches interactive_skill.generate_interactive_stream to control
which model each stream uses. Both runs use qwen-max for HTML/CSS; only JS differs.

Comparing the two best coding-optimized models available:
- zai/glm-4.7 (ZhipuAI, 355B flagship, 73.8% SWE-bench)
- dashscope/qwen3-coder-plus (Alibaba, 480B MoE / 35B active)
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

PROMPT = "请制作一个可以拖拽观察抛物线变化的互动网页，适合初二。"
TEACHER_ID = "2fe869fb-4a2d-4aa1-a173-c263235dc62b"

# A/B candidates for the JS stream model
AB_CONFIGS = {
    "glm-4.7": {
        "html": "dashscope/qwen-max",
        "css": "dashscope/qwen-max",
        "js": "zai/glm-4.7",
    },
    "qwen3-coder": {
        "html": "dashscope/qwen-max",
        "css": "dashscope/qwen-max",
        "js": "dashscope/qwen3-coder-plus",
    },
}


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


def _check_js_quality(js_code: str) -> dict[str, Any]:
    """Heuristic quality checks on generated JS code."""
    checks: dict[str, Any] = {}
    checks["non_empty"] = len(js_code.strip()) > 50
    checks["has_dom_ready"] = "DOMContentLoaded" in js_code
    opens = js_code.count("{")
    closes = js_code.count("}")
    checks["braces_balanced"] = abs(opens - closes) <= 1
    trimmed = js_code.rstrip()
    checks["not_truncated"] = not any([
        trimmed.endswith("//"), trimmed.endswith("/*"),
        trimmed.endswith(","), trimmed.endswith("("), trimmed.endswith("="),
    ])
    checks["has_error_handling"] = "try" in js_code and "catch" in js_code
    checks["uses_modern_js"] = "const " in js_code or "let " in js_code
    checks["has_event_listeners"] = "addEventListener" in js_code
    checks["has_canvas_or_svg"] = any(
        kw in js_code for kw in ["getContext", "canvas", "Canvas", "svg"]
    )
    checks["has_interactivity"] = any(
        kw in js_code for kw in ["mousedown", "mousemove", "mouseup", "input", "change", "drag", "touchstart"]
    )
    checks["uses_mathjax"] = "MathJax" in js_code
    checks["uses_chartjs"] = "Chart(" in js_code
    checks["uses_matterjs"] = "Matter." in js_code

    core = [
        checks["non_empty"], checks["has_dom_ready"], checks["braces_balanced"],
        checks["not_truncated"], checks["has_event_listeners"], checks["has_interactivity"],
    ]
    checks["runnable_score"] = round(sum(core) / len(core), 2)
    return checks


@dataclass
class RunResult:
    label: str
    js_model: str
    duration_s: float = 0.0
    http_status: int = 0
    event_count: int = 0
    html_len: int = 0
    css_len: int = 0
    js_len: int = 0
    html_code: str = ""
    css_code: str = ""
    js_code: str = ""
    js_quality: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def total_len(self) -> int:
        return self.html_len + self.css_len + self.js_len

    def summary_line(self) -> str:
        q = self.js_quality.get("runnable_score", "?")
        return (
            f"{self.label:>15}: {self.duration_s:>6.1f}s | "
            f"HTML {self.html_len:>6,} | CSS {self.css_len:>6,} | JS {self.js_len:>6,} | "
            f"Total {self.total_len:>6,} | Runnable={q}"
        )


async def _run_one(
    client: AsyncClient,
    label: str,
    model_map: dict[str, str],
) -> RunResult:
    """Run the interactive scenario with a specific model configuration.

    Directly patches interactive_skill.model_for_phase inside generate_interactive_stream
    to guarantee the right model is used for each phase.
    """
    import skills.interactive_skill as iskill
    from agents.provider import create_model
    from config.settings import get_settings

    result = RunResult(label=label, js_model=model_map["js"])

    # Save the original generator
    _original_gen = iskill.generate_interactive_stream

    async def _patched_gen(plan, teacher_context=None):
        """Replacement generator that uses our model_map directly."""
        yield {
            "type": "start",
            "title": plan.get("title", "Interactive Content"),
            "description": plan.get("description", ""),
            "phases": ["html", "css", "js"],
        }

        contract = iskill._build_element_contract(plan)
        settings = get_settings()
        queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

        async def _gen_stream(phase, system_prompt, user_prompt):
            try:
                from pydantic_ai import Agent
                model = create_model(model_map[phase])
                agent = Agent(
                    model=model, output_type=str,
                    system_prompt=system_prompt,
                    retries=1, defer_model_check=True,
                )
                buf = ""
                async with agent.run_stream(
                    user_prompt,
                    model_settings={"max_tokens": settings.agent_max_tokens},
                ) as stream:
                    async for chunk in stream.stream_text(delta=True):
                        buf += chunk
                        await queue.put((f"{phase}-delta", chunk))
                await queue.put((f"{phase}-complete", buf))
            except Exception as e:
                import logging
                logging.getLogger(__name__).exception(
                    "AB test %s/%s failed: %s", label, phase, e
                )
                await queue.put((f"{phase}-complete", ""))

        tasks = [
            asyncio.create_task(
                _gen_stream("html", iskill.HTML_SYSTEM_PROMPT,
                            iskill._build_html_prompt(plan, contract))
            ),
            asyncio.create_task(
                _gen_stream("css", iskill.CSS_SYSTEM_PROMPT,
                            iskill._build_css_prompt(plan, contract))
            ),
            asyncio.create_task(
                _gen_stream("js", iskill.JS_SYSTEM_PROMPT,
                            iskill._build_js_prompt(plan, contract))
            ),
        ]

        completed: set[str] = set()
        full: dict[str, str] = {"html": "", "css": "", "js": ""}
        while len(completed) < 3:
            try:
                msg_type, content = await asyncio.wait_for(queue.get(), timeout=180)
            except asyncio.TimeoutError:
                break
            if msg_type.endswith("-delta"):
                yield {"type": msg_type, "content": content}
            elif msg_type.endswith("-complete"):
                phase = msg_type.replace("-complete", "")
                full[phase] = content
                completed.add(phase)
                yield {"type": msg_type}

        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        yield {
            "type": "complete",
            "html": full["html"], "css": full["css"], "js": full["js"],
            "title": plan.get("title", ""), "description": plan.get("description", ""),
            "preferredHeight": iskill._estimate_height(full["html"]),
        }

    # Monkey-patch
    iskill.generate_interactive_stream = _patched_gen

    try:
        # Also force the TeacherAgent to use qwen-max (avoid Opus fallback issues)
        import config.settings as _csettings
        orig_strong = _csettings.get_settings().strong_model
        _csettings.get_settings().strong_model = "dashscope/qwen-max"

        started = time.perf_counter()
        resp = await client.post(
            "/api/conversation/stream",
            json={
                "message": PROMPT,
                "language": "zh-CN",
                "teacherId": TEACHER_ID,
            },
        )
        result.duration_s = round(time.perf_counter() - started, 1)
        result.http_status = resp.status_code

        payloads = _parse_sse(resp.text)
        result.event_count = len(payloads)

        interactive = [p for p in payloads if p.get("type") == "data-interactive-content"]
        if interactive:
            data = interactive[0].get("data", {})
            result.html_code = data.get("html") or ""
            result.css_code = data.get("css") or ""
            result.js_code = data.get("js") or ""
            result.html_len = len(result.html_code)
            result.css_len = len(result.css_code)
            result.js_len = len(result.js_code)
            result.js_quality = _check_js_quality(result.js_code)
        else:
            result.error = "No interactive-content event"
    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
    finally:
        iskill.generate_interactive_stream = _original_gen
        _csettings.get_settings().strong_model = orig_strong

    return result


async def main() -> None:
    from main import app
    from services.java_client import get_java_client

    java = get_java_client()
    await java.start()

    results: list[RunResult] = []
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=300) as client:
            print("=" * 70)
            print("  A/B Test: JS model for interactive content")
            print("  HTML/CSS: qwen-max (both runs)")
            print("  JS:       glm-4.7  vs  qwen3-coder-plus")
            print("=" * 70)

            for label, model_map in AB_CONFIGS.items():
                print(f"\n--- {label} (JS: {model_map['js']}) ---")
                r = await _run_one(client, label, model_map)
                results.append(r)
                if r.error:
                    print(f"  ERROR: {r.error}")
                else:
                    print(f"  {r.summary_line()}")

            # Comparison
            print("\n" + "=" * 70)
            print("  COMPARISON")
            print("=" * 70)
            for r in results:
                print(f"  {r.summary_line()}")

            print()
            r0, r1 = results[0], results[1]
            if r0.error or r1.error:
                print("  INCONCLUSIVE — one or both failed")
            else:
                q0 = r0.js_quality
                q1 = r1.js_quality
                print(f"  {'Check':<25} {'glm-4.7':>12} {'qwen3-coder':>12}")
                print(f"  {'-'*49}")
                all_keys = sorted(set(q0) | set(q1))
                for k in all_keys:
                    v0, v1 = q0.get(k, "?"), q1.get(k, "?")
                    flag = "  <<<" if v0 != v1 else ""
                    print(f"  {k:<25} {str(v0):>12} {str(v1):>12}{flag}")

                # Verdict
                print()
                s0 = q0.get("runnable_score", 0)
                s1 = q1.get("runnable_score", 0)
                winner = r0.label if s0 > s1 else r1.label if s1 > s0 else "tie"
                faster = r0.label if r0.duration_s < r1.duration_s else r1.label
                print(f"  Quality:  glm-4.7={s0}, qwen3-coder={s1}")
                print(f"  Speed:    glm-4.7={r0.duration_s}s, qwen3-coder={r1.duration_s}s")
                print(f"  JS size:  glm-4.7={r0.js_len:,}, qwen3-coder={r1.js_len:,}")
                print()
                if s0 >= 0.8 and s1 >= 0.8:
                    print(f"  VERDICT: Both quality OK. Faster={faster}")
                    if abs(r0.duration_s - r1.duration_s) < 5:
                        print(f"  RECOMMENDATION: Similar speed; pick by JS quality/size")
                    else:
                        print(f"  RECOMMENDATION: Use {faster} (faster with good quality)")
                elif s0 >= 0.8:
                    print(f"  VERDICT: glm-4.7 quality better ({s0} vs {s1})")
                    print(f"  RECOMMENDATION: Use glm-4.7 for JS")
                elif s1 >= 0.8:
                    print(f"  VERDICT: qwen3-coder quality better ({s1} vs {s0})")
                    print(f"  RECOMMENDATION: Use qwen3-coder-plus for JS")
                else:
                    print(f"  VERDICT: Both below quality threshold")

    finally:
        await java.close()

    # Save
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "prompt": PROMPT,
        "results": [{
            "label": r.label, "js_model": r.js_model,
            "duration_s": r.duration_s, "http_status": r.http_status,
            "event_count": r.event_count,
            "html_len": r.html_len, "css_len": r.css_len, "js_len": r.js_len,
            "total_len": r.total_len,
            "js_quality": r.js_quality, "error": r.error,
        } for r in results],
        "js_code_samples": {
            r.label: r.js_code[:3000] for r in results
        },
    }
    out = Path("docs/testing/interactive-ab-glm47-vs-qwen3coder.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Saved: {out}")

    # Save standalone HTML files for browser verification
    CDN_LIBS = """
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/matter-js@0.19/build/matter.min.js"></script>
    """
    for r in results:
        if r.error or not r.html_code:
            continue
        html_page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>A/B Test — {r.label}</title>
{CDN_LIBS}
<style>
{r.css_code}
</style>
</head>
<body>
{r.html_code}
<script>
{r.js_code}
</script>
</body>
</html>"""
        html_out = Path(f"docs/testing/ab-verify-{r.label}.html")
        html_out.write_text(html_page, encoding="utf-8")
        print(f"  HTML: {html_out}")


if __name__ == "__main__":
    asyncio.run(main())
