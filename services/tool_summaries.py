"""Tool result summarizer — extracts human-readable summaries from tool outputs.

Each tool gets a dedicated extractor that produces a short text summary
(shown on the badge) and optional structured details (shown on hover).

The summary dict has:
- text: str — short inline text, e.g. "3 个班级"
- details: list[dict] | None — structured items for hover popover
  Each detail item: {"label": str, "value": str, "id": str | None}
"""

from __future__ import annotations

from typing import Any


def _get(d: dict, *keys, default=None):
    """Get first non-None value from dict for given keys. Unlike ``or``, treats 0 as valid."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def summarize_tool_result(tool_name: str, result: dict[str, Any]) -> dict | None:
    """Return a summary dict for the given tool result, or None."""
    fn = _EXTRACTORS.get(tool_name)
    if fn is None:
        return None
    try:
        return fn(result)
    except Exception:
        return None


# ── Per-tool extractors ──────────────────────────────────────────────


def _summarize_teacher_classes(r: dict) -> dict | None:
    classes = r.get("classes") or []
    if not classes:
        return {"text": "暂无班级", "details": None}
    items = []
    for c in classes:
        name = c.get("className") or c.get("name") or "未命名"
        count = _get(c, "studentCount", "student_count", default="?")
        cid = c.get("classId") or c.get("id") or ""
        items.append({"label": name, "value": f"{count} 名学生", "id": cid})
    return {"text": f"{len(classes)} 个班级", "details": items}


def _summarize_class_detail(r: dict) -> dict | None:
    cls = r.get("class") or r
    name = cls.get("className") or cls.get("name") or ""
    students = cls.get("students") or []
    assignments = cls.get("assignments") or []

    parts = []
    if students:
        parts.append(f"{len(students)} 名学生")
    if assignments:
        parts.append(f"{len(assignments)} 项作业")
    detail_text = "、".join(parts) if parts else "详情已加载"
    summary_text = f"{name}: {detail_text}" if name else detail_text

    details = []
    for s in students[:10]:  # cap at 10 for hover
        sname = s.get("studentName") or s.get("name") or "未命名"
        sid = s.get("studentId") or s.get("id") or ""
        details.append({"label": sname, "value": "学生", "id": sid})
    if len(students) > 10:
        details.append({"label": f"…还有 {len(students) - 10} 名", "value": "", "id": None})

    return {"text": summary_text, "details": details or None}


def _summarize_assignment_submissions(r: dict) -> dict | None:
    submissions = r.get("submissions") or []
    total = _get(r, "total", default=len(submissions))
    avg = _get(r, "averageScore", "average_score")
    parts = [f"{total} 份提交"]
    if avg is not None:
        parts.append(f"均分 {avg}")
    return {"text": "、".join(parts), "details": None}


def _summarize_student_grades(r: dict) -> dict | None:
    grades = r.get("grades") or []
    if not grades:
        return {"text": "暂无成绩", "details": None}
    return {"text": f"{len(grades)} 条成绩记录", "details": None}


def _summarize_search_documents(r: dict) -> dict | None:
    status = r.get("status", "")
    total = r.get("total", 0)
    if status == "no_result" or total == 0:
        hint = r.get("fallback_hint", "")
        return {
            "text": "未找到相关内容",
            "details": [{"label": hint, "value": "", "id": None}] if hint else None,
        }
    sources = r.get("sources") or []
    source_details = [
        {"label": s.get("fileName", ""), "value": "文档", "id": s.get("fileId", "")}
        for s in sources[:5]
    ]
    return {"text": f"找到 {total} 条结果", "details": source_details or None}


def _summarize_generate_quiz(r: dict) -> dict | None:
    questions = r.get("questions") or []
    total = _get(r, "total", default=len(questions))
    if total == 0:
        return {"text": "生成完成", "details": None}
    return {"text": f"已生成 {total} 道题目", "details": None}


def _summarize_clarification(r: dict) -> dict | None:
    clarify = r.get("clarify") or {}
    question = clarify.get("question", "")
    if question:
        return {"text": f"询问: {question[:20]}…" if len(question) > 20 else f"询问: {question}", "details": None}
    return {"text": "等待确认", "details": None}


def _summarize_interactive_html(r: dict) -> dict | None:
    return {"text": "互动网页已生成", "details": None}


def _summarize_pptx_outline(r: dict) -> dict | None:
    outline = r.get("outline") or {}
    slides = outline.get("slides") or []
    if slides:
        return {"text": f"大纲: {len(slides)} 页", "details": None}
    return {"text": "大纲已生成", "details": None}


def _summarize_pptx(r: dict) -> dict | None:
    return {"text": "PPT 已生成", "details": None}


def _summarize_build_report(r: dict) -> dict | None:
    page = r.get("page") or {}
    summary = page.get("summary") or {}
    mean = summary.get("mean")
    count = summary.get("count")
    parts = []
    if count is not None:
        parts.append(f"{count} 人")
    if mean is not None:
        parts.append(f"均分 {mean}")
    return {"text": "、".join(parts) if parts else "报告已生成", "details": None}


# ── Registry ─────────────────────────────────────────────────────────

_EXTRACTORS: dict[str, Any] = {
    "get_teacher_classes": _summarize_teacher_classes,
    "get_class_detail": _summarize_class_detail,
    "get_assignment_submissions": _summarize_assignment_submissions,
    "get_student_grades": _summarize_student_grades,
    "search_teacher_documents": _summarize_search_documents,
    "generate_quiz_questions": _summarize_generate_quiz,
    "ask_clarification": _summarize_clarification,
    "generate_interactive_html": _summarize_interactive_html,
    "request_interactive_content": _summarize_interactive_html,
    "propose_pptx_outline": _summarize_pptx_outline,
    "generate_pptx": _summarize_pptx,
    "build_report_page": _summarize_build_report,
}
