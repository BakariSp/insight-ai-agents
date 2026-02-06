"""Tests for RouterAgent — intent classification with confidence-based routing."""

import pytest
from pydantic_ai.models.test import TestModel

from agents.router import (
    _apply_confidence_routing,
    _apply_v1_guard,
    _degrade_to_chat,
    _initial_agent,
    classify_intent,
    V1_QUIZ_KEYWORDS,
)
from models.blueprint import Blueprint
from models.conversation import IntentType, FollowupIntentType, RouterResult
from tests.test_planner import _sample_blueprint_args


# ── Confidence routing unit tests ─────────────────────────────


def test_confidence_high_build():
    """confidence ≥ 0.7 + build_workflow → should_build=True."""
    r = RouterResult(intent="build_workflow", confidence=0.85, should_build=False)
    result = _apply_confidence_routing(r)
    assert result.intent == "build_workflow"
    assert result.should_build is True


def test_confidence_medium_forces_clarify():
    """0.4 ≤ confidence < 0.7 + build_workflow → force clarify."""
    r = RouterResult(intent="build_workflow", confidence=0.55, should_build=True)
    result = _apply_confidence_routing(r)
    assert result.intent == "clarify"
    assert result.should_build is False
    assert result.clarifying_question is not None


def test_confidence_medium_clarify_keeps_question():
    """0.4 ≤ confidence < 0.7 + clarify with existing question → keep question."""
    r = RouterResult(
        intent="clarify",
        confidence=0.5,
        should_build=False,
        clarifying_question="Which class?",
    )
    result = _apply_confidence_routing(r)
    assert result.intent == "clarify"
    assert result.clarifying_question == "Which class?"


def test_confidence_low_forces_chat():
    """confidence < 0.4 + build_workflow → force chat_smalltalk."""
    r = RouterResult(intent="build_workflow", confidence=0.3, should_build=True)
    result = _apply_confidence_routing(r)
    assert result.intent == "chat_smalltalk"
    assert result.should_build is False


def test_confidence_low_keeps_chat():
    """confidence < 0.4 + already chat → keep as is."""
    r = RouterResult(intent="chat_smalltalk", confidence=0.2, should_build=False)
    result = _apply_confidence_routing(r)
    assert result.intent == "chat_smalltalk"
    assert result.should_build is False


def test_confidence_medium_chat_qa_passthrough():
    """0.4 ≤ confidence < 0.7 + chat_qa → no override (not build/clarify)."""
    r = RouterResult(intent="chat_qa", confidence=0.6, should_build=False)
    result = _apply_confidence_routing(r)
    assert result.intent == "chat_qa"
    assert result.should_build is False


# ── Agent-level tests (TestModel) ─────────────────────────────


def _router_output(intent: str, confidence: float, **kwargs) -> dict:
    """Build a RouterResult dict for TestModel."""
    return {
        "intent": intent,
        "confidence": confidence,
        "should_build": kwargs.get("should_build", False),
        "clarifying_question": kwargs.get("clarifying_question"),
        "route_hint": kwargs.get("route_hint"),
    }


@pytest.mark.asyncio
async def test_classify_smalltalk():
    """Greeting message → chat_smalltalk."""
    test_model = TestModel(
        custom_output_args=_router_output("chat_smalltalk", 0.95),
    )
    result = await _initial_agent.run("你好", model=test_model)
    r = result.output
    assert r.intent == "chat_smalltalk"
    assert r.confidence >= 0.8


@pytest.mark.asyncio
async def test_classify_build_workflow():
    """Clear analytical request → build_workflow with high confidence."""
    test_model = TestModel(
        custom_output_args=_router_output(
            "build_workflow", 0.9, should_build=True,
        ),
    )
    result = await _initial_agent.run(
        "分析 1A 班英语成绩", model=test_model,
    )
    r = result.output
    assert r.intent == "build_workflow"
    assert r.confidence >= 0.7


@pytest.mark.asyncio
async def test_classify_clarify():
    """Vague request → clarify with medium confidence."""
    test_model = TestModel(
        custom_output_args=_router_output(
            "clarify",
            0.55,
            clarifying_question="请问您想分析哪个班级？",
            route_hint="needClassId",
        ),
    )
    result = await _initial_agent.run("分析英语表现", model=test_model)
    r = result.output
    assert r.intent == "clarify"
    assert r.clarifying_question is not None
    assert r.route_hint == "needClassId"


@pytest.mark.asyncio
async def test_classify_intent_initial_mode():
    """classify_intent in initial mode (no blueprint)."""
    test_model = TestModel(
        custom_output_args=_router_output("chat_qa", 0.85),
    )
    result = await _initial_agent.run("KPI 是什么意思", model=test_model)
    r = result.output
    assert r.intent == "chat_qa"


@pytest.mark.asyncio
async def test_classify_intent_followup_mode():
    """classify_intent in followup mode (with blueprint) returns followup intent."""
    bp = Blueprint(**_sample_blueprint_args())
    test_model = TestModel(
        custom_output_args=_router_output("chat", 0.8),
    )
    # Build a followup agent manually for testing
    from pydantic_ai import Agent
    from config.prompts.router import build_router_prompt

    followup_agent = Agent(
        model=test_model,
        output_type=RouterResult,
        system_prompt=build_router_prompt(
            blueprint_name=bp.name,
            blueprint_description=bp.description,
            page_summary="Test summary",
        ),
        retries=1,
        defer_model_check=True,
    )
    result = await followup_agent.run("哪些学生需要关注？")
    r = result.output
    assert r.intent == "chat"
    assert r.confidence >= 0.7


@pytest.mark.asyncio
async def test_followup_refine():
    """Follow-up refine intent."""
    bp = Blueprint(**_sample_blueprint_args())
    test_model = TestModel(
        custom_output_args=_router_output("refine", 0.85, should_build=True),
    )
    from pydantic_ai import Agent
    from config.prompts.router import build_router_prompt

    followup_agent = Agent(
        model=test_model,
        output_type=RouterResult,
        system_prompt=build_router_prompt(
            blueprint_name=bp.name,
            blueprint_description=bp.description,
        ),
        retries=1,
        defer_model_check=True,
    )
    result = await followup_agent.run("把图表颜色换成蓝色")
    r = result.output
    assert r.intent == "refine"
    assert r.should_build is True


@pytest.mark.asyncio
async def test_followup_rebuild():
    """Follow-up rebuild intent."""
    bp = Blueprint(**_sample_blueprint_args())
    test_model = TestModel(
        custom_output_args=_router_output("rebuild", 0.9, should_build=True),
    )
    from pydantic_ai import Agent
    from config.prompts.router import build_router_prompt

    followup_agent = Agent(
        model=test_model,
        output_type=RouterResult,
        system_prompt=build_router_prompt(
            blueprint_name=bp.name,
            blueprint_description=bp.description,
        ),
        retries=1,
        defer_model_check=True,
    )
    result = await followup_agent.run("加一个语法分析板块")
    r = result.output
    assert r.intent == "rebuild"
    assert r.should_build is True


# ── refine_scope tests (Phase 6.4) ────────────────────────────


def test_router_result_refine_scope_serialization():
    """RouterResult.refine_scope serializes to camelCase."""
    result = RouterResult(
        intent="refine",
        confidence=0.85,
        should_build=True,
        refine_scope="patch_layout",
    )

    data = result.model_dump(by_alias=True)

    assert "refineScope" in data
    assert data["refineScope"] == "patch_layout"


def test_router_result_refine_scope_optional():
    """RouterResult.refine_scope is optional (None by default)."""
    result = RouterResult(
        intent="chat",
        confidence=0.9,
    )

    assert result.refine_scope is None
    data = result.model_dump(by_alias=True)
    assert data.get("refineScope") is None


def test_router_result_refine_scope_patch_compose():
    """RouterResult accepts patch_compose scope."""
    result = RouterResult(
        intent="refine",
        confidence=0.8,
        should_build=True,
        refine_scope="patch_compose",
    )

    assert result.refine_scope == "patch_compose"


@pytest.mark.asyncio
async def test_followup_refine_with_scope():
    """Follow-up refine intent includes refine_scope."""
    bp = Blueprint(**_sample_blueprint_args())
    test_model = TestModel(
        custom_output_args={
            "intent": "refine",
            "confidence": 0.85,
            "should_build": True,
            "clarifying_question": None,
            "route_hint": None,
            "refine_scope": "patch_layout",
        },
    )
    from pydantic_ai import Agent
    from config.prompts.router import build_router_prompt

    followup_agent = Agent(
        model=test_model,
        output_type=RouterResult,
        system_prompt=build_router_prompt(
            blueprint_name=bp.name,
            blueprint_description=bp.description,
        ),
        retries=1,
        defer_model_check=True,
    )
    result = await followup_agent.run("把图表颜色换成蓝色")
    r = result.output
    assert r.intent == "refine"
    assert r.refine_scope == "patch_layout"


# ── V1 Capability Guard tests ────────────────────────────────


def test_v1_guard_quiz_keyword_allows_build():
    """V1 guard allows build when quiz keywords present."""
    r = RouterResult(intent="build_workflow", confidence=0.85, should_build=True)
    result = _apply_v1_guard(r, "帮我出10道语法选择题")
    assert result.should_build is True
    assert result.intent == "build_workflow"


def test_v1_guard_english_quiz_keyword_allows_build():
    """V1 guard allows build for English quiz keywords."""
    r = RouterResult(intent="build_workflow", confidence=0.85, should_build=True)
    result = _apply_v1_guard(r, "Generate 5 MCQ on grammar")
    assert result.should_build is True


def test_v1_guard_non_quiz_hint_degrades():
    """V1 guard degrades non-quiz hint to chat."""
    r = RouterResult(
        intent="build_workflow",
        confidence=0.85,
        should_build=True,
        route_hint="lesson_plan",
    )
    result = _apply_v1_guard(r, "帮我做一个课程计划")
    assert result.should_build is False
    assert result.intent == "chat_qa"
    assert "题目生成" in result.clarifying_question


def test_v1_guard_ppt_hint_degrades():
    """V1 guard degrades PPT generation to chat."""
    r = RouterResult(
        intent="build_workflow",
        confidence=0.9,
        should_build=True,
        route_hint="ppt_generation",
    )
    result = _apply_v1_guard(r, "Generate a presentation for Unit 5")
    assert result.should_build is False
    assert result.intent == "chat_qa"
    assert "quiz generation" in result.clarifying_question.lower()


def test_v1_guard_non_build_passthrough():
    """V1 guard does not affect non-build intents."""
    r = RouterResult(intent="chat_qa", confidence=0.9, should_build=False)
    result = _apply_v1_guard(r, "什么是KPI？")
    assert result.intent == "chat_qa"
    assert result.should_build is False


def test_v1_guard_no_hint_no_keyword_allows():
    """V1 guard allows build when no explicit non-quiz hint and LLM says build."""
    r = RouterResult(intent="build_workflow", confidence=0.85, should_build=True)
    result = _apply_v1_guard(r, "分析 1A 班英语成绩")
    assert result.should_build is True


def test_v1_quiz_keywords_match_chinese():
    """V1_QUIZ_KEYWORDS matches Chinese quiz terms."""
    assert V1_QUIZ_KEYWORDS.search("帮我出题")
    assert V1_QUIZ_KEYWORDS.search("生成10道题")
    assert V1_QUIZ_KEYWORDS.search("英语练习")
    assert V1_QUIZ_KEYWORDS.search("选择题")
    assert V1_QUIZ_KEYWORDS.search("填空题")


def test_v1_quiz_keywords_match_english():
    """V1_QUIZ_KEYWORDS matches English quiz terms."""
    assert V1_QUIZ_KEYWORDS.search("Generate quiz")
    assert V1_QUIZ_KEYWORDS.search("Create MCQ questions")
    assert V1_QUIZ_KEYWORDS.search("practice exercise")
    assert V1_QUIZ_KEYWORDS.search("assessment")


def test_v1_quiz_keywords_no_false_positive():
    """V1_QUIZ_KEYWORDS should not match unrelated text."""
    assert not V1_QUIZ_KEYWORDS.search("你好")
    assert not V1_QUIZ_KEYWORDS.search("天气怎么样")
    assert not V1_QUIZ_KEYWORDS.search("KPI是什么")


def test_degrade_to_chat_chinese():
    """Degradation message is Chinese for Chinese input."""
    r = RouterResult(intent="build_workflow", confidence=0.85, should_build=True)
    result = _degrade_to_chat(r, "帮我做课件")
    assert "题目生成" in result.clarifying_question
    assert result.should_build is False


def test_degrade_to_chat_english():
    """Degradation message is English for English input."""
    r = RouterResult(intent="build_workflow", confidence=0.85, should_build=True)
    result = _degrade_to_chat(r, "Make a lesson plan")
    assert "quiz generation" in result.clarifying_question.lower()
    assert result.should_build is False
