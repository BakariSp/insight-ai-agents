"""Unified LLM service powered by LiteLLM.

Supports any provider LiteLLM supports via model name prefix:
    - anthropic/claude-sonnet-4-20250514
    - openai/gpt-4o
    - dashscope/qwen-max
    - zai/glm-4.7
"""

import json
import litellm
from config import Config


class LLMService:
    """Thin wrapper around litellm.completion() for multi-provider LLM access."""

    def __init__(self, model: str | None = None):
        self.model = model or Config.LLM_MODEL
        self.max_tokens = Config.MAX_TOKENS

    def chat(self, messages: list, tools: list | None = None, system: str = "") -> dict:
        """Send a conversation turn to the LLM via LiteLLM.

        Args:
            messages: Conversation in OpenAI message format.
            tools:    Tool definitions in OpenAI function-calling format.
            system:   Optional system prompt (prepended as system message).

        Returns:
            Parsed response dict with keys:
                content, tool_calls, finish_reason, usage.
        """
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": all_messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = litellm.completion(**kwargs)
        return self._parse_response(response)

    def _parse_response(self, response) -> dict:
        """Parse LiteLLM ModelResponse into a simple dict."""
        choice = response.choices[0]
        message = choice.message

        tool_calls = None
        if message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]

        return {
            "content": message.content,
            "tool_calls": tool_calls,
            "finish_reason": choice.finish_reason,
            "usage": {
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        }
