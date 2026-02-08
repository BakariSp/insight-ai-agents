"""Tests for conversation models — camelCase serialization, enum values, optional fields."""

import pytest

from models.conversation import (
    ClarifyChoice,
    ClarifyOptions,
    ConversationRequest,
    ConversationResponse,
    FollowupIntentType,
    IntentType,
    ModelTier,
    RouterResult,
)


# ── Enum tests ────────────────────────────────────────────────


def test_intent_type_values():
    assert IntentType.CHAT_SMALLTALK.value == "chat_smalltalk"
    assert IntentType.CHAT_QA.value == "chat_qa"
    assert IntentType.BUILD_WORKFLOW.value == "build_workflow"
    assert IntentType.CLARIFY.value == "clarify"


def test_followup_intent_type_values():
    assert FollowupIntentType.CHAT.value == "chat"
    assert FollowupIntentType.REFINE.value == "refine"
    assert FollowupIntentType.REBUILD.value == "rebuild"


# ── RouterResult tests ────────────────────────────────────────


def test_router_result_camel_case():
    r = RouterResult(
        intent="build_workflow",
        confidence=0.85,
        should_build=True,
        clarifying_question=None,
        route_hint=None,
    )
    data = r.model_dump(by_alias=True)
    assert "shouldBuild" in data
    assert "clarifyingQuestion" in data
    assert "routeHint" in data
    assert data["confidence"] == 0.85


def test_router_result_with_clarify():
    r = RouterResult(
        intent="clarify",
        confidence=0.5,
        should_build=False,
        clarifying_question="Which class do you want to analyze?",
        route_hint="needClassId",
    )
    assert r.clarifying_question is not None
    assert r.route_hint == "needClassId"


# ── ClarifyOptions tests ─────────────────────────────────────


def test_clarify_options_camel_case():
    opts = ClarifyOptions(
        type="single_select",
        choices=[
            ClarifyChoice(label="Class 1A", value="c-1a", description="Form 1 Class A"),
            ClarifyChoice(label="Class 1B", value="c-1b", description="Form 1 Class B"),
        ],
        allow_custom_input=True,
    )
    data = opts.model_dump(by_alias=True)
    assert "allowCustomInput" in data
    assert data["allowCustomInput"] is True
    assert len(data["choices"]) == 2
    assert data["choices"][0]["label"] == "Class 1A"


def test_clarify_options_defaults():
    opts = ClarifyOptions()
    assert opts.type == "single_select"
    assert opts.choices == []
    assert opts.allow_custom_input is True


# ── ConversationRequest tests ─────────────────────────────────


def test_conversation_request_minimal():
    req = ConversationRequest(message="Hello")
    assert req.message == "Hello"
    assert req.language == "en"
    assert req.teacher_id == ""
    assert req.context is None
    assert req.blueprint is None
    assert req.page_context is None
    assert req.conversation_id is None


def test_conversation_request_camel_case():
    req = ConversationRequest(
        message="Analyze scores",
        teacher_id="t-001",
        conversation_id="conv-123",
    )
    data = req.model_dump(by_alias=True)
    assert "teacherId" in data
    assert "conversationId" in data
    assert "pageContext" in data


def test_conversation_request_from_camel():
    """Verify request can be constructed from camelCase input (as from frontend)."""
    req = ConversationRequest(
        **{
            "message": "Analyze scores",
            "teacherId": "t-001",
            "pageContext": {"summary": "..."},
            "conversationId": "conv-123",
        }
    )
    assert req.teacher_id == "t-001"
    assert req.page_context == {"summary": "..."}
    assert req.conversation_id == "conv-123"


# ── ConversationResponse tests ────────────────────────────────


def test_conversation_response_chat():
    resp = ConversationResponse(
        mode="entry",
        action="chat",
        chat_kind="smalltalk",
        chat_response="Hello! How can I help you?",
    )
    data = resp.model_dump(by_alias=True)
    assert data["action"] == "chat"
    assert data["mode"] == "entry"
    assert data["chatKind"] == "smalltalk"
    assert data["legacyAction"] == "chat_smalltalk"
    assert "chatResponse" in data
    assert data["chatResponse"] == "Hello! How can I help you?"
    assert data["blueprint"] is None
    assert data["clarifyOptions"] is None


def test_conversation_response_build_workflow():
    resp = ConversationResponse(
        mode="entry",
        action="build",
        chat_response="I'll generate an analysis for you.",
        blueprint=None,  # would be populated in real usage
    )
    data = resp.model_dump(by_alias=True)
    assert data["action"] == "build"
    assert data["legacyAction"] == "build_workflow"
    assert "chatResponse" in data


def test_conversation_response_clarify():
    resp = ConversationResponse(
        mode="entry",
        action="clarify",
        chat_response="Which class do you want to analyze?",
        clarify_options=ClarifyOptions(
            type="single_select",
            choices=[
                ClarifyChoice(label="1A", value="c-1a"),
                ClarifyChoice(label="1B", value="c-1b"),
            ],
        ),
    )
    data = resp.model_dump(by_alias=True)
    assert data["action"] == "clarify"
    assert data["legacyAction"] == "clarify"
    assert data["clarifyOptions"] is not None
    assert data["clarifyOptions"]["type"] == "single_select"
    assert len(data["clarifyOptions"]["choices"]) == 2


def test_conversation_response_all_actions():
    """Verify all 7 response types can be constructed with new structured fields."""
    cases = [
        ("entry", "chat", "smalltalk", "chat_smalltalk"),
        ("entry", "chat", "qa", "chat_qa"),
        ("entry", "build", None, "build_workflow"),
        ("entry", "clarify", None, "clarify"),
        ("followup", "chat", "page", "chat"),
        ("followup", "refine", None, "refine"),
        ("followup", "rebuild", None, "rebuild"),
    ]
    for mode, action, chat_kind, expected_legacy in cases:
        resp = ConversationResponse(
            mode=mode, action=action, chat_kind=chat_kind,
        )
        assert resp.action == action
        assert resp.mode == mode
        assert resp.chat_kind == chat_kind
        assert resp.legacy_action == expected_legacy


# ── resolved_entities field ──────────────────────────────────


def test_conversation_response_with_resolved_entities():
    """Verify resolved_entities serializes to camelCase."""
    from models.entity import EntityType, ResolvedEntity

    resp = ConversationResponse(
        mode="entry",
        action="build",
        chat_response="Generated analysis",
        resolved_entities=[
            ResolvedEntity(
                entity_type=EntityType.CLASS,
                entity_id="class-hk-f1a",
                display_name="Form 1A",
                confidence=1.0,
                match_type="exact",
            ),
        ],
    )
    data = resp.model_dump(by_alias=True)
    assert "resolvedEntities" in data
    assert len(data["resolvedEntities"]) == 1
    assert data["resolvedEntities"][0]["entityId"] == "class-hk-f1a"
    assert data["resolvedEntities"][0]["entityType"] == "class"
    assert data["resolvedEntities"][0]["matchType"] == "exact"


def test_conversation_response_resolved_entities_none():
    """Verify resolvedEntities defaults to null."""
    resp = ConversationResponse(mode="entry", action="chat", chat_kind="smalltalk")
    data = resp.model_dump(by_alias=True)
    assert data["resolvedEntities"] is None


# ── legacyAction computed field (Phase 4.5.3) ───────────────


def test_legacy_action_computed_field():
    """Verify legacyAction computed field produces backward-compatible values."""
    resp = ConversationResponse(mode="entry", action="build")
    assert resp.legacy_action == "build_workflow"

    resp2 = ConversationResponse(mode="entry", action="chat", chat_kind="qa")
    assert resp2.legacy_action == "chat_qa"

    resp3 = ConversationResponse(mode="followup", action="chat", chat_kind="page")
    assert resp3.legacy_action == "chat"


def test_legacy_action_in_serialized_output():
    """Verify legacyAction appears in camelCase JSON output."""
    resp = ConversationResponse(mode="entry", action="chat", chat_kind="smalltalk")
    data = resp.model_dump(by_alias=True)
    assert "legacyAction" in data
    assert data["legacyAction"] == "chat_smalltalk"


# ── ModelTier tests ──────────────────────────────────────────


def test_model_tier_enum_values():
    assert ModelTier.FAST.value == "fast"
    assert ModelTier.STANDARD.value == "standard"
    assert ModelTier.STRONG.value == "strong"
    assert ModelTier.VISION.value == "vision"


def test_router_result_model_tier_default():
    """RouterResult defaults to STANDARD tier."""
    r = RouterResult(intent="content_create", confidence=0.9)
    assert r.model_tier == ModelTier.STANDARD


def test_router_result_model_tier_serialization():
    """model_tier serializes to camelCase 'modelTier'."""
    r = RouterResult(
        intent="content_create",
        confidence=0.9,
        model_tier=ModelTier.STRONG,
    )
    data = r.model_dump(by_alias=True)
    assert "modelTier" in data
    assert data["modelTier"] == "strong"


def test_router_result_model_tier_from_string():
    """model_tier can be set from string (as LLM JSON returns)."""
    r = RouterResult(
        intent="content_create",
        confidence=0.9,
        model_tier="strong",
    )
    assert r.model_tier == ModelTier.STRONG


def test_router_result_model_tier_fast():
    r = RouterResult(
        intent="chat_smalltalk",
        confidence=0.95,
        model_tier="fast",
    )
    assert r.model_tier == ModelTier.FAST
    data = r.model_dump(by_alias=True)
    assert data["modelTier"] == "fast"


def test_router_result_model_tier_vision():
    r = RouterResult(
        intent="content_create",
        confidence=0.85,
        model_tier="vision",
    )
    assert r.model_tier == ModelTier.VISION
