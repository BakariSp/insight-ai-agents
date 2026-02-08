"""FastMCP tool registry for Insight AI Agent.

Raw tool functions live in data_tools.py and stats_tools.py.
This module registers them with FastMCP for MCP protocol access
and maintains a TOOL_REGISTRY for in-process invocation.
"""

from __future__ import annotations

from typing import Any, Callable

from fastmcp import FastMCP

from tools.data_tools import (
    get_assignment_submissions,
    get_class_detail,
    get_student_grades,
    get_teacher_classes,
)
from tools.stats_tools import calculate_stats, compare_performance
from tools.assessment_tools import (
    analyze_student_weakness,
    get_student_error_patterns,
    calculate_class_mastery,
)
from tools.rubric_tools import get_rubric, list_available_rubrics
from tools.document_tools import search_teacher_documents
from tools.render_tools import (
    propose_pptx_outline, generate_pptx, generate_docx, render_pdf,
    generate_interactive_html, request_interactive_content,
)
from tools.platform_tools import save_as_assignment, create_share_link

mcp = FastMCP("insight-ai-tools")

# Register all tools with FastMCP
mcp.tool()(get_teacher_classes)
mcp.tool()(get_class_detail)
mcp.tool()(get_assignment_submissions)
mcp.tool()(get_student_grades)
mcp.tool()(calculate_stats)
mcp.tool()(compare_performance)
# Phase 7: Assessment tools
mcp.tool()(analyze_student_weakness)
mcp.tool()(get_student_error_patterns)
mcp.tool()(calculate_class_mastery)
# Phase 7: Rubric tools
mcp.tool()(get_rubric)
mcp.tool()(list_available_rubrics)
# Knowledge Base: Document search
mcp.tool()(search_teacher_documents)
# Agent Path: Render tools
mcp.tool()(propose_pptx_outline)
mcp.tool()(generate_pptx)
mcp.tool()(generate_docx)
mcp.tool()(render_pdf)
mcp.tool()(generate_interactive_html)
mcp.tool()(request_interactive_content)
# Agent Path: Platform operations
mcp.tool()(save_as_assignment)
mcp.tool()(create_share_link)

# In-process tool registry: name → callable
TOOL_REGISTRY: dict[str, Callable[..., Any]] = {
    "get_teacher_classes": get_teacher_classes,
    "get_class_detail": get_class_detail,
    "get_assignment_submissions": get_assignment_submissions,
    "get_student_grades": get_student_grades,
    "calculate_stats": calculate_stats,
    "compare_performance": compare_performance,
    # Phase 7: Assessment tools
    "analyze_student_weakness": analyze_student_weakness,
    "get_student_error_patterns": get_student_error_patterns,
    "calculate_class_mastery": calculate_class_mastery,
    # Phase 7: Rubric tools
    "get_rubric": get_rubric,
    "list_available_rubrics": list_available_rubrics,
    # Knowledge Base: Document search
    "search_teacher_documents": search_teacher_documents,
    # Agent Path: Render tools
    "propose_pptx_outline": propose_pptx_outline,
    "generate_pptx": generate_pptx,
    "generate_docx": generate_docx,
    "render_pdf": render_pdf,
    "generate_interactive_html": generate_interactive_html,
    "request_interactive_content": request_interactive_content,
    # Agent Path: Platform operations
    "save_as_assignment": save_as_assignment,
    "create_share_link": create_share_link,
}


def get_tool_descriptions() -> list[dict[str, str]]:
    """Return name + description for every registered tool.

    Used by PlannerAgent to inject available tool info into the system prompt.
    """
    return [
        {"name": name, "description": (fn.__doc__ or "").strip().split("\n")[0]}
        for name, fn in TOOL_REGISTRY.items()
    ]
