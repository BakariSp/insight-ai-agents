"""Interactive HTML — three-stream parallel generator.

Generates HTML, CSS, and JS in parallel using three concurrent LLM calls,
yielding delta events as content arrives. This replaces the monolithic
single-call `generate_interactive_html` approach, reducing perceived
latency from ~90s to progressive rendering starting at ~5s.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

from pydantic_ai import Agent

from agents.provider import create_model, get_model_for_tier
from config.settings import get_settings

logger = logging.getLogger(__name__)

# ── System Prompts ───────────────────────────────────────────────

HTML_SYSTEM_PROMPT = """\
You are an HTML structure generator for educational interactive content.
Output ONLY raw HTML body content (no <!DOCTYPE>, no <html>, no <head>, no <body> tags).
Write semantic, accessible HTML with proper element IDs and classes as specified in the Element Contract.
Use Chinese text for UI labels when the content is for Chinese-speaking students.
Include placeholder containers (divs with IDs) for interactive elements that JS will initialize.
Do NOT include any CSS or JavaScript — those are handled separately.
Do NOT wrap output in markdown code blocks. Output raw HTML only.

IMPORTANT — keep it concise:
- Generate a clean, functional MVP structure. The teacher can request refinements later.
- Prefer fewer wrapper divs. Avoid deeply nested structures.
- For text content, write brief placeholder text rather than full paragraphs.
- Target ~100-200 lines of HTML, not 300+.
"""

CSS_SYSTEM_PROMPT = """\
You are a CSS style generator for educational interactive content.
Output ONLY raw CSS rules (no <style> tags, no markdown code blocks).
Reference ONLY the element IDs and classes from the Element Contract.
Do NOT output any HTML or JavaScript.

Style approach — clean and functional first:
- Define CSS variables for primary/secondary colors at :root
- Use flexbox/grid for layout
- Clean typography, readable font sizes
- Rounded corners (border-radius: 8px), subtle box-shadows
- ONE hover transition per interactive element (transition: 0.2s ease)
- Basic responsive design (one @media breakpoint at 768px)

Keep it lean:
- Do NOT add @keyframes animations unless the Element Contract specifically lists "animation" sections.
- Do NOT write extensive gradient layers or decorative pseudo-elements.
- Target ~100-150 lines of CSS. The teacher can request visual enhancements later.
"""

JS_SYSTEM_PROMPT = """\
You are a JavaScript generator for educational interactive content.
Output ONLY raw JavaScript code (no <script> tags, no markdown code blocks).
Reference ONLY the element IDs and classes from the Element Contract.
Do NOT output any HTML or CSS.
Do NOT use import/export statements (code runs in a script tag).

Coding approach:
- Use const/let, arrow functions, template literals (ES6+)
- Wrap everything in a DOMContentLoaded listener
- Initialize all interactive elements from the Element Contract
- Add event listeners for user interactions (click, drag, input, range)
- Use requestAnimationFrame for animations
- Handle errors gracefully (try/catch around DOM queries)

CDN libraries available (pre-loaded in the page <head>):
- Chart.js: `new Chart(ctx, config)` — for charts, graphs, data visualization
- MathJax: `MathJax.typeset()` — for rendering LaTeX/math expressions
- Matter.js: `Matter.Engine.create()` — for physics simulations with rigid bodies

When a library fits the task, USE it instead of hand-coding equivalent logic.
When no library fits (e.g. custom geometry, freeform canvas drawing, bespoke drag logic),
write vanilla JS — that is perfectly fine.

Keep it focused:
- Implement CORE interactivity only. The teacher will iterate on details.
- Target ~150-250 lines of JS, not 400+. Concise code is better code.
"""


# ── Element Contract Builder ─────────────────────────────────────


def _build_element_contract(plan: dict) -> str:
    """Build a shared element contract for HTML/CSS/JS generators."""
    sections = plan.get("sections", [])
    contract_lines = [
        "Element Contract (all generators must use these exact IDs/classes):"
    ]
    for sec in sections:
        sec_id = sec.get("id", "")
        sec_type = sec.get("type", "")
        sec_desc = sec.get("desc", "")
        contract_lines.append(f"  - #{sec_id} ({sec_type}): {sec_desc}")

    css_classes = plan.get("cssClasses", [])
    if css_classes:
        contract_lines.append(f"  CSS classes: {', '.join(css_classes)}")

    interactions = plan.get("interactions", [])
    if interactions:
        contract_lines.append(f"  Interactions: {', '.join(interactions)}")

    return "\n".join(contract_lines)


# ── Prompt Builders ──────────────────────────────────────────────


def _build_html_prompt(plan: dict, contract: str) -> str:
    title = plan.get("title", "Interactive Content")
    description = plan.get("description", "")
    topics = plan.get("topics", [])
    grade = plan.get("gradeLevel", "")
    subject = plan.get("subject", "")
    style = plan.get("style", "modern")
    features = plan.get("includeFeatures", [])

    return f"""Generate the HTML body structure for: {title}
Description: {description}
Topics: {', '.join(topics)}
Grade: {grade}, Subject: {subject}, Style: {style}
Features: {', '.join(features)}

{contract}

Requirements:
- Create all section containers with exact IDs from the contract
- Add headings, form elements (input[type=range], buttons) as appropriate
- Include <canvas> or placeholder divs for charts/simulations
- Use semantic HTML5 elements
- Add data attributes for JS initialization where needed
- Keep structure minimal — avoid excessive wrapper divs
- Output ONLY raw HTML (no doctype, no html/head/body tags)
"""


def _build_css_prompt(plan: dict, contract: str) -> str:
    title = plan.get("title", "Interactive Content")
    style = plan.get("style", "modern")
    features = plan.get("includeFeatures", [])

    style_guides = {
        "modern": "Clean lines, blue/indigo palette (#4f46e5), rounded corners, subtle shadows",
        "playful": "Bright colors, large rounded elements, cheerful palette",
        "scientific": "Precise layout, monospace for data, neutral palette, grid-based",
    }
    style_desc = style_guides.get(style, style_guides["modern"])

    return f"""Generate CSS styles for: {title}
Visual style: {style} — {style_desc}
Features: {', '.join(features)}

{contract}

Requirements:
- Style ALL elements from the contract
- Define :root CSS variables for colors
- Add hover states for interactive elements
- One @media (max-width: 768px) for mobile
- Output ONLY raw CSS rules
"""


def _build_js_prompt(plan: dict, contract: str) -> str:
    title = plan.get("title", "Interactive Content")
    description = plan.get("description", "")
    topics = plan.get("topics", [])
    features = plan.get("includeFeatures", [])
    sections = plan.get("sections", [])

    section_desc = "\n".join(
        f"  - #{s.get('id')}: {s.get('type')} — {s.get('desc')}"
        for s in sections
    )

    # Detect which CDN libraries the JS should leverage
    all_types = {s.get("type", "") for s in sections}
    all_features = set(features)
    lib_hints = []
    if all_types & {"chart", "graph"} or all_features & {"chart"}:
        lib_hints.append("- Chart.js is loaded: use `new Chart(ctx, config)` for charts/graphs")
    if all_types & {"simulation", "physics"} or all_features & {"simulation", "physics"}:
        lib_hints.append("- Matter.js is loaded: use `Matter.Engine.create()` for physics simulations")
    if all_features & {"animation", "creative", "drawing"}:
        lib_hints.append("- p5.js is loaded: use p5 instance mode for creative animations")
    # Math rendering is almost always useful for educational content
    lib_hints.append("- MathJax is loaded: call `MathJax.typeset()` after inserting math expressions")
    lib_section = "\n".join(lib_hints) if lib_hints else ""

    return f"""Generate JavaScript for: {title}
Description: {description}
Topics: {', '.join(topics)}
Features: {', '.join(features)}

Interactive sections:
{section_desc}

{contract}

CDN libraries available in the page (use when they fit, skip when they don't):
{lib_section}

Requirements:
- Wrap code in DOMContentLoaded listener
- Initialize all interactive elements from the contract
- Implement the described interactions (sliders, drag-drop, quizzes, animations)
- Use requestAnimationFrame for smooth animations
- Add proper event listeners and cleanup
- Handle errors gracefully (try/catch around DOM queries)
- Output ONLY raw JavaScript (no script tags)
- Do NOT use ES modules (import/export) — code runs inline
"""


# ── Height Estimation ────────────────────────────────────────────


def _estimate_height(html: str) -> int:
    """Estimate a reasonable iframe height from the HTML content."""
    line_count = html.count("\n") + 1
    has_canvas = "canvas" in html.lower() or "simulation" in html.lower()
    has_chart = "chart" in html.lower()

    if has_canvas or has_chart:
        return max(600, min(line_count * 8, 900))
    return max(500, min(line_count * 6, 800))


# ── Core: Three-stream parallel generator ────────────────────────


async def generate_interactive_stream(
    plan: dict,
    teacher_context: dict | None = None,
) -> AsyncGenerator[dict, None]:
    """Three-stream parallel generator for interactive HTML content.

    Yields events in this order:
      {"type": "start", "title": ..., "description": ..., "phases": ["html","css","js"]}
      {"type": "html-delta", "content": "<div..."}
      {"type": "css-delta",  "content": ".container{..."}
      {"type": "js-delta",   "content": "function init(){..."}
      {"type": "html-complete"}
      {"type": "css-complete"}
      {"type": "js-complete"}
      {"type": "complete", "html": full_body, "css": full_css, "js": full_js, ...}
    """
    yield {
        "type": "start",
        "title": plan.get("title", "Interactive Content"),
        "description": plan.get("description", ""),
        "phases": ["html", "css", "js"],
    }

    contract = _build_element_contract(plan)
    settings = get_settings()

    # All three phases use code tier (qwen3-coder-plus) —
    # A/B test showed it produces more complete structure and richer interactivity.
    model_for_phase = {
        "html": get_model_for_tier("code"),
        "css": get_model_for_tier("code"),
        "js": get_model_for_tier("code"),
    }

    # Three parallel generators writing to a shared asyncio.Queue
    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

    async def _gen_stream(
        phase: str, system_prompt: str, user_prompt: str
    ) -> None:
        """Run one LLM stream and push deltas to the shared queue."""
        try:
            model = create_model(model_for_phase[phase])
            agent = Agent(
                model=model,
                output_type=str,
                system_prompt=system_prompt,
                retries=1,
                defer_model_check=True,
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
            logger.exception("Interactive %s generation failed: %s", phase, e)
            # Still signal completion with whatever we have
            await queue.put((f"{phase}-complete", ""))

    # Launch all three in parallel
    tasks = [
        asyncio.create_task(
            _gen_stream("html", HTML_SYSTEM_PROMPT, _build_html_prompt(plan, contract))
        ),
        asyncio.create_task(
            _gen_stream("css", CSS_SYSTEM_PROMPT, _build_css_prompt(plan, contract))
        ),
        asyncio.create_task(
            _gen_stream("js", JS_SYSTEM_PROMPT, _build_js_prompt(plan, contract))
        ),
    ]

    completed: set[str] = set()
    full: dict[str, str] = {"html": "", "css": "", "js": ""}

    while len(completed) < 3:
        try:
            msg_type, content = await asyncio.wait_for(queue.get(), timeout=120)
        except asyncio.TimeoutError:
            logger.error("Interactive generation timed out after 120s")
            break

        if msg_type.endswith("-delta"):
            yield {"type": msg_type, "content": content}
        elif msg_type.endswith("-complete"):
            phase = msg_type.replace("-complete", "")
            full[phase] = content
            completed.add(phase)
            yield {"type": msg_type}

    # Ensure all tasks complete cleanly
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    yield {
        "type": "complete",
        "html": full["html"],
        "css": full["css"],
        "js": full["js"],
        "title": plan.get("title", "Interactive Content"),
        "description": plan.get("description", ""),
        "preferredHeight": _estimate_height(full["html"]),
    }
