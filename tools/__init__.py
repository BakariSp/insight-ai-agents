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

mcp = FastMCP("insight-ai-tools")

# Register all tools with FastMCP
mcp.tool()(get_teacher_classes)
mcp.tool()(get_class_detail)
mcp.tool()(get_assignment_submissions)
mcp.tool()(get_student_grades)
mcp.tool()(calculate_stats)
mcp.tool()(compare_performance)

# In-process tool registry: name → callable
TOOL_REGISTRY: dict[str, Callable[..., Any]] = {
    "get_teacher_classes": get_teacher_classes,
    "get_class_detail": get_class_detail,
    "get_assignment_submissions": get_assignment_submissions,
    "get_student_grades": get_student_grades,
    "calculate_stats": calculate_stats,
    "compare_performance": compare_performance,
}


def get_tool_descriptions() -> list[dict[str, str]]:
    """Return name + description for every registered tool.

    Used by PlannerAgent to inject available tool info into the system prompt.
    """
    return [
        {"name": name, "description": (fn.__doc__ or "").strip().split("\n")[0]}
        for name, fn in TOOL_REGISTRY.items()
    ]
