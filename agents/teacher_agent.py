"""Universal Teacher Agent — Agent Path core.

LLM + Tools, free orchestration, no fixed scenario logic.
The LLM decides which tools to call and in what order based on the
teacher's request and available context.
"""

from __future__ import annotations

import logging

from pydantic_ai import Agent

from agents.provider import create_model
from config.prompts.teacher_agent import build_teacher_agent_prompt
from config.settings import get_settings
from tools import TOOL_REGISTRY

logger = logging.getLogger(__name__)

# Tools available to the Agent Path (excludes stats/compute tools used by Blueprint)
AGENT_TOOL_NAMES = [
    # Data queries (existing)
    "get_teacher_classes",
    "get_class_detail",
    "get_student_grades",
    "get_assignment_submissions",
    # Assessment analysis (existing)
    "analyze_student_weakness",
    "get_student_error_patterns",
    # Knowledge retrieval (existing)
    "search_teacher_documents",
    # Rubric tools (existing)
    "get_rubric",
    "list_available_rubrics",
    # Render tools (new)
    "generate_pptx",
    "generate_docx",
    "render_pdf",
    # Platform operations (new)
    "save_as_assignment",
    "create_share_link",
]


def create_teacher_agent(
    teacher_context: dict,
    suggested_tools: list[str] | None = None,
) -> Agent:
    """Create a universal teacher Agent instance.

    Args:
        teacher_context: Teacher context (classes, subject, grade, etc.)
        suggested_tools: Optional tool hints from the Router

    Returns:
        PydanticAI Agent instance with tools + system prompt
    """
    settings = get_settings()
    model = create_model(settings.agent_model)

    system_prompt = build_teacher_agent_prompt(
        teacher_context=teacher_context,
        suggested_tools=suggested_tools,
    )

    agent = Agent(
        model=model,
        system_prompt=system_prompt,
        retries=2,
        defer_model_check=True,
    )

    # Register available tools
    tools = _get_agent_tools()
    for tool_fn in tools:
        agent.tool()(tool_fn)

    return agent


def _get_agent_tools() -> list:
    """Return tool functions available to the Agent Path.

    Includes: data queries + knowledge retrieval + render tools + platform operations.
    Excludes: stats/compute tools (those are used by Blueprint path).
    """
    tools = []
    for name in AGENT_TOOL_NAMES:
        if name in TOOL_REGISTRY:
            tools.append(TOOL_REGISTRY[name])
        else:
            logger.debug("Agent tool %r not found in TOOL_REGISTRY, skipping", name)
    return tools
