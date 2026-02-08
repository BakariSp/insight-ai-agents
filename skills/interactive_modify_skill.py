"""Interactive content incremental modification skill.

Takes existing HTML + CSS + JS and a modification instruction, produces
a targeted update via a single LLM call instead of regenerating all
three streams from scratch.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

from pydantic_ai import Agent

from agents.provider import create_model, get_model_for_tier
from config.settings import get_settings

logger = logging.getLogger(__name__)

MODIFY_SYSTEM_PROMPT = """\
You are an expert at modifying interactive educational HTML content.
You will receive the CURRENT HTML, CSS, and JS of an interactive web page,
along with a modification request from a teacher.

Your task is to apply the requested modification precisely while preserving
all existing functionality that is not affected by the change.

## Rules

1. Only modify the parts that need to change. If only CSS needs updating
   (e.g. color changes), keep HTML and JS exactly as they are.
2. Always output COMPLETE file contents for each changed stream —
   not diffs or partial snippets.
3. For unchanged streams, output them exactly as provided.
4. Output ONLY a JSON object with this structure:
   {
     "changed": ["css"],          // list of streams that were modified
     "html": "... full html ...", // always include all three
     "css": "... full css ...",
     "js": "... full js ..."
   }
5. Do NOT wrap output in markdown code blocks.
6. Use Chinese for any new user-facing labels when the existing content is in Chinese.
7. Preserve all existing element IDs and classes referenced by other streams.
"""


async def modify_interactive_stream(
    current_html: str,
    current_css: str,
    current_js: str,
    modification_request: str,
    title: str = "",
) -> AsyncGenerator[dict, None]:
    """Modify existing interactive content via a single LLM call.

    Yields events compatible with the interactive content SSE protocol:
      {"type": "start", ...}
      {"type": "complete", "html": ..., "css": ..., "js": ..., ...}
    """
    settings = get_settings()
    model_name = get_model_for_tier("code")

    user_prompt = f"""\
## Modification Request
{modification_request}

## Current Content Title
{title}

## Current HTML
```html
{current_html}
```

## Current CSS
```css
{current_css}
```

## Current JS
```javascript
{current_js}
```

Apply the modification request above. Output ONLY the JSON object as specified."""

    yield {
        "type": "start",
        "title": title,
        "description": f"Modifying: {modification_request[:100]}",
        "phases": ["modify"],
    }

    try:
        model = create_model(model_name)
        agent = Agent(
            model=model,
            output_type=str,
            system_prompt=MODIFY_SYSTEM_PROMPT,
            retries=1,
            defer_model_check=True,
        )

        result = await agent.run(
            user_prompt,
            model_settings={"max_tokens": settings.agent_max_tokens},
        )
        raw_output = result.output

        # Parse the JSON output
        parsed = _parse_modify_output(raw_output, current_html, current_css, current_js)

        yield {
            "type": "complete",
            "html": parsed["html"],
            "css": parsed["css"],
            "js": parsed["js"],
            "title": title,
            "description": f"Modified: {modification_request[:100]}",
            "changed": parsed.get("changed", []),
            "preferredHeight": 500,
        }

    except Exception as e:
        logger.exception("Interactive content modification failed: %s", e)
        # Fallback: return original content unchanged
        yield {
            "type": "complete",
            "html": current_html,
            "css": current_css,
            "js": current_js,
            "title": title,
            "description": f"Modification failed: {e}",
            "changed": [],
            "preferredHeight": 500,
        }


def _parse_modify_output(
    raw: str,
    fallback_html: str,
    fallback_css: str,
    fallback_js: str,
) -> dict:
    """Parse the LLM's JSON output, with fallbacks for malformed output."""
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
        return {
            "changed": data.get("changed", ["html", "css", "js"]),
            "html": data.get("html", fallback_html),
            "css": data.get("css", fallback_css),
            "js": data.get("js", fallback_js),
        }
    except json.JSONDecodeError:
        logger.warning("Failed to parse modify output as JSON, using as-is")
        # If the LLM just output raw code, treat it as full replacement
        return {
            "changed": ["html", "css", "js"],
            "html": text if "<" in text else fallback_html,
            "css": fallback_css,
            "js": fallback_js,
        }
