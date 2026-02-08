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
from models.patch import PatchPlan
from models.skill_config import SkillConfig


# ── Multimodal attachment ────────────────────────────────────


class Attachment(CamelModel):
    """A file attached to a conversation message (e.g. image)."""

    file_id: str
    url: str  # Signed OSS URL from Java backend (may be near expiry)
    mime_type: str = "image/jpeg"
    filename: str = ""


# ── Intent enums ──────────────────────────────────────────────


class ModelTier(str, Enum):
    """Model quality tier — decided by Router alongside intent classification.

    Controls which LLM model is used for the task:
    - FAST: cheap + fast for trivial tasks (chat, translation)
    - STANDARD: balanced for general content generation (lesson plans, PPT, docs)
    - STRONG: best quality for complex tasks (interactive content, quiz, deep analysis)
    - VISION: multimodal model for image understanding
    """

    FAST = "fast"
    STANDARD = "standard"
    STRONG = "strong"
    VISION = "vision"


class IntentType(str, Enum):
    """Initial-mode intent types (no existing blueprint context)."""

    CHAT_SMALLTALK = "chat_smalltalk"
    CHAT_QA = "chat_qa"
    BUILD_WORKFLOW = "build_workflow"
    QUIZ_GENERATE = "quiz_generate"  # Skill fast-path: direct quiz generation
    CONTENT_CREATE = "content_create"  # Agent Path: general content generation
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
    refine_scope: str | None = None  # Phase 6.4: "patch_layout", "patch_compose", or "full_rebuild"

    # ── Path routing (Agent Path) ────────────────────────────
    path: str = "skill"  # "skill" | "blueprint" | "agent" | "chat"
    suggested_tools: list[str] = Field(default_factory=list)

    # ── Model routing ────────────────────────────────────────
    model_tier: ModelTier = ModelTier.STANDARD

    # ── Skill / Canvas extensions ────────────────────────────
    extracted_params: dict = Field(default_factory=dict)
    completeness: float = 0.0  # 0-1, how sufficient are the known params
    critical_missing: list[str] = Field(default_factory=list)
    suggested_skills: list[str] = Field(default_factory=list)
    enable_rag: bool = False
    strategy: str = "direct_generate"  # direct_generate | ask_one_question | show_context


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
    attachments: list[Attachment] = Field(default_factory=list)
    language: str = "en"
    teacher_id: str = ""
    context: dict | None = None
    blueprint: Blueprint | None = None
    page_context: dict | None = None
    conversation_id: str | None = None
    skill_config: SkillConfig | None = None  # Skill toggles (RAG, file context)


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
    patch_plan: PatchPlan | None = None  # Phase 6.4: for refine with scope != full_rebuild

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
