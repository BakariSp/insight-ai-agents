"""Entity resolution models — resolved class references from natural language.

Defines output models for the entity resolver service, which matches
natural-language class mentions (e.g. "1A班", "Form 1A") to concrete IDs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from models.base import CamelModel


class ResolvedEntity(CamelModel):
    """A single resolved entity (class) with confidence and match metadata."""

    class_id: str
    display_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    match_type: Literal["exact", "alias", "grade", "fuzzy"]


class ResolveResult(CamelModel):
    """Output of entity resolution — zero or more matched classes."""

    matches: list[ResolvedEntity] = Field(default_factory=list)
    is_ambiguous: bool = False
    scope_mode: Literal["none", "single", "multi", "grade"] = "none"
