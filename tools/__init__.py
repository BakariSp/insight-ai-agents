"""FastMCP tool registry for Insight AI Agent.

Raw tool functions live in data_tools.py and stats_tools.py.
This module registers them with FastMCP for MCP protocol access.
"""

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
