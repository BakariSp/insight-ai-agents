"""Stream adapter — PydanticAI events → Data Stream Protocol SSE.

Step 1.3 of AI native rewrite.  Converts PydanticAI's ``stream_responses()``
output into Vercel AI SDK Data Stream Protocol SSE lines consumed by the
frontend ``useChat`` hook.

Implementation is based on the Step 0.5 calibrated event mapping
(see ``docs/plans/stream-event-mapping.md``).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncIterator

from pydantic_ai.messages import (
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    ModelRequest,
)
from pydantic_ai.result import StreamedRunResult

from models.errors import classify_stream_error
from services.datastream import DataStreamEncoder

logger = logging.getLogger(__name__)


def _parse_tabs_from_markdown(markdown_content: str) -> dict | None:
    """
    Parse [TAB:key] markers from markdown and build AIReportResponse structure.

    Args:
        markdown_content: Full markdown content with tab markers

    Returns:
        dict with {layout: "tabs", tabs: [...]} structure, or None if no tabs found
    """
    import re

    # Pattern: ## [TAB:key] label
    tab_pattern = re.compile(r"^## \[TAB:(\w+)\] (.+)$", re.MULTILINE)

    matches = list(tab_pattern.finditer(markdown_content))

    if not matches:
        return None  # No tabs found, use default rendering

    tabs = []
    for i, match in enumerate(matches):
        tab_key = match.group(1)
        tab_label = match.group(2)

        # Extract content between this tab and next tab
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown_content)

        content = markdown_content[start:end].strip()

        # MVP: wrap content as single MarkdownBlock
        tabs.append(
            {
                "key": tab_key,
                "label": tab_label,
                "blocks": [
                    {
                        "type": "markdown",
                        "content": content,
                    }
                ],
            }
        )

    return {
        "layout": "tabs",
        "tabs": tabs,
    }


async def adapt_stream(
    stream: StreamedRunResult,
    enc: DataStreamEncoder,
    message_id: str | None = None,
    pre_text: str | None = None,
    context: dict | None = None,
) -> AsyncIterator[str]:
    """Convert PydanticAI stream into Data Stream Protocol SSE lines.

    Uses ``stream_responses()`` which yields ``(ModelResponse, is_last)`` tuples.
    We diff successive response snapshots to emit incremental SSE events.

    Args:
        stream: PydanticAI StreamedRunResult (inside async with context).
        enc: DataStreamEncoder instance for SSE formatting.
        message_id: Optional message ID for the start event.
        pre_text: Optional acknowledgment text emitted immediately before the
            LLM stream begins.  This gives the user instant feedback (e.g.
            "好的，正在为您生成...") without depending on the LLM to produce
            text alongside tool calls in the same response.
        context: Optional context dict (may contain blueprint_hints for tab parsing)

    Yields:
        SSE-formatted strings ready for StreamingResponse.
    """
    yield enc.start(message_id=message_id)
    yield enc.start_step()

    # Inject immediate acknowledgment text before LLM stream starts
    if pre_text:
        ack_id = "t-ack"
        yield enc.text_start(ack_id)
        yield enc.text_delta(ack_id, pre_text)
        yield enc.text_end(ack_id)

    # Track state for incremental diffing
    prev_text_len: dict[int, int] = {}  # part_index → last seen text length
    emitted_tool_start: set[int] = set()  # part indices where we emitted tool-input-start
    emitted_tool_input: set[int] = set()  # part indices where we emitted tool-input-available
    emitted_call_ids: dict[int, str] = {}  # part_index → the call_id we actually emitted
    real_to_emitted: dict[str, str] = {}  # real tool_call_id → emitted call_id
    text_ids: dict[int, str] = {}  # part_index → text-id for SSE
    text_started: set[int] = set()  # part indices where we emitted text-start
    text_ended: set[int] = set()  # part indices where we already emitted text-end

    # Collect full text content for tab parsing
    full_text_parts: dict[int, list[str]] = {}

    error_occurred = False

    try:
        async for response, is_last in stream.stream_responses():
            for idx, part in enumerate(response.parts):
                if isinstance(part, TextPart):
                    # ── Text streaming ──
                    text_id = text_ids.setdefault(idx, f"t-{idx}")

                    if idx not in text_started:
                        yield enc.text_start(text_id)
                        text_started.add(idx)

                    current_len = len(part.content)
                    prev_len = prev_text_len.get(idx, 0)

                    if current_len > prev_len:
                        delta = part.content[prev_len:]
                        yield enc.text_delta(text_id, delta)
                        prev_text_len[idx] = current_len

                    # Collect full text content for tab parsing
                    if idx not in full_text_parts:
                        full_text_parts[idx] = []
                    full_text_parts[idx] = [part.content]

                elif isinstance(part, ToolCallPart):
                    # Close any preceding text parts before starting tool call
                    for tidx in text_started - text_ended:
                        yield enc.text_end(text_ids[tidx])
                        text_ended.add(tidx)

                    # ── Tool call streaming ──
                    # Lock the call_id on first emission to avoid mismatches:
                    # tool_call_id may be None in early snapshots, populated later.
                    if idx not in emitted_call_ids:
                        call_id = part.tool_call_id or f"tc-{idx}"
                        emitted_call_ids[idx] = call_id
                    call_id = emitted_call_ids[idx]

                    # Track real → emitted mapping for tool-output-available
                    if part.tool_call_id and part.tool_call_id not in real_to_emitted:
                        real_to_emitted[part.tool_call_id] = call_id

                    if idx not in emitted_tool_start:
                        yield enc.tool_input_start(call_id, part.tool_name)
                        emitted_tool_start.add(idx)

                    # Emit tool-input-available when args are complete
                    if part.args and idx not in emitted_tool_input:
                        args = part.args if isinstance(part.args, dict) else {}
                        yield enc.tool_input_available(call_id, part.tool_name, args)
                        emitted_tool_input.add(idx)

        # After streaming completes, emit tool calls and results from new_messages.
        # This catches ToolCallParts not seen during stream_responses() (common
        # with LiteLLM providers) and emits tool-input-start/available for them.
        for msg in stream.new_messages():
            if isinstance(msg, ModelResponse):
                for part in msg.parts:
                    if isinstance(part, ToolCallPart):
                        raw_id = part.tool_call_id or f"tc-post-{uuid.uuid4().hex[:6]}"
                        call_id = real_to_emitted.get(raw_id, raw_id)
                        # Register mapping if new
                        if part.tool_call_id and part.tool_call_id not in real_to_emitted:
                            real_to_emitted[part.tool_call_id] = call_id

                        # Only emit if not already emitted during streaming
                        if call_id not in {emitted_call_ids.get(i) for i in emitted_tool_start}:
                            # Close any open text parts first
                            for tidx in text_started - text_ended:
                                yield enc.text_end(text_ids[tidx])
                                text_ended.add(tidx)

                            yield enc.tool_input_start(call_id, part.tool_name)
                            args = part.args if isinstance(part.args, dict) else {}
                            yield enc.tool_input_available(call_id, part.tool_name, args)

            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, ToolReturnPart):
                        raw_id = part.tool_call_id or uuid.uuid4().hex[:8]
                        call_id = real_to_emitted.get(raw_id, raw_id)
                        output = _serialize_tool_output(part.content)
                        yield enc.tool_output_available(call_id, output)

                        # Emit semantic data-* events based on tool output
                        for line in _emit_semantic_events(enc, output):
                            yield line

        # Close any text parts still open after stream completes
        for tidx in text_started - text_ended:
            yield enc.text_end(text_ids[tidx])
            text_ended.add(tidx)

        # After stream completes, check if we should emit data-page
        if context and context.get("blueprint_hints"):
            hints = context["blueprint_hints"]
            expected_artifacts = hints.get("expectedArtifacts", [])

            # Only process tabs for "report" artifact type
            if "report" in expected_artifacts and full_text_parts:
                # Combine all text parts
                all_text = []
                for idx in sorted(full_text_parts.keys()):
                    all_text.extend(full_text_parts[idx])
                full_text = "".join(all_text)

                tab_structure = _parse_tabs_from_markdown(full_text)

                if tab_structure:
                    # Emit data-page event with tab structure
                    yield enc.data("page", tab_structure)

                    logger.info("Emitted data-page with %d tabs", len(tab_structure["tabs"]))

    except Exception as e:
        error_occurred = True
        logger.exception("Error during stream adaptation")
        yield enc.error(classify_stream_error(str(e)))

    finally:
        yield enc.finish_step()
        yield enc.finish("error" if error_occurred else "stop")


def _serialize_tool_output(content: Any) -> Any:
    """Ensure tool output is JSON-serializable."""
    if isinstance(content, str):
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return content
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        return content
    return str(content)


def _emit_semantic_events(
    enc: DataStreamEncoder, output: Any
) -> list[str]:
    """Inspect tool output and return semantic data-* SSE events.

    Maps ``artifact_type`` / ``status`` in tool outputs to the frontend's
    expected ``data-quiz-question``, ``data-file-ready``,
    ``data-interactive-content``, ``data-pptx-outline``, etc.
    """
    if not isinstance(output, dict):
        return []
    if output.get("status") == "error":
        return []

    lines: list[str] = []
    artifact_type = output.get("artifact_type", "")
    status = output.get("status", "")

    # ── Quiz completion signal ──
    # Individual quiz-question events are already streamed incrementally
    # via ToolTracker (see quiz_tools.py).  Only emit the completion
    # signal here to avoid sending every question twice.
    if artifact_type == "quiz" and status == "ok":
        lines.append(enc.data("quiz-complete", {
            "total": output.get("total", len(output.get("questions", []))),
        }))

    # ── Quiz replace (single question refinement) ──
    elif status == "replaced":
        lines.append(enc.data("quiz-replace", {
            "index": output.get("target_index", 0),
            "question": output.get("question", {}),
        }))

    # ── PPT outline proposal ──
    elif status == "proposed":
        lines.append(enc.data("pptx-outline", {
            "title": output.get("title", ""),
            "outline": output.get("outline", []),
            "totalSlides": output.get("totalSlides", 0),
            "estimatedDuration": output.get("estimatedDuration", 0),
            "requiresConfirmation": True,
        }))

    # ── File ready (PPTX / DOCX / PDF with URL) ──
    elif artifact_type in ("pptx", "document") and output.get("url"):
        # Determine file type from artifact_type and filename
        filename = output.get("filename", "")
        if artifact_type == "pptx" or filename.endswith(".pptx"):
            file_type = "pptx"
        elif filename.endswith(".docx"):
            file_type = "docx"
        elif filename.endswith(".pdf"):
            file_type = "pdf"
        else:
            file_type = artifact_type
        lines.append(enc.data("file-ready", {
            "type": file_type,
            "url": output["url"],
            "filename": filename,
            "size": output.get("size"),
            "preview": {
                "pageCount": output.get("slide_count"),
            },
        }))

    # ── Interactive content (complete HTML) ──
    elif artifact_type == "interactive" and output.get("html"):
        lines.append(enc.data("interactive-content", {
            "html": output["html"],
            "title": output.get("title", ""),
            "description": output.get("description", ""),
            "preferredHeight": output.get("preferredHeight", 500),
        }))

    # ── Clarify action ──
    elif output.get("action") == "clarify" and output.get("clarify"):
        clarify = output["clarify"]
        lines.append(enc.data("clarify", {
            "choices": clarify.get("options", []),
        }))

    # ── RAG search sources (citation transparency) ──
    # Emitted for any tool that returns a non-empty "sources" list,
    # typically search_teacher_documents.
    sources = output.get("sources")
    if sources and isinstance(sources, list) and len(sources) > 0:
        lines.append(enc.data("rag-sources", {
            "query": output.get("query", ""),
            "sources": sources,
            "total": output.get("total", 0),
        }))

    return lines


def extract_tool_calls_summary(result: Any) -> str | None:
    """Extract a brief summary of tool calls from a PydanticAI result.

    Inspects ``result.new_messages()`` (or ``result.all_messages()``) for
    ToolCallPart and ToolReturnPart to build a compact summary like::

        generate_quiz_questions(topic=英语, count=5) → ok; patch_artifact(op=replace) → ok

    Returns ``None`` if no tool calls were made.
    """
    try:
        messages = result.new_messages() if hasattr(result, "new_messages") else []
    except Exception:
        try:
            messages = result.all_messages() if hasattr(result, "all_messages") else []
        except Exception:
            return None

    calls: list[str] = []
    # Collect tool calls and their results
    call_map: dict[str, str] = {}  # tool_call_id → tool_name(args_summary)
    result_map: dict[str, str] = {}  # tool_call_id → status

    for msg in messages:
        if not hasattr(msg, "parts"):
            continue
        for part in msg.parts:
            if isinstance(part, ToolCallPart):
                call_id = part.tool_call_id or ""
                args_str = ""
                if isinstance(part.args, dict) and part.args:
                    # Keep only first 2 args for brevity
                    items = list(part.args.items())[:2]
                    args_str = ", ".join(f"{k}={v}" for k, v in items)
                call_map[call_id] = f"{part.tool_name}({args_str})"
            elif isinstance(part, ToolReturnPart):
                call_id = part.tool_call_id or ""
                status = "ok"
                if isinstance(part.content, dict):
                    status = str(part.content.get("status", "ok"))
                elif isinstance(part.content, str) and "error" in part.content.lower():
                    status = "error"
                result_map[call_id] = status

    for call_id, call_desc in call_map.items():
        status = result_map.get(call_id, "ok")
        calls.append(f"{call_desc} → {status}")

    return "; ".join(calls) if calls else None
