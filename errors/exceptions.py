"""Domain-specific exceptions for Insight AI Agent.

These exceptions allow the Executor and API layers to distinguish between
different failure modes and respond with appropriate SSE events or HTTP errors.
"""

from __future__ import annotations


class ToolError(Exception):
    """Base class for tool execution errors."""

    def __init__(self, tool_name: str, message: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' failed: {message}")


class DataFetchError(ToolError):
    """A required data binding returned an error or missing entity.

    Raised during Phase A (Data Contract resolution) when a tool returns
    an ``{"error": ...}`` dict for a *required* binding.  Carries enough
    context for the Executor to emit a ``DATA_ERROR`` SSE event.
    """

    def __init__(
        self,
        tool_name: str,
        message: str,
        entity: str = "",
        suggestions: list[str] | None = None,
    ) -> None:
        self.entity = entity
        self.suggestions = suggestions or []
        super().__init__(tool_name, message)


class EntityNotFoundError(DataFetchError):
    """A referenced entity (class, student, assignment) does not exist.

    Specialization of ``DataFetchError`` for entity-not-found situations,
    making it easy to generate user-friendly "did you mean?" suggestions.
    """

    def __init__(
        self,
        tool_name: str,
        entity_id: str,
        entity_type: str = "entity",
        suggestions: list[str] | None = None,
    ) -> None:
        self.entity_id = entity_id
        self.entity_type = entity_type
        super().__init__(
            tool_name=tool_name,
            message=f"{entity_type} '{entity_id}' not found",
            entity=entity_id,
            suggestions=suggestions or [],
        )
