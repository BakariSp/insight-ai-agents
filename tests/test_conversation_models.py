"""Tests for conversation models — camelCase serialization, enum values, optional fields."""

import pytest

from models.conversation import (
    ClarifyChoice,
    ClarifyOptions,
    ConversationRequest,
    ConversationResponse,
    FollowupIntentType,
    IntentType,
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
        action="chat_smalltalk",
        chat_response="Hello! How can I help you?",
    )
    data = resp.model_dump(by_alias=True)
    assert data["action"] == "chat_smalltalk"
    assert "chatResponse" in data
    assert data["chatResponse"] == "Hello! How can I help you?"
    assert data["blueprint"] is None
    assert data["clarifyOptions"] is None


def test_conversation_response_build_workflow():
    resp = ConversationResponse(
        action="build_workflow",
        chat_response="I'll generate an analysis for you.",
        blueprint=None,  # would be populated in real usage
    )
    data = resp.model_dump(by_alias=True)
    assert data["action"] == "build_workflow"
    assert "chatResponse" in data


def test_conversation_response_clarify():
    resp = ConversationResponse(
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
    assert data["clarifyOptions"] is not None
    assert data["clarifyOptions"]["type"] == "single_select"
    assert len(data["clarifyOptions"]["choices"]) == 2


def test_conversation_response_all_actions():
    """Verify all 7 action types can be set."""
    for action in [
        "chat_smalltalk",
        "chat_qa",
        "build_workflow",
        "clarify",
        "chat",
        "refine",
        "rebuild",
    ]:
        resp = ConversationResponse(action=action)
        assert resp.action == action


# ── resolved_entities field ──────────────────────────────────


def test_conversation_response_with_resolved_entities():
    """Verify resolved_entities serializes to camelCase."""
    from models.entity import ResolvedEntity

    resp = ConversationResponse(
        action="build_workflow",
        chat_response="Generated analysis",
        resolved_entities=[
            ResolvedEntity(
                class_id="class-hk-f1a",
                display_name="Form 1A",
                confidence=1.0,
                match_type="exact",
            ),
        ],
    )
    data = resp.model_dump(by_alias=True)
    assert "resolvedEntities" in data
    assert len(data["resolvedEntities"]) == 1
    assert data["resolvedEntities"][0]["classId"] == "class-hk-f1a"
    assert data["resolvedEntities"][0]["matchType"] == "exact"


def test_conversation_response_resolved_entities_none():
    """Verify resolvedEntities defaults to null."""
    resp = ConversationResponse(action="chat_smalltalk")
    data = resp.model_dump(by_alias=True)
    assert data["resolvedEntities"] is None
