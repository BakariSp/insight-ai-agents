import uuid
from services.anthropic_service import AnthropicService
from skills import WebSearchSkill, MemorySkill
from config import Config

SYSTEM_PROMPT = """You are Insight AI, a helpful assistant with access to tools.
Use the available tools when they would help answer the user's question.
Be concise and accurate. If you don't know something, say so."""


class ChatAgent:
    """Orchestrates conversations with Claude, routing tool calls to skills."""

    def __init__(self):
        self.service = AnthropicService()
        self.skills = self._load_skills()
        self.conversations: dict[str, list] = {}

    def _load_skills(self) -> dict:
        """Initialize and register all available skills."""
        skill_instances = [
            WebSearchSkill(api_key=Config.__dict__.get("BRAVE_API_KEY", "")),
            MemorySkill(),
        ]
        return {s.name: s for s in skill_instances}

    def list_skills(self) -> list[dict]:
        return [
            {"name": s.name, "description": s.description}
            for s in self.skills.values()
        ]

    def run(self, user_message: str, conversation_id: str | None = None) -> dict:
        """Run a full agent turn: send message, handle tool calls, return final response."""
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        messages = self.conversations.get(conversation_id, [])
        messages.append({"role": "user", "content": user_message})

        tools = [s.to_tool_definition() for s in self.skills.values()]

        # Agent loop: keep going until we get a final text response
        while True:
            response = self.service.chat(
                messages=messages,
                tools=tools,
                system=SYSTEM_PROMPT,
            )

            # Add assistant response to conversation
            messages.append({"role": "assistant", "content": response["content"]})

            # If the model wants to use a tool, execute it and continue
            if response["stop_reason"] == "tool_use":
                tool_results = []
                for block in response["content"]:
                    if block["type"] == "tool_use":
                        result = self._execute_tool(block["name"], block["input"])
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": result,
                        })
                messages.append({"role": "user", "content": tool_results})
            else:
                # Final response — extract text
                break

        self.conversations[conversation_id] = messages

        text_parts = [b["text"] for b in response["content"] if b["type"] == "text"]
        return {
            "conversation_id": conversation_id,
            "response": "\n".join(text_parts),
            "usage": response["usage"],
        }

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        skill = self.skills.get(tool_name)
        if not skill:
            return f"Error: unknown tool '{tool_name}'"
        try:
            return skill.execute(**tool_input)
        except Exception as e:
            return f"Error executing {tool_name}: {e}"
