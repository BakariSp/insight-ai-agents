"""Unified LLM service powered by LiteLLM.

Supports any provider LiteLLM supports via model name prefix:
    - anthropic/claude-sonnet-4-20250514
    - openai/gpt-4o
    - dashscope/qwen-max
    - zai/glm-4.7
"""

from __future__ import annotations

import litellm

from config.llm_config import LLMConfig
from config.settings import get_settings


class LLMService:
    """Thin wrapper around litellm.completion() for multi-provider LLM access.

    Accepts an optional :class:`LLMConfig` that is merged on top of the
    global defaults from Settings.  Individual calls can still override
    any parameter via ``**overrides``.

    Priority chain (low → high):
        .env global defaults  →  agent-level LLMConfig  →  per-call overrides
    """

    def __init__(self, config: LLMConfig | None = None, model: str | None = None):
        settings = get_settings()
        self._config = settings.get_default_llm_config()

        # Agent-level overrides
        if config:
            self._config = self._config.merge(config)

        # Legacy `model=` shortcut (backwards-compatible with existing callers)
        if model:
            self._config = self._config.merge(LLMConfig(model=model))

    @property
    def model(self) -> str | None:
        return self._config.model

    def chat(
        self,
        messages: list,
        tools: list | None = None,
        system: str = "",
        **overrides,
    ) -> dict:
        """Send a conversation turn to the LLM via LiteLLM.

        Args:
            messages: Conversation in OpenAI message format.
            tools:    Tool definitions in OpenAI function-calling format.
            system:   Optional system prompt (prepended as system message).
            **overrides: Per-call parameter overrides (e.g. ``temperature=0.2``).

        Returns:
            Parsed response dict with keys:
                content, tool_calls, finish_reason, usage.
        """
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        kwargs: dict = {
            "model": self._config.model,
            "messages": all_messages,
            **self._config.to_litellm_kwargs(),
        }
        if tools:
            kwargs["tools"] = tools

        # Per-call overrides win
        kwargs.update(overrides)

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
