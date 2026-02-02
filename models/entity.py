"""Entity resolution models — general-purpose entity matching from natural language.

Defines output models for the entity resolver service, which matches
natural-language entity mentions (classes, students, assignments) to concrete IDs.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field

from models.base import CamelModel


class EntityType(str, Enum):
    """Supported entity types for resolution."""

    CLASS = "class"
    STUDENT = "student"
    ASSIGNMENT = "assignment"


class ResolvedEntity(CamelModel):
    """A single resolved entity with confidence and match metadata."""

    entity_type: EntityType
    entity_id: str
    display_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    match_type: Literal["exact", "alias", "grade", "fuzzy"]


class ResolveResult(CamelModel):
    """Output of entity resolution — zero or more matched entities."""

    entities: list[ResolvedEntity] = Field(default_factory=list)
    is_ambiguous: bool = False
    scope_mode: Literal["none", "single", "multi", "grade"] = "none"
    missing_context: list[str] = Field(default_factory=list)
