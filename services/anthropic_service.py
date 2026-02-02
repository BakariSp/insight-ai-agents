import anthropic
from config import Config


class AnthropicService:
    """Wrapper around the Anthropic API for tool-use conversations."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        self.model = Config.ANTHROPIC_MODEL
        self.max_tokens = Config.MAX_TOKENS

    def chat(self, messages: list, tools: list | None = None, system: str = "") -> dict:
        """Send a message to Claude and return the response.

        Args:
            messages: Conversation messages in Anthropic format.
            tools: Optional list of tool definitions for function calling.
            system: Optional system prompt.

        Returns:
            The API response as a dict.
        """
        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        response = self.client.messages.create(**kwargs)
        return self._parse_response(response)

    def _parse_response(self, response) -> dict:
        """Parse the Anthropic API response into a simpler dict."""
        result = {
            "role": response.role,
            "content": [],
            "stop_reason": response.stop_reason,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        }

        for block in response.content:
            if block.type == "text":
                result["content"].append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                result["content"].append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        return result
