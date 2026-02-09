"""Native tool registrations — migrates existing tools to the new registry.

Step 1.1.3+ of AI native rewrite.  Each tool is re-exported from its original
module and registered via ``@register_tool(toolset="...")``.

Import this module at startup to populate the registry.
"""

from __future__ import annotations

from pydantic_ai import RunContext

from agents.native_agent import AgentDeps
from tools.registry import register_tool


# ── generation toolset ──────────────────────────────────────


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
    """Generate quiz questions for a given topic (multiple choice, fill-in-blank, etc.).

    Args:
        ctx: Agent run context with teacher_id.
        topic: The subject/topic for the quiz questions.
        count: Number of questions to generate (default 10).
        difficulty: Difficulty level — "easy", "medium", or "hard".
        types: Question types, e.g. ["SINGLE_CHOICE", "FILL_IN_BLANK"].
        subject: Academic subject (e.g. "English", "Math").
        grade: Grade level (e.g. "Grade 5").
        context: Additional context or instructions for generation.

    Returns:
        {"status": "ok", "questions": [...], "total": int, "artifact_type": "quiz", "content_format": "json"}
    """
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
    return {
        "status": "ok",
        "artifact_type": "quiz",
        "content_format": "json",
        **result,
    }


# ── platform toolset ────────────────────────────────────────


@register_tool(toolset="platform")
async def search_teacher_documents(
    ctx: RunContext[AgentDeps],
    query: str,
    n_results: int = 5,
    include_public: bool = False,
) -> dict:
    """Search the teacher's knowledge base for relevant document chunks (RAG).

    Uses LightRAG hybrid search (vector + knowledge graph) to find relevant
    document fragments. Searches the teacher's private workspace by default.
    Set include_public=True to also search the public knowledge base
    (results may contain content from other schools).

    Args:
        ctx: Agent run context with teacher_id.
        query: Natural-language search query.
        n_results: Maximum number of results to return.
        include_public: Also search public knowledge base (default False).

    Returns:
        {"status": "ok"|"no_result"|"error"|"degraded", "query": str, "results": [...]}
    """
    from tools.document_tools import search_teacher_documents as _search

    teacher_id = ctx.deps.teacher_id
    if not teacher_id:
        return {"status": "error", "reason": "teacher_id is required", "query": query, "results": []}

    try:
        result = await _search(
            teacher_id=teacher_id,
            query=query,
            n_results=n_results,
            include_public=include_public,
        )
        # Normalize status per RAG failure semantics (6.7)
        if result.get("error"):
            return {"status": "error", "reason": result["error"], "query": query, "results": []}
        if not result.get("results"):
            return {"status": "no_result", "query": query, "results": [], "total": 0}
        return {"status": "ok", **result}
    except Exception as e:
        return {"status": "error", "reason": str(e), "query": query, "results": []}


# ── base_data toolset ───────────────────────────────────────


@register_tool(toolset="base_data")
async def get_teacher_classes(
    ctx: RunContext[AgentDeps],
) -> dict:
    """Get the list of classes for the current teacher.

    Returns:
        {"status": "ok", "classes": [...]} or {"status": "error", "reason": "..."}
    """
    from config.settings import get_settings
    from tools.data_tools import get_teacher_classes as _get_classes

    teacher_id = ctx.deps.teacher_id
    if not teacher_id:
        return {"status": "error", "reason": "teacher_id is required"}

    try:
        result = await _get_classes(teacher_id=teacher_id)
        return {"status": "ok", "classes": result if isinstance(result, list) else result.get("classes", [])}
    except Exception as e:
        settings = get_settings()
        if settings.debug:
            from services.mock_data import _mock_teacher_classes
            return _mock_teacher_classes(teacher_id)
        return {"status": "error", "reason": str(e)}


@register_tool(toolset="base_data")
async def get_class_detail(
    ctx: RunContext[AgentDeps],
    class_id: str,
) -> dict:
    """Get detailed information about a specific class.

    Args:
        ctx: Agent run context.
        class_id: The class ID to look up.

    Returns:
        {"status": "ok", ...class details} or {"status": "error", "reason": "..."}
    """
    from tools.data_tools import get_class_detail as _get_detail

    teacher_id = ctx.deps.teacher_id
    if not teacher_id:
        return {"status": "error", "reason": "teacher_id is required"}

    try:
        result = await _get_detail(teacher_id=teacher_id, class_id=class_id)
        return {"status": "ok", **(result if isinstance(result, dict) else {"data": result})}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


@register_tool(toolset="base_data")
async def get_assignment_submissions(
    ctx: RunContext[AgentDeps],
    class_id: str,
    assignment_id: str,
) -> dict:
    """Get student submission records for a specific assignment.

    Args:
        ctx: Agent run context.
        class_id: The class ID.
        assignment_id: The assignment ID.

    Returns:
        {"status": "ok", "submissions": [...]} or {"status": "error", "reason": "..."}
    """
    from tools.data_tools import get_assignment_submissions as _get_subs

    teacher_id = ctx.deps.teacher_id
    if not teacher_id:
        return {"status": "error", "reason": "teacher_id is required"}

    try:
        result = await _get_subs(
            teacher_id=teacher_id,
            class_id=class_id,
            assignment_id=assignment_id,
        )
        return {"status": "ok", **(result if isinstance(result, dict) else {"submissions": result})}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


@register_tool(toolset="base_data")
async def get_student_grades(
    ctx: RunContext[AgentDeps],
    class_id: str,
    student_id: str = "",
) -> dict:
    """Get student grades for a class (or a specific student).

    Args:
        ctx: Agent run context.
        class_id: The class ID.
        student_id: Optional specific student ID.

    Returns:
        {"status": "ok", "grades": [...]} or {"status": "error", "reason": "..."}
    """
    from tools.data_tools import get_student_grades as _get_grades

    teacher_id = ctx.deps.teacher_id
    if not teacher_id:
        return {"status": "error", "reason": "teacher_id is required"}

    try:
        result = await _get_grades(
            teacher_id=teacher_id,
            class_id=class_id,
            student_id=student_id,
        )
        return {"status": "ok", **(result if isinstance(result, dict) else {"grades": result})}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


# ── analysis toolset ────────────────────────────────────────


@register_tool(toolset="analysis")
async def calculate_stats(
    ctx: RunContext[AgentDeps],
    data: list[float],
    metrics: list[str] | None = None,
) -> dict:
    """Calculate statistics (mean, median, std dev, etc.) on numeric data.

    Use this after fetching student grades/scores via data tools.
    Pass the numeric values as a list.

    Args:
        ctx: Agent run context.
        data: List of numeric values to analyze.
        metrics: Optional list of metrics to compute (e.g. ["mean", "median", "std"]).

    Returns:
        {"status": "ok", "stats": {...}} or {"status": "error", "reason": "..."}
    """
    from tools.stats_tools import calculate_stats as _calc

    try:
        result = _calc(data=data, metrics=metrics)
        return {"status": "ok", **(result if isinstance(result, dict) else {"stats": result})}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


@register_tool(toolset="analysis")
async def compare_performance(
    ctx: RunContext[AgentDeps],
    group_a: list[float],
    group_b: list[float],
    metrics: list[str] | None = None,
) -> dict:
    """Compare performance between two groups of numeric scores.

    Use this after fetching grade data for two classes or time periods.

    Args:
        ctx: Agent run context.
        group_a: First group of numeric values.
        group_b: Second group of numeric values.
        metrics: Optional list of comparison metrics.

    Returns:
        {"status": "ok", "comparison": {...}} or {"status": "error", "reason": "..."}
    """
    from tools.stats_tools import compare_performance as _compare

    try:
        result = _compare(group_a=group_a, group_b=group_b, metrics=metrics)
        return {"status": "ok", **(result if isinstance(result, dict) else {"comparison": result})}
    except Exception as e:
        return {"status": "error", "reason": str(e)}
