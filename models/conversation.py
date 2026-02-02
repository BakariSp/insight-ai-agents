"""Conversation models — intent routing, clarify interaction, unified request/response.

Defines the data contracts for Phase 4's unified conversation gateway:
- Intent classification (initial + follow-up modes)
- Clarify interactive options
- Unified ConversationRequest / ConversationResponse
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field

from models.base import CamelModel
from models.blueprint import Blueprint


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

    The ``action`` field determines which response fields are populated:

    | action           | mode     | key fields                        |
    |------------------|----------|-----------------------------------|
    | chat_smalltalk   | initial  | chatResponse                      |
    | chat_qa          | initial  | chatResponse                      |
    | build_workflow   | initial  | blueprint, chatResponse            |
    | clarify          | initial  | chatResponse, clarifyOptions       |
    | chat             | followup | chatResponse                      |
    | refine           | followup | blueprint, chatResponse            |
    | rebuild          | followup | blueprint, chatResponse            |
    """

    action: str
    chat_response: str | None = None
    blueprint: Blueprint | None = None
    clarify_options: ClarifyOptions | None = None
    conversation_id: str | None = None
