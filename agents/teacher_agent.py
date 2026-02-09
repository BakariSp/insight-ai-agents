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
from tools import TOOL_REGISTRY

logger = logging.getLogger(__name__)

# Always-on base tools (data/knowledge/assessment).
BASE_TOOL_NAMES = [
    "get_teacher_classes",
    "get_class_detail",
    "get_student_grades",
    "get_assignment_submissions",
    "analyze_student_weakness",
    "get_student_error_patterns",
    "search_teacher_documents",
    "get_rubric",
    "list_available_rubrics",
]

# Generation/tooling priority set (candidate tools from Router).
PRIORITY_TOOL_NAMES = [
    "propose_pptx_outline",
    "generate_pptx",
    "generate_docx",
    "render_pdf",
    "generate_interactive_html",
    "request_interactive_content",
    "save_as_assignment",
    "create_share_link",
    "generate_quiz_questions",
]


def create_teacher_agent(
    teacher_context: dict,
    suggested_tools: list[str] | None = None,
    candidate_tools: list[str] | None = None,
    model_tier: str = "standard",
    _override_model: str | None = None,
    tool_tracker=None,
    _allowed_tool_names: list[str] | None = None,
    output_type=None,
) -> Agent:
    """Create a universal teacher Agent instance.

    Args:
        teacher_context: Teacher context (classes, subject, grade, etc.)
        suggested_tools: Optional legacy tool hints from the Router.
        candidate_tools: Preferred generation tool set from Router.
        model_tier: Model quality tier from Router (fast/standard/strong/vision).
                    Controls which LLM is used for this agent session.
        _override_model: If set, use this model name instead of tier mapping.
                         Used internally by the fallback mechanism.
        tool_tracker: Optional ToolTracker for real-time progress events.

    Returns:
        PydanticAI Agent instance with tools + system prompt
    """
    if _override_model:
        model_name = _override_model
    else:
        model_name = get_model_for_tier(model_tier)
    model = create_model(model_name)
    logger.info("Agent using model_tier=%s → model=%s", model_tier, model_name)

    system_prompt = build_teacher_agent_prompt(
        teacher_context=teacher_context,
        suggested_tools=candidate_tools or suggested_tools,
    )

    agent = Agent(
        model=model,
        system_prompt=system_prompt,
        output_type=output_type,
        retries=2,
        defer_model_check=True,
    )

    # Register available tools (plain — no RunContext needed)
    tools = _get_agent_tools(
        candidate_tools=candidate_tools or suggested_tools,
        allowed_tool_names=_allowed_tool_names,
    )
    for tool_fn in tools:
        if tool_tracker is not None:
            agent.tool_plain()(tool_tracker.wrap(tool_fn))
        else:
            agent.tool_plain()(tool_fn)

    return agent


def _get_agent_tools(
    candidate_tools: list[str] | None = None,
    allowed_tool_names: list[str] | None = None,
) -> list:
    """Return tool functions available to the Agent Path.

    Base tools (data/knowledge/assessment) are always registered regardless of
    ``allowed_tool_names`` — they provide data context the Agent needs (§7.2).
    ``allowed_tool_names`` only narrows the priority / generation set.
    When ``candidate_tools`` is not supplied, all priority tools are registered.
    """
    tools = []

    # 常驻基座 — always present
    base_names = list(BASE_TOOL_NAMES)

    # Priority / generation tools — filtered by candidate_tools input
    if candidate_tools:
        priority_names = [
            name for name in candidate_tools if name in PRIORITY_TOOL_NAMES
        ]
    else:
        priority_names = list(PRIORITY_TOOL_NAMES)

    # allowed_tool_names further narrows priority set only, not base
    if allowed_tool_names:
        allowed = set(allowed_tool_names)
        priority_names = [n for n in priority_names if n in allowed]

    names = base_names + priority_names

    for name in names:
        if name in TOOL_REGISTRY:
            tools.append(TOOL_REGISTRY[name])
        else:
            logger.debug("Agent tool %r not found in TOOL_REGISTRY, skipping", name)
    return tools
