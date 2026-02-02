from abc import ABC, abstractmethod


class BaseSkill(ABC):
    """Base class for all agent skills/tools.

    Each skill maps to a Claude tool_use definition and provides
    execution logic when the tool is called.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this skill (used as tool name)."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what this skill does (shown to the model)."""

    @property
    @abstractmethod
    def input_schema(self) -> dict:
        """JSON Schema for the tool's input parameters."""

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """Execute the skill with the given parameters and return a result string."""

    def to_tool_definition(self) -> dict:
        """Convert this skill to an OpenAI function-calling tool definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }
