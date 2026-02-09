"""Native tool registrations for Step 2 tool convergence."""

from __future__ import annotations

import copy
import logging
from typing import Any

from pydantic_ai import RunContext

from agents.native_agent import AgentDeps
from models.tool_contracts import ClarifyChoice, ClarifyEvent
from services.artifact_store import get_artifact_store
from tools.registry import register_tool

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# base_data (5)
# ---------------------------------------------------------------------------


@register_tool(toolset="base_data")
async def get_teacher_classes(ctx: RunContext[AgentDeps]) -> dict:
    """List all classes assigned to the current teacher."""
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
    """Get detailed information for a class including students and assignments."""
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
    """Get all student submissions and scores for a specific assignment."""
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
    """Get all grades for a specific student in a class."""
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
    metrics: list[str] | None = None,
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
    metrics: list[str] | None = None,
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
    knowledge_point_ids: list[str] | None = None,
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
    types: list[str] | None = None,
    subject: str = "",
    grade: str = "",
    context: str = "",
) -> dict:
    """Generate quiz questions on a topic, returning a JSON artifact."""
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
    """Generate a PPTX file from a list of slide definitions."""
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
    """Wrap self-contained interactive HTML into a renderable artifact."""
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


@register_tool(toolset="generation")
async def request_interactive_content(
    ctx: RunContext[AgentDeps],
    title: str,
    description: str,
    topics: list[str],
    sections: list[dict],
    grade_level: str = "",
    subject: str = "",
    style: str = "modern",
    include_features: list[str] | None = None,
) -> dict:
    """Plan interactive HTML content for three-stream parallel generation."""
    from tools.render_tools import request_interactive_content as _request

    result = await _request(
        title=title,
        description=description,
        topics=topics,
        sections=sections,
        grade_level=grade_level,
        subject=subject,
        style=style,
        include_features=include_features,
    )
    artifact_meta = _save_artifact(
        conversation_id=ctx.deps.conversation_id,
        artifact_type="interactive",
        content_format="json",
        content=result,
    )
    return _ok({**result, **artifact_meta, "artifact_type": "interactive", "content_format": "json"})


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
        html = str(artifact.content)
        regen = await generate_interactive_html(
            ctx,
            html=html,
            title="Regenerated Interactive Content",
            description=instruction,
        )
        return regen
    if artifact.artifact_type in {"document", "pptx"}:
        return _error("regenerate fallback not implemented for this artifact_type")
    return _error("unsupported artifact_type", artifact_type=artifact.artifact_type)


# ---------------------------------------------------------------------------
# platform (5)
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


@register_tool(toolset="platform")
async def save_as_assignment(
    ctx: RunContext[AgentDeps],
    title: str,
    questions: list[dict],
    class_id: str = "",
    due_date: str = "",
    description: str = "",
) -> dict:
    """Save generated questions as a class assignment on the platform."""
    from tools.platform_tools import save_as_assignment as _save

    result = await _save(
        title=title,
        questions=questions,
        class_id=class_id,
        due_date=due_date,
        description=description,
    )
    return _ok(result)


@register_tool(toolset="platform")
async def create_share_link(
    ctx: RunContext[AgentDeps],
    assignment_id: str,
) -> dict:
    """Create a shareable link for an assignment."""
    from tools.platform_tools import create_share_link as _share

    result = await _share(assignment_id=assignment_id)
    return _ok(result)


@register_tool(toolset="platform")
async def ask_clarification(
    ctx: RunContext[AgentDeps],
    question: str,
    options: list[dict[str, str]] | None = None,
    allow_custom_input: bool = True,
) -> dict:
    """Ask the user a clarifying question with optional multiple-choice options."""
    clarify = ClarifyEvent(
        question=question,
        options=[
            ClarifyChoice(
                label=str(item.get("label", "")),
                value=str(item.get("value", "")),
                description=str(item.get("description", "")),
            )
            for item in (options or [])
        ],
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
