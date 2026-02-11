"""Tool contract models — Step 1.0 of AI native rewrite.

Defines ToolResult envelope, Artifact data model, and status constants.
These contracts are frozen after Step 1 (see protocol-freeze-v1.md).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Content Format ───────────────────────────────────────────


class ContentFormat(str, Enum):
    """Supported content formats for artifacts."""

    JSON = "json"
    MARKDOWN = "markdown"
    HTML = "html"
    URL = "url"


# ── Artifact Model (frozen — protocol-freeze-v1) ────────────


class ArtifactResource(BaseModel):
    """Artifact-associated resource (image, JS lib, etc.)."""

    id: str
    storage: Literal["inline", "attached", "external"]
    mime_type: str | None = None
    url: str | None = None
    data: str | None = None


class Artifact(BaseModel):
    """Unified artifact data model.

    - ``artifact_type``: business object kind (quiz / ppt / doc / interactive)
    - ``content_format``: technical format (json / markdown / html / url)
    """

    artifact_id: str
    artifact_type: str
    content_format: ContentFormat
    content: Any
    resources: list[ArtifactResource] = Field(default_factory=list)
    version: int = 1


# ── ToolResult Envelope ──────────────────────────────────────


class ToolResult(BaseModel):
    """Structured return envelope for generation / RAG / write / clarify tools.

    Data-only tools (get_teacher_classes, calculate_stats) return plain dicts
    with a ``status`` field.  Generation / mutation tools MUST use this envelope
    so ``stream_adapter`` can emit correct SSE events without text heuristics.
    """

    data: Any
    artifact_type: str | None = None
    content_format: str | None = None
    action: str = "complete"  # "complete" | "clarify" | "partial"
    status: str = "ok"  # "ok" | "error" | "partial"


# ── Clarify Event ────────────────────────────────────────────


class ClarifyChoice(BaseModel):
    """A single option in a clarify interaction."""

    label: str
    value: str
    description: str = ""


class ClarifyEvent(BaseModel):
    """Structured clarify response — replaces text-based clarify detection."""

    question: str
    options: list[ClarifyChoice] = Field(default_factory=list)
    allow_custom_input: bool = True


# ── RAG Status Constants ─────────────────────────────────────

RAG_STATUS_OK = "ok"
RAG_STATUS_NO_RESULT = "no_result"
RAG_STATUS_ERROR = "error"
RAG_STATUS_DEGRADED = "degraded"
