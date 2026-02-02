import json
import uuid
from services.llm_service import LLMService
from skills import WebSearchSkill, MemorySkill
from config import Config

SYSTEM_PROMPT = """You are Insight AI, a helpful assistant with access to tools.
Use the available tools when they would help answer the user's question.
Be concise and accurate. If you don't know something, say so."""


class ChatAgent:
    """Orchestrates conversations with LLMs, routing tool calls to skills."""

    def __init__(self):
        self.default_service = LLMService()
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

    def run(
        self,
        user_message: str,
        conversation_id: str | None = None,
        model: str | None = None,
    ) -> dict:
        """Run a full agent turn: send message, handle tool calls, return final response.

        Args:
            user_message:     The user's input text.
            conversation_id:  Optional ID to continue a conversation.
            model:            Optional model override (e.g. "openai/gpt-4o").
        """
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        service = LLMService(model=model) if model else self.default_service

        messages = self.conversations.get(conversation_id, [])
        messages.append({"role": "user", "content": user_message})

        tools = [s.to_tool_definition() for s in self.skills.values()]

        # Agent loop: keep going until we get a final text response
        while True:
            response = service.chat(
                messages=messages,
                tools=tools,
                system=SYSTEM_PROMPT,
            )

            # Build assistant message for conversation history
            assistant_msg: dict = {"role": "assistant", "content": response["content"]}
            if response["tool_calls"]:
                assistant_msg["tool_calls"] = response["tool_calls"]
            messages.append(assistant_msg)

            # If the model wants to use tools, execute them and continue
            if response["finish_reason"] == "tool_calls" and response["tool_calls"]:
                for tc in response["tool_calls"]:
                    args = json.loads(tc["function"]["arguments"])
                    result = self._execute_tool(tc["function"]["name"], args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })
            else:
                break

        self.conversations[conversation_id] = messages

        return {
            "conversation_id": conversation_id,
            "response": response["content"] or "",
            "model": service.model,
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
