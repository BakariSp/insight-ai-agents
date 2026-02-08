"""Universal Teacher Agent — Agent Path core.

LLM + Tools, free orchestration, no fixed scenario logic.
The LLM decides which tools to call and in what order based on the
teacher's request and available context.
"""

from __future__ import annotations

import logging

from pydantic_ai import Agent

from agents.provider import create_model, get_model_for_tier
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
    "propose_pptx_outline",
    "generate_pptx",
    "generate_docx",
    "render_pdf",
    "generate_interactive_html",
    # Platform operations (new)
    "save_as_assignment",
    "create_share_link",
]


def create_teacher_agent(
    teacher_context: dict,
    suggested_tools: list[str] | None = None,
    model_tier: str = "standard",
) -> Agent:
    """Create a universal teacher Agent instance.

    Args:
        teacher_context: Teacher context (classes, subject, grade, etc.)
        suggested_tools: Optional tool hints from the Router
        model_tier: Model quality tier from Router (fast/standard/strong/vision).
                    Controls which LLM is used for this agent session.

    Returns:
        PydanticAI Agent instance with tools + system prompt
    """
    model_name = get_model_for_tier(model_tier)
    model = create_model(model_name)
    logger.info("Agent using model_tier=%s → model=%s", model_tier, model_name)

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

    # Register available tools (plain — no RunContext needed)
    tools = _get_agent_tools()
    for tool_fn in tools:
        agent.tool_plain()(tool_fn)

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
