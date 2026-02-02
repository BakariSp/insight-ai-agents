"""Conversation models — intent routing, clarify interaction, unified request/response.

Defines the data contracts for Phase 4's unified conversation gateway:
- Intent classification (initial + follow-up modes)
- Clarify interactive options
- Unified ConversationRequest / ConversationResponse
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, computed_field

from models.base import CamelModel
from models.blueprint import Blueprint
from models.entity import ResolvedEntity


# ── Intent enums ──────────────────────────────────────────────


class IntentType(str, Enum):
    """Initial-mode intent types (no existing blueprint context)."""

    CHAT_SMALLTALK = "chat_smalltalk"
    CHAT_QA = "chat_qa"
    BUILD_WORKFLOW = "build_workflow"
    CLARIFY = "clarify"


class FollowupIntentType(str, Enum):
    """Follow-up-mode intent types (existing blueprint context)."""

    CHAT = "chat"
    REFINE = "refine"
    REBUILD = "rebuild"


# ── Router output ─────────────────────────────────────────────


class RouterResult(CamelModel):
    """Output of RouterAgent intent classification."""

    intent: str
    confidence: float = Field(ge=0.0, le=1.0)
    should_build: bool = False
    clarifying_question: str | None = None
    route_hint: str | None = None


# ── Clarify interaction ───────────────────────────────────────


class ClarifyChoice(CamelModel):
    """A single option in a clarify interaction."""

    label: str
    value: str
    description: str = ""


class ClarifyOptions(CamelModel):
    """Structured options for interactive clarification."""

    type: Literal["single_select", "multi_select"] = "single_select"
    choices: list[ClarifyChoice] = Field(default_factory=list)
    allow_custom_input: bool = True


# ── Unified request / response ────────────────────────────────


class ConversationRequest(CamelModel):
    """POST /api/conversation — unified request body."""

    message: str
    language: str = "en"
    teacher_id: str = ""
    context: dict | None = None
    blueprint: Blueprint | None = None
    page_context: dict | None = None
    conversation_id: str | None = None


class ConversationResponse(CamelModel):
    """POST /api/conversation — unified response body.

    Uses a structured ``mode`` + ``action`` + ``chatKind`` triple to classify
    the response type.  A backward-compatible ``legacyAction`` computed field
    produces the Phase-4 single-string action values for older consumers.

    | mode     | action  | chatKind  | legacyAction   | key fields              |
    |----------|---------|-----------|----------------|-------------------------|
    | entry    | chat    | smalltalk | chat_smalltalk | chatResponse            |
    | entry    | chat    | qa        | chat_qa        | chatResponse            |
    | entry    | build   | —         | build_workflow | blueprint, chatResponse |
    | entry    | clarify | —         | clarify        | chatResponse, options   |
    | followup | chat    | page      | chat           | chatResponse            |
    | followup | refine  | —         | refine         | blueprint, chatResponse |
    | followup | rebuild | —         | rebuild        | blueprint, chatResponse |
    """

    mode: Literal["entry", "followup"]
    action: Literal["chat", "build", "clarify", "refine", "rebuild"]
    chat_kind: Literal["smalltalk", "qa", "page"] | None = None
    chat_response: str | None = None
    blueprint: Blueprint | None = None
    clarify_options: ClarifyOptions | None = None
    conversation_id: str | None = None
    resolved_entities: list[ResolvedEntity] | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def legacy_action(self) -> str:
        """Backward-compatible action string matching Phase 4 convention."""
        if self.action == "chat":
            if self.chat_kind == "smalltalk":
                return "chat_smalltalk"
            if self.chat_kind == "qa":
                return "chat_qa"
            return "chat"
        if self.action == "build":
            return "build_workflow"
        return self.action
