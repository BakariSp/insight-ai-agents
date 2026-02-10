"""Native tool registrations for Step 2 tool convergence."""

from __future__ import annotations

import copy
import json
import logging
from typing import Annotated, Any

from pydantic import BeforeValidator
from pydantic_ai import RunContext

from agents.native_agent import AgentDeps
from models.tool_contracts import ClarifyChoice, ClarifyEvent
from services.artifact_store import get_artifact_store
from tools.registry import register_tool

logger = logging.getLogger(__name__)


def _coerce_json_str_to_list(v: Any) -> Any:
    """LLMs sometimes double-encode a JSON array as a string.

    e.g. the model sends ``types: '["a","b"]'`` instead of ``types: ["a","b"]``.
    This validator coerces the string back into a list so validation succeeds.
    """
    if isinstance(v, str):
        v = v.strip()
        if v.startswith("["):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
    return v


StrList = Annotated[list[str] | None, BeforeValidator(_coerce_json_str_to_list)]


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"status": "ok", **data}


def _error(reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": "error", "reason": reason, **extra}


def _is_error(result: dict[str, Any]) -> bool:
    """Detect error from underlying tools.

    data_tools return ``{"status": "error", "reason": ...}`` on failure,
    while some legacy paths use ``{"error": "..."}``  — handle both.
    """
    if result.get("status") == "error":
        return True
    if result.get("error"):
        return True
    return False


def _forward_error(result: dict[str, Any]) -> dict[str, Any]:
    """Convert an underlying error result into a standard _error() envelope."""
    reason = result.get("reason") or result.get("error") or "unknown error"
    return _error(str(reason))


def _save_artifact(
    *,
    conversation_id: str,
    artifact_type: str,
    content_format: str,
    content: Any,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    artifact = get_artifact_store().save_artifact(
        conversation_id=conversation_id,
        artifact_type=artifact_type,
        content_format=content_format,
        content=content,
        artifact_id=artifact_id,
    )
    return {
        "artifact_id": artifact.artifact_id,
        "artifact_type": artifact.artifact_type,
        "content_format": artifact.content_format.value,
        "version": artifact.version,
    }


async def _modify_interactive_html(original_html: str, instruction: str) -> str:
    """Use the code model to modify interactive HTML based on a user instruction.

    Called by ``regenerate_from_previous`` when the artifact is interactive.
    The code model receives the original HTML and the modification request,
    then returns the complete modified HTML.
    """
    from pydantic_ai import Agent
    from pydantic_ai.settings import ModelSettings
    from agents.provider import create_model, get_model_for_tier

    model = create_model(get_model_for_tier("code"))
    agent: Agent[None, str] = Agent(
        model=model,
        system_prompt=(
            "You are an expert HTML/CSS/JavaScript developer.\n"
            "You will receive an existing HTML document and a modification instruction.\n"
            "Apply the requested change and return the COMPLETE modified HTML document.\n"
            "Rules:\n"
            "- Return ONLY the HTML code, no markdown fences, no explanation.\n"
            "- Keep the document self-contained (inline CSS/JS, CDN libs OK).\n"
            "- Preserve all existing functionality unless the instruction says otherwise.\n"
            "- If the instruction is ambiguous, make a reasonable choice."
        ),
        output_type=str,
    )
    result = await agent.run(
        f"## Original HTML\n```html\n{original_html}\n```\n\n"
        f"## Modification Request\n{instruction}",
        model_settings=ModelSettings(
            max_tokens=16384,
            extra_body={"enable_thinking": False},
        ),
    )
    modified = result.output

    # Strip markdown code fences if the model wrapped the output
    if modified.startswith("```"):
        lines = modified.split("\n")
        # Remove first line (```html) and last line (```)
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        elif lines[0].startswith("```"):
            lines = lines[1:]
        modified = "\n".join(lines)

    return modified


# ---------------------------------------------------------------------------
# base_data (5)
# ---------------------------------------------------------------------------


@register_tool(toolset="base_data")
async def get_teacher_classes(ctx: RunContext[AgentDeps]) -> dict:
    """List all classes for the current teacher (SUMMARY ONLY).

    Returns class_id, name, grade, subject, student_count, assignment_count.
    Does NOT include student roster or assignment details.
    To get student names or assignment list, call get_class_detail with the class_id.
    """
    from tools.data_tools import get_teacher_classes as _get_classes

    teacher_id = ctx.deps.teacher_id
    if not teacher_id:
        return _error("teacher_id is required")
    result = await _get_classes(teacher_id=teacher_id)
    if _is_error(result):
        return _forward_error(result)
    return _ok({"classes": result.get("classes", [])})


@register_tool(toolset="base_data")
async def get_class_detail(ctx: RunContext[AgentDeps], class_id: str) -> dict:
    """Get full details for a specific class: student roster + assignment list.

    Returns student names/IDs, assignment titles/scores/due dates, and class metadata.
    Always call this when the user asks about a class's students or assignments.
    The class_id can be obtained from get_teacher_classes.
    """
    from tools.data_tools import get_class_detail as _get_detail

    teacher_id = ctx.deps.teacher_id
    if not teacher_id:
        return _error("teacher_id is required")
    result = await _get_detail(teacher_id=teacher_id, class_id=class_id)
    if _is_error(result):
        return _forward_error(result)
    return _ok(result)


@register_tool(toolset="base_data")
async def get_assignment_submissions(
    ctx: RunContext[AgentDeps],
    class_id: str,
    assignment_id: str,
) -> dict:
    """Get all student submissions and scores for a specific assignment.

    Returns per-student scores, submission status, and a raw scores array.
    The assignment_id can be obtained from get_class_detail.
    """
    from tools.data_tools import get_assignment_submissions as _get_subs

    teacher_id = ctx.deps.teacher_id
    if not teacher_id:
        return _error("teacher_id is required")
    result = await _get_subs(teacher_id=teacher_id, assignment_id=assignment_id)
    if _is_error(result):
        return _forward_error(result)
    result["class_id"] = class_id
    return _ok(result)


@register_tool(toolset="base_data")
async def get_student_grades(
    ctx: RunContext[AgentDeps],
    class_id: str,
    student_id: str,
) -> dict:
    """Get all grades for a specific student in a class.

    The student_id and class_id can be obtained from get_class_detail.
    """
    from tools.data_tools import get_student_grades as _get_grades

    teacher_id = ctx.deps.teacher_id
    if not teacher_id:
        return _error("teacher_id is required")
    result = await _get_grades(teacher_id=teacher_id, student_id=student_id)
    if _is_error(result):
        return _forward_error(result)
    result["class_id"] = class_id
    return _ok(result)


@register_tool(toolset="base_data")
async def resolve_entity(
    ctx: RunContext[AgentDeps],
    query: str,
) -> dict:
    """Resolve a natural-language entity reference (student name, class name) to IDs."""
    from services.entity_resolver import resolve_entities

    teacher_id = ctx.deps.teacher_id
    if not teacher_id:
        return _error("teacher_id is required")
    resolved = await resolve_entities(
        teacher_id=teacher_id,
        query_text=query,
        context=ctx.deps.context,
    )
    return _ok(resolved.model_dump(by_alias=True))


# ---------------------------------------------------------------------------
# analysis (5)
# ---------------------------------------------------------------------------


@register_tool(toolset="analysis")
async def calculate_stats(
    ctx: RunContext[AgentDeps],
    data: list[float],
    metrics: StrList = None,
) -> dict:
    """Compute descriptive statistics (mean, median, stdev, etc.) on a numeric dataset."""
    from tools.stats_tools import calculate_stats as _calc

    result = _calc(data=data, metrics=metrics)
    if _is_error(result):
        return _forward_error(result)
    return _ok(result)


@register_tool(toolset="analysis")
async def compare_performance(
    ctx: RunContext[AgentDeps],
    group_a: list[float],
    group_b: list[float],
    metrics: StrList = None,
) -> dict:
    """Compare two groups of scores and return comparative statistics."""
    from tools.stats_tools import compare_performance as _compare

    result = _compare(group_a=group_a, group_b=group_b, metrics=metrics)
    if _is_error(result):
        return _forward_error(result)
    return _ok(result)


@register_tool(toolset="analysis")
async def analyze_student_weakness(
    ctx: RunContext[AgentDeps],
    class_id: str,
    subject: str = "",
    submissions: list[dict[str, Any]] | None = None,
) -> dict:
    """Identify common weakness areas across students in a class."""
    from tools.assessment_tools import analyze_student_weakness as _analyze

    teacher_id = ctx.deps.teacher_id
    if not teacher_id:
        return _error("teacher_id is required")
    result = await _analyze(
        teacher_id=teacher_id,
        class_id=class_id,
        subject=subject,
        submissions=submissions,
    )
    return _ok(result)


@register_tool(toolset="analysis")
async def get_student_error_patterns(
    ctx: RunContext[AgentDeps],
    student_id: str,
    class_id: str = "",
    submissions: list[dict[str, Any]] | None = None,
) -> dict:
    """Detect recurring error patterns for a specific student."""
    from tools.assessment_tools import get_student_error_patterns as _patterns

    teacher_id = ctx.deps.teacher_id
    if not teacher_id:
        return _error("teacher_id is required")
    result = await _patterns(
        teacher_id=teacher_id,
        student_id=student_id,
        class_id=class_id,
        submissions=submissions,
    )
    return _ok(result)


@register_tool(toolset="analysis")
async def calculate_class_mastery(
    ctx: RunContext[AgentDeps],
    submissions: list[dict[str, Any]],
    knowledge_point_ids: StrList = None,
) -> dict:
    """Calculate mastery level per knowledge point from submission data."""
    from tools.assessment_tools import calculate_class_mastery as _mastery

    result = _mastery(
        submissions=submissions,
        knowledge_point_ids=knowledge_point_ids,
    )
    return _ok(result)


# ---------------------------------------------------------------------------
# generation (7)
# ---------------------------------------------------------------------------


@register_tool(toolset="generation")
async def generate_quiz_questions(
    ctx: RunContext[AgentDeps],
    topic: str,
    count: int = 10,
    difficulty: str = "medium",
    types: StrList = None,
    subject: str = "",
    grade: str = "",
    context: str = "",
) -> dict:
    """Generate quiz questions on a topic, returning a JSON artifact."""
    # Per-turn dedup: prevent LLM from calling this tool multiple times
    _tool_key = "generate_quiz_questions"
    if _tool_key in ctx.deps._called_gen_tools:
        return _ok({"message": "Quiz questions already generated in this turn. Use the existing result.", "duplicate": True})
    ctx.deps._called_gen_tools.add(_tool_key)

    from tools.quiz_tools import generate_quiz_questions as _generate

    result = await _generate(
        topic=topic,
        count=count,
        difficulty=difficulty,
        types=types,
        subject=subject,
        grade=grade,
        context=context,
    )
    artifact_meta = _save_artifact(
        conversation_id=ctx.deps.conversation_id,
        artifact_type="quiz",
        content_format="json",
        content=result,
    )
    return _ok({
        **result,
        **artifact_meta,
        "artifact_type": "quiz",
        "content_format": "json",
    })


@register_tool(toolset="generation")
async def propose_pptx_outline(
    ctx: RunContext[AgentDeps],
    title: str,
    outline: list[dict],
    total_slides: int = 0,
    estimated_duration: int = 0,
) -> dict:
    """Propose a slide-by-slide outline for a PPTX presentation."""
    from tools.render_tools import propose_pptx_outline as _outline

    result = await _outline(
        title=title,
        outline=outline,
        total_slides=total_slides,
        estimated_duration=estimated_duration,
    )
    artifact_meta = _save_artifact(
        conversation_id=ctx.deps.conversation_id,
        artifact_type="pptx",
        content_format="json",
        content=result,
    )
    return _ok({**result, **artifact_meta, "artifact_type": "pptx", "content_format": "json"})


@register_tool(toolset="generation")
async def generate_pptx(
    ctx: RunContext[AgentDeps],
    slides: list[dict],
    title: str = "Presentation",
    template: str = "education",
) -> dict:
    """Generate a PPTX file from a list of slide definitions.

    IMPORTANT: You must call propose_pptx_outline first and get teacher approval
    before calling this tool. If no outline has been proposed in this conversation,
    this tool will return an error.
    """
    # Enforce: outline must exist in this conversation before generating
    store = get_artifact_store()
    latest = store.get_latest_for_conversation(ctx.deps.conversation_id)
    if latest is None or latest.artifact_type != "pptx":
        return _error(
            "请先调用 propose_pptx_outline 提交大纲供教师确认，确认后再生成 PPT。"
        )

    from tools.render_tools import generate_pptx as _generate_pptx

    result = await _generate_pptx(slides=slides, title=title, template=template)
    artifact_meta = _save_artifact(
        conversation_id=ctx.deps.conversation_id,
        artifact_type="pptx",
        content_format="json",
        content=result,
    )
    return _ok({**result, **artifact_meta, "artifact_type": "pptx", "content_format": "json"})


@register_tool(toolset="generation")
async def generate_docx(
    ctx: RunContext[AgentDeps],
    content: str,
    title: str = "Document",
    format: str = "plain",
) -> dict:
    """Generate a DOCX document from text or markdown content."""
    from tools.render_tools import generate_docx as _generate_docx

    result = await _generate_docx(content=content, title=title, format=format)
    artifact_meta = _save_artifact(
        conversation_id=ctx.deps.conversation_id,
        artifact_type="document",
        content_format="markdown",
        content=content,
    )
    return _ok({**result, **artifact_meta, "artifact_type": "document", "content_format": "markdown"})


@register_tool(toolset="generation")
async def render_pdf(
    ctx: RunContext[AgentDeps],
    html_content: str,
    title: str = "Document",
    css_template: str = "default",
) -> dict:
    """Render HTML content to a PDF document."""
    from tools.render_tools import render_pdf as _render_pdf

    result = await _render_pdf(
        html_content=html_content,
        title=title,
        css_template=css_template,
    )
    artifact_meta = _save_artifact(
        conversation_id=ctx.deps.conversation_id,
        artifact_type="document",
        content_format="html",
        content=html_content,
    )
    return _ok({**result, **artifact_meta, "artifact_type": "document", "content_format": "html"})


@register_tool(toolset="generation")
async def generate_interactive_html(
    ctx: RunContext[AgentDeps],
    html: str,
    title: str = "Interactive Content",
    description: str = "",
    preferred_height: int | None = None,
) -> dict:
    """Generate an interactive HTML web page rendered live in the browser.

    Use this for interactive content, simulations, animations, drag-and-drop
    exercises, visual demos, or any web-based learning material.

    IMPORTANT: The HTML must be fully self-contained — ALL CSS must be in
    <style> tags (never <link>), ALL JS must be in <script> tags (never
    external src for your own code).  External CDN libs are OK (Chart.js,
    p5.js, D3.js, Three.js, Matter.js are pre-loaded).  Do NOT reference
    local files or relative URLs — they will fail to load.

    ## AI 实时对话功能 (可选)

    当教师要求生成可以 **实时对话、角色扮演、口语练习、AI 陪练** 等
    需要与 AI 交互的内容时，可以在 HTML 中调用平台预置的
    `InsightAI.chat()` 接口。该接口通过 postMessage 与平台 AI Agent
    通信，无需额外引入任何库。

    ### API
    ```js
    // 发送消息给 AI，返回 Promise<string>（AI 的回复文本）
    const reply = await InsightAI.chat(userMessage, {
      role: '角色名',           // AI 要扮演的角色，如 "English Teacher"
      scenario: '场景描述',     // 对话场景，如 "日常英语口语练习"
      instructions: '额外要求'  // 如 "用英语回复" / "用文言文" / "纠正语法错误"
    });
    ```

    ### 何时使用 / 不使用
    - ✅ "生成一个可以跟 AI 对话的英语练习" → 使用
    - ✅ "做一个历史角色扮演，学生可以跟诸葛亮对话" → 使用
    - ✅ "AI 口语陪练 / AI 写作助手" → 使用
    - ❌ "生成赤壁夜话对话展示" → 不使用，纯展示
    - ❌ "做一个物理模拟动画" → 不使用，无需对话

    ### 典型用法
    ```html
    <div id="chat-log"></div>
    <input id="user-input" placeholder="Type here...">
    <button onclick="send()">Send</button>
    <script>
    async function send() {
      var input = document.getElementById('user-input');
      var log = document.getElementById('chat-log');
      var text = input.value.trim();
      if (!text) return;
      log.innerHTML += '<p><b>You:</b> ' + text + '</p>';
      input.value = '';
      try {
        var reply = await InsightAI.chat(text, {
          role: 'English Teacher',
          scenario: 'Casual conversation practice',
          instructions: 'Reply in English. Gently correct grammar mistakes.'
        });
        log.innerHTML += '<p><b>Teacher:</b> ' + reply + '</p>';
      } catch(e) {
        log.innerHTML += '<p style="color:red">Failed: ' + e.message + '</p>';
      }
    }
    </script>
    ```
    """
    from tools.render_tools import generate_interactive_html as _interactive

    result = await _interactive(
        html=html,
        title=title,
        description=description,
        preferred_height=preferred_height,
    )
    artifact_meta = _save_artifact(
        conversation_id=ctx.deps.conversation_id,
        artifact_type="interactive",
        content_format="html",
        content=result["html"],
    )
    return _ok({**result, **artifact_meta, "artifact_type": "interactive", "content_format": "html"})


# NOTE: request_interactive_content is disabled — three-stream progressive
# rendering is not yet implemented.  The tool returned only planning metadata
# (no HTML), so the stream adapter never emitted a data-interactive-content
# event and the frontend saw nothing.  Re-enable when three-stream is built.
# See: render_tools.py:request_interactive_content


# ---------------------------------------------------------------------------
# artifact_ops (3)
# ---------------------------------------------------------------------------


def _get_path_tokens(path: str) -> list[str]:
    p = path.strip()
    if not p.startswith("/"):
        return []
    return [token for token in p.split("/")[1:] if token]


def _apply_json_patch(content: Any, operations: list[dict[str, Any]]) -> Any:
    """Apply a list of JSON Patch-like operations to *content*.

    Returns the patched content on success, or raises ``ValueError``
    with a human-readable message when a single operation fails.
    """
    patched = copy.deepcopy(content)
    for idx, op in enumerate(operations):
        action = str(op.get("op", "")).lower()
        path = str(op.get("path", ""))
        tokens = _get_path_tokens(path)
        if not tokens:
            continue
        try:
            parent = patched
            for token in tokens[:-1]:
                if isinstance(parent, list):
                    parent = parent[int(token)]
                else:
                    parent = parent[token]
            key = tokens[-1]

            if isinstance(parent, list):
                list_idx = int(key)
                if action == "remove":
                    parent.pop(list_idx)
                elif action == "add":
                    parent.insert(list_idx, op.get("value"))
                else:
                    parent[list_idx] = op.get("value")
            else:
                if action == "remove":
                    parent.pop(key, None)
                else:
                    parent[key] = op.get("value")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ValueError(
                f"patch operation {idx} failed (op={action!r}, path={path!r}): {exc}"
            ) from exc
    return patched


@register_tool(toolset="artifact_ops")
async def get_artifact(
    ctx: RunContext[AgentDeps],
    artifact_id: str = "",
) -> dict:
    """Retrieve an artifact by ID, or the latest artifact in the current conversation."""
    store = get_artifact_store()
    artifact = (
        store.get_artifact(artifact_id)
        if artifact_id
        else store.get_latest_for_conversation(ctx.deps.conversation_id)
    )
    if artifact is None:
        return _error("artifact not found")
    return _ok({
        "artifact_id": artifact.artifact_id,
        "artifact_type": artifact.artifact_type,
        "content_format": artifact.content_format.value,
        "content": artifact.content,
        "version": artifact.version,
    })


@register_tool(toolset="artifact_ops")
async def patch_artifact(
    ctx: RunContext[AgentDeps],
    artifact_id: str,
    operations: list[dict[str, Any]],
) -> dict:
    """Apply JSON Patch operations to modify an existing artifact in place."""
    store = get_artifact_store()
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        return _error("artifact not found", artifact_id=artifact_id)

    if artifact.content_format.value == "json":
        try:
            new_content = _apply_json_patch(artifact.content, operations)
        except ValueError as exc:
            return _error(str(exc), artifact_id=artifact_id)
    elif artifact.content_format.value in {"markdown", "html"}:
        if len(operations) == 1 and operations[0].get("path") == "/content":
            new_content = operations[0].get("value", artifact.content)
        else:
            return _error("text artifact only supports /content patch", artifact_id=artifact_id)
    else:
        return _error("unsupported content_format", content_format=artifact.content_format.value)

    saved = _save_artifact(
        conversation_id=ctx.deps.conversation_id,
        artifact_type=artifact.artifact_type,
        content_format=artifact.content_format.value,
        content=new_content,
        artifact_id=artifact.artifact_id,
    )
    return _ok({
        **saved,
        "artifact_type": artifact.artifact_type,
        "content_format": artifact.content_format.value,
        "content": new_content,
    })


@register_tool(toolset="artifact_ops")
async def regenerate_from_previous(
    ctx: RunContext[AgentDeps],
    artifact_id: str,
    instruction: str,
) -> dict:
    """Regenerate an artifact from scratch using the original parameters and new instructions."""
    store = get_artifact_store()
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        return _error("artifact not found", artifact_id=artifact_id)

    if artifact.artifact_type == "quiz":
        # Preserve original quiz parameters from the artifact content when possible.
        prev = artifact.content if isinstance(artifact.content, dict) else {}
        topic = instruction[:80] if instruction else prev.get("topic", "General Quiz")
        regen = await generate_quiz_questions(
            ctx,
            topic=topic,
            count=prev.get("count", 10),
            difficulty=prev.get("difficulty", "medium"),
            types=prev.get("types"),
            subject=prev.get("subject", ""),
            grade=prev.get("grade", ""),
            context=instruction,
        )
        return regen
    if artifact.artifact_type == "interactive":
        original_html = str(artifact.content)
        modified_html = await _modify_interactive_html(original_html, instruction)
        regen = await generate_interactive_html(
            ctx,
            html=modified_html,
            title="Regenerated Interactive Content",
            description=instruction,
        )
        return regen
    if artifact.artifact_type in {"document", "pptx"}:
        return _error("regenerate fallback not implemented for this artifact_type")
    return _error("unsupported artifact_type", artifact_type=artifact.artifact_type)


# ---------------------------------------------------------------------------
# platform (3 active, 2 disabled — save_as_assignment, create_share_link)
# ---------------------------------------------------------------------------


@register_tool(toolset="platform")
async def search_teacher_documents(
    ctx: RunContext[AgentDeps],
    query: str,
    n_results: int = 5,
    include_public: bool = False,
) -> dict:
    """Search the teacher's uploaded documents via RAG knowledge base."""
    from tools.document_tools import search_teacher_documents as _search

    teacher_id = ctx.deps.teacher_id
    if not teacher_id:
        return _error("teacher_id is required", query=query, results=[])
    result = await _search(
        teacher_id=teacher_id,
        query=query,
        n_results=n_results,
        include_public=include_public,
    )
    # Pass through the underlying status (ok / no_result / error / degraded)
    # transparently — document_tools already returns well-structured envelopes.
    return result


# NOTE: save_as_assignment and create_share_link are Phase 1 placeholders
# that return "coming soon" messages. Disabled to avoid confusing users.
# Re-enable when Phase 2 Java backend integration is implemented.
# See: platform_tools.py
#
# @register_tool(toolset="platform")
# async def save_as_assignment(...) -> dict: ...
#
# @register_tool(toolset="platform")
# async def create_share_link(...) -> dict: ...


@register_tool(toolset="platform")
async def ask_clarification(
    ctx: RunContext[AgentDeps],
    question: str,
    options: str | list[Any] | None = None,
    allow_custom_input: bool = True,
) -> dict:
    """Ask the user a clarifying question with optional multiple-choice options."""
    # LLMs sometimes double-encode options as a JSON string instead of an array.
    raw_options: list[Any] = []
    if isinstance(options, str):
        try:
            parsed = json.loads(options)
            raw_options = parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            raw_options = []
    elif isinstance(options, list):
        raw_options = options

    choices: list[ClarifyChoice] = []
    for item in raw_options:
        if isinstance(item, dict):
            choices.append(ClarifyChoice(
                label=str(item.get("label", "")),
                value=str(item.get("value", item.get("label", ""))),
                description=str(item.get("description", "")),
            ))
        elif isinstance(item, str):
            choices.append(ClarifyChoice(label=item, value=item))
        else:
            choices.append(ClarifyChoice(label=str(item), value=str(item)))
    clarify = ClarifyEvent(
        question=question,
        options=choices,
        allow_custom_input=allow_custom_input,
    )
    return _ok({
        "action": "clarify",
        "clarify": clarify.model_dump(),
    })


@register_tool(toolset="platform")
async def build_report_page(
    ctx: RunContext[AgentDeps],
    class_id: str,
    assignment_id: str = "",
) -> dict:
    """Build a lightweight report page by chaining data + analysis tools."""
    submissions = await get_assignment_submissions(
        ctx,
        class_id=class_id,
        assignment_id=assignment_id,
    )
    if submissions.get("status") != "ok":
        return submissions

    scores = submissions.get("scores", [])
    stats = await calculate_stats(ctx, data=scores, metrics=["mean", "median", "max", "min"])
    if stats.get("status") != "ok":
        return stats

    page = {
        "title": "Class Performance Report",
        "class_id": class_id,
        "assignment_id": assignment_id,
        "summary": {
            "mean": stats.get("mean"),
            "median": stats.get("median"),
            "max": stats.get("max"),
            "min": stats.get("min"),
            "count": stats.get("count"),
        },
        "submissions": submissions.get("submissions", []),
    }
    return _ok({"page": page})
