"""ChatAgent — handles smalltalk and knowledge Q&A intents.

Lightweight agent that generates friendly text responses without tool calls.
Used for chat_smalltalk and chat_qa intents in the conversation gateway.
"""

from __future__ import annotations

import logging

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage

from agents.provider import create_model
from config.llm_config import LLMConfig
from config.prompts.chat import build_chat_prompt
from models.conversation import Attachment
from services.multimodal import build_user_content, has_images

logger = logging.getLogger(__name__)

# Slightly higher temperature for natural conversation
CHAT_LLM_CONFIG = LLMConfig(temperature=0.7)

# Module-level agent — reused across requests
_chat_agent = Agent(
    model=create_model(),
    system_prompt=build_chat_prompt(),
    retries=1,
    defer_model_check=True,
)


async def generate_response(
    message: str,
    intent_type: str = "chat_smalltalk",
    language: str = "en",
    conversation_history: str = "",
    attachments: list[Attachment] | None = None,
    message_history: list[ModelMessage] | None = None,
) -> str:
    """Generate a chat response for smalltalk or QA intent.

    Args:
        message: The user's message.
        intent_type: "chat_smalltalk" or "chat_qa".
        language: Language hint for response generation.
        conversation_history: Formatted recent turns for context (legacy, used as fallback).
        attachments: Optional image attachments for multimodal input.
        message_history: Structured PydanticAI message history for proper multi-turn context.

    Returns:
        A Markdown-formatted text response.
    """
    run_prompt = (
        f"[Language: {language}]\n"
        f"[Intent: {intent_type}]\n\n"
        f"{message}"
    )

    # Build multimodal content when images are attached
    user_content = await build_user_content(run_prompt, attachments or [])

    # Use vision model when images are present
    if has_images(attachments):
        from config.settings import get_settings

        agent = Agent(
            model=create_model(get_settings().vision_model),
            system_prompt=build_chat_prompt(),
            retries=1,
            defer_model_check=True,
        )
        logger.info("ChatAgent: using vision model for %d image(s)", len(attachments or []))
    else:
        agent = _chat_agent

    logger.info(
        "ChatAgent: intent=%s message=%.60s history_turns=%d",
        intent_type, message, len(message_history or []),
    )

    result = await agent.run(
        user_content,
        message_history=message_history or [],
        model_settings=CHAT_LLM_CONFIG.to_litellm_kwargs(),
    )
    response = str(result.output)

    logger.info("ChatAgent: response length=%d", len(response))
    return response
