"""ChatAgent — handles smalltalk and knowledge Q&A intents.

Lightweight agent that generates friendly text responses without tool calls.
Used for chat_smalltalk and chat_qa intents in the conversation gateway.
"""

from __future__ import annotations

import logging

from pydantic_ai import Agent

from agents.provider import create_model
from config.llm_config import LLMConfig
from config.prompts.chat import build_chat_prompt

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
) -> str:
    """Generate a chat response for smalltalk or QA intent.

    Args:
        message: The user's message.
        intent_type: "chat_smalltalk" or "chat_qa".
        language: Language hint for response generation.
        conversation_history: Formatted recent turns for context.

    Returns:
        A Markdown-formatted text response.
    """
    history_section = ""
    if conversation_history:
        history_section = f"[Recent conversation]\n{conversation_history}\n\n"

    run_prompt = (
        f"[Language: {language}]\n"
        f"[Intent: {intent_type}]\n\n"
        f"{history_section}"
        f"{message}"
    )

    logger.info("ChatAgent: intent=%s message=%.60s", intent_type, message)

    result = await _chat_agent.run(
        run_prompt,
        model_settings=CHAT_LLM_CONFIG.to_litellm_kwargs(),
    )
    response = str(result.output)

    logger.info("ChatAgent: response length=%d", len(response))
    return response
