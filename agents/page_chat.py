"""PageChatAgent — answers follow-up questions about existing analysis pages.

Uses blueprint context and page data summary to provide data-grounded answers.
Has tool access for supplementary data queries when needed.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent

from agents.provider import create_model
from config.llm_config import LLMConfig
from config.prompts.page_chat import build_page_chat_prompt
from models.blueprint import Blueprint
from models.conversation import Attachment
from services.multimodal import build_user_content, has_images

logger = logging.getLogger(__name__)

# Moderate temperature — informative but natural
PAGE_CHAT_LLM_CONFIG = LLMConfig(temperature=0.5)


def _summarize_page_context(page_context: dict[str, Any] | None) -> str:
    """Convert page_context dict into a readable text summary."""
    if not page_context:
        return "No page data available."

    lines = []
    for key, value in page_context.items():
        if isinstance(value, dict):
            lines.append(f"**{key}**:")
            for k, v in value.items():
                lines.append(f"  - {k}: {v}")
        elif isinstance(value, list):
            lines.append(f"**{key}**: {len(value)} items")
        else:
            lines.append(f"**{key}**: {value}")
    return "\n".join(lines) if lines else "No page data available."


async def generate_response(
    message: str,
    blueprint: Blueprint,
    page_context: dict[str, Any] | None = None,
    language: str = "en",
    attachments: list[Attachment] | None = None,
) -> str:
    """Generate a response to a follow-up question about the current page.

    Args:
        message: The user's follow-up question.
        blueprint: The current blueprint (provides context).
        page_context: Summary of the page's data points.
        language: Language hint for response generation.
        attachments: Optional image attachments for multimodal input.

    Returns:
        A Markdown-formatted text response grounded in page data.
    """
    page_summary = _summarize_page_context(page_context)

    # Use vision model when images are present
    if has_images(attachments):
        from config.settings import get_settings

        model = create_model(get_settings().vision_model)
        logger.info("PageChatAgent: using vision model for %d image(s)", len(attachments or []))
    else:
        model = create_model()

    # Build a per-request agent with page-specific context
    agent = Agent(
        model=model,
        system_prompt=build_page_chat_prompt(
            blueprint_name=blueprint.name,
            blueprint_description=blueprint.description,
            page_summary=page_summary,
        ),
        retries=1,
        defer_model_check=True,
    )

    run_prompt = f"[Language: {language}]\n\n{message}"

    # Build multimodal content when images are attached
    user_content = await build_user_content(run_prompt, attachments or [])

    logger.info(
        "PageChatAgent: blueprint=%s message=%.60s",
        blueprint.id,
        message,
    )

    result = await agent.run(
        user_content,
        model_settings=PAGE_CHAT_LLM_CONFIG.to_litellm_kwargs(),
    )
    response = str(result.output)

    logger.info("PageChatAgent: response length=%d", len(response))
    return response
