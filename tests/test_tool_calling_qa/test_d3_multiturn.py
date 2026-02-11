"""D3: Multi-Turn Context — verify context inheritance, topic switching, and
clarify→execute flows across conversation turns.

Uses Phase 1 mock (instant tool returns, only tests LLM decision).

Usage:
    cd insight-ai-agent
    pytest tests/test_tool_calling_qa/test_d3_multiturn.py -v -s
"""

from __future__ import annotations

import pytest

import tools.native_tools  # noqa: F401

from agents.native_agent import AgentDeps
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from tests.test_tool_calling_qa.conftest import (
    DEFAULT_MODEL,
    MOCK_RETURNS,
    run_agent_phase1,
    build_chat_history,
    _has_api_key,
)

pytestmark = pytest.mark.skipif(not _has_api_key, reason="No LLM API key")


# ── History builders for specific scenarios ──────────────────


def _clarify_history(user_msg: str, clarify_question: str) -> list[ModelMessage]:
    """Turn 1: user asks vague → agent clarifies."""
    import json
    return [
        ModelRequest(parts=[UserPromptPart(content=user_msg)]),
        ModelResponse(parts=[
            ToolCallPart(
                tool_name="ask_clarification",
                args=json.dumps({"question": clarify_question, "options": ["数学", "英语", "物理"]}),
                tool_call_id="tc-clarify-1",
            ),
        ]),
        ModelRequest(parts=[
            ToolReturnPart(
                tool_name="ask_clarification",
                content=json.dumps(MOCK_RETURNS["ask_clarification"]),
                tool_call_id="tc-clarify-1",
            ),
        ]),
        ModelResponse(parts=[TextPart(content=clarify_question)]),
    ]


def _quiz_success_history(topic: str = "数学二次函数") -> list[ModelMessage]:
    """Turn 1: user requested quiz → agent generated successfully."""
    import json
    return [
        ModelRequest(parts=[UserPromptPart(content=f"帮我出5道{topic}选择题")]),
        ModelResponse(parts=[
            ToolCallPart(
                tool_name="generate_quiz_questions",
                args=json.dumps({"topic": topic, "count": 5, "types": ["选择题"]}),
                tool_call_id="tc-quiz-1",
            ),
        ]),
        ModelRequest(parts=[
            ToolReturnPart(
                tool_name="generate_quiz_questions",
                content=json.dumps(MOCK_RETURNS["generate_quiz_questions"]),
                tool_call_id="tc-quiz-1",
            ),
        ]),
        ModelResponse(parts=[TextPart(
            content="已为您生成5道数学二次函数选择题。请查看右侧的题目卡片。"
        )]),
    ]


def _data_query_history() -> list[ModelMessage]:
    """Turn 1: user queried class data → agent returned results."""
    import json
    return [
        ModelRequest(parts=[UserPromptPart(content="帮我看看三年一班的情况")]),
        ModelResponse(parts=[
            ToolCallPart(
                tool_name="get_teacher_classes",
                args="{}",
                tool_call_id="tc-classes-1",
            ),
        ]),
        ModelRequest(parts=[
            ToolReturnPart(
                tool_name="get_teacher_classes",
                content=json.dumps(MOCK_RETURNS["get_teacher_classes"]),
                tool_call_id="tc-classes-1",
            ),
        ]),
        ModelResponse(parts=[
            ToolCallPart(
                tool_name="get_class_detail",
                args=json.dumps({"class_id": "c-001"}),
                tool_call_id="tc-detail-1",
            ),
        ]),
        ModelRequest(parts=[
            ToolReturnPart(
                tool_name="get_class_detail",
                content=json.dumps(MOCK_RETURNS["get_class_detail"]),
                tool_call_id="tc-detail-1",
            ),
        ]),
        ModelResponse(parts=[TextPart(
            content="三年一班共30名学生，目前有5个作业。"
        )]),
    ]


def _interactive_clarify_history() -> list[ModelMessage]:
    """Turn 1: user asks for interactive page → agent clarifies topic."""
    import json
    return [
        ModelRequest(parts=[UserPromptPart(content="做一个互动网页")]),
        ModelResponse(parts=[
            ToolCallPart(
                tool_name="ask_clarification",
                args=json.dumps({"question": "请问您想做什么主题的互动网页？", "options": ["太阳系", "细胞分裂", "化学反应"]}),
                tool_call_id="tc-clarify-i1",
            ),
        ]),
        ModelRequest(parts=[
            ToolReturnPart(
                tool_name="ask_clarification",
                content=json.dumps(MOCK_RETURNS["ask_clarification"]),
                tool_call_id="tc-clarify-i1",
            ),
        ]),
        ModelResponse(parts=[TextPart(content="请问您想做什么主题的互动网页？")]),
    ]


# ── Test cases ───────────────────────────────────────────────


class TestD3ClarifyThenExecute:
    """After clarification, the next turn should execute, not clarify again."""

    @pytest.mark.asyncio
    async def test_mt01_clarify_then_quiz(self, mock_tools):
        """'帮我出题' → clarify → '数学二次函数' → should call generate_quiz_questions."""
        history = _clarify_history("帮我出题", "请问您想出什么科目的题目？")
        result = await run_agent_phase1("数学二次函数", DEFAULT_MODEL, message_history=history)

        print(f"  mt-01: tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")
        assert "generate_quiz_questions" in result.tool_names, (
            f"[mt-01] After clarify, '数学二次函数' should trigger generate_quiz_questions, "
            f"got: {result.tool_names_list or '(none)'}"
        )

    @pytest.mark.asyncio
    async def test_mt06_clarify_then_interactive(self, mock_tools):
        """'做互动网页' → clarify → '太阳系行星' → should call generate_interactive_html."""
        history = _interactive_clarify_history()
        result = await run_agent_phase1("太阳系行星", DEFAULT_MODEL, message_history=history)

        print(f"  mt-06: tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")
        assert "generate_interactive_html" in result.tool_names, (
            f"[mt-06] After clarify, '太阳系行星' should trigger generate_interactive_html, "
            f"got: {result.tool_names_list or '(none)'}"
        )

    @pytest.mark.asyncio
    async def test_mt07_clarify_then_ppt(self, mock_tools):
        """'帮我做PPT' → clarify → '二次函数复习课' → should call propose_pptx_outline."""
        history = _clarify_history("帮我做PPT", "请问您想做什么主题的PPT？")
        result = await run_agent_phase1("二次函数复习课", DEFAULT_MODEL, message_history=history)

        print(f"  mt-07: tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")
        assert "propose_pptx_outline" in result.tool_names, (
            f"[mt-07] After PPT clarify, should trigger propose_pptx_outline, "
            f"got: {result.tool_names_list or '(none)'}"
        )


class TestD3ContextInheritance:
    """Subsequent turns should inherit context from previous turns."""

    @pytest.mark.asyncio
    async def test_mt02_repeat_similar(self, mock_tools):
        """After quiz success → '再出5道类似的' → should call generate_quiz_questions."""
        history = _quiz_success_history()
        result = await run_agent_phase1("再出5道类似的", DEFAULT_MODEL, message_history=history)

        print(f"  mt-02: tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")
        # Should inherit quiz context and generate again
        acceptable = {"generate_quiz_questions", "regenerate_from_previous"}
        assert result.tool_names & acceptable, (
            f"[mt-02] '再出5道类似的' after quiz should re-generate, "
            f"got: {result.tool_names_list or '(none)'}"
        )

    @pytest.mark.asyncio
    async def test_mt10_inherit_class_context(self, mock_tools):
        """After class data query → '张三的数学成绩怎么样' → should query student grades."""
        history = _data_query_history()
        result = await run_agent_phase1(
            "张三的数学成绩怎么样", DEFAULT_MODEL, message_history=history,
        )

        print(f"  mt-10: tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")
        # Should use class context and query student grades
        acceptable = {"get_student_grades", "resolve_entity", "get_class_detail"}
        assert result.tool_names & acceptable, (
            f"[mt-10] After class query, student grade query should use data tools, "
            f"got: {result.tool_names_list or '(none)'}"
        )


class TestD3TopicSwitch:
    """Topic switches should NOT carry over old intent."""

    @pytest.mark.asyncio
    async def test_mt03_switch_to_chat(self, mock_tools):
        """After data analysis → '你好' → should NOT call tools."""
        history = _data_query_history()
        result = await run_agent_phase1("你好", DEFAULT_MODEL, message_history=history)

        print(f"  mt-03: tools={result.tool_names_list or '(none)'} ({result.latency_ms:.0f}ms)")
        # ask_clarification is a soft-fail (cautious), any data/gen tool is hard-fail
        data_gen_tools = {
            "get_teacher_classes", "get_class_detail", "get_assignment_submissions",
            "generate_quiz_questions", "generate_interactive_html",
        }
        triggered_bad = result.tool_names & data_gen_tools
        assert not triggered_bad, (
            f"[mt-03] '你好' after analysis should NOT trigger data/gen tools, "
            f"but got: {list(triggered_bad)}"
        )

    @pytest.mark.asyncio
    async def test_mt09_eval_not_new_request(self, mock_tools):
        """After quiz → '这些题目怎么样，难度合适吗？' → should NOT call tools."""
        history = _quiz_success_history()
        result = await run_agent_phase1(
            "这些题目怎么样，难度合适吗？", DEFAULT_MODEL, message_history=history,
        )

        print(f"  mt-09: tools={result.tool_names_list or '(none)'} ({result.latency_ms:.0f}ms)")
        gen_tools = {"generate_quiz_questions", "generate_interactive_html", "propose_pptx_outline"}
        triggered_gen = result.tool_names & gen_tools
        assert not triggered_gen, (
            f"[mt-09] Evaluation question should NOT trigger generation, "
            f"but got: {list(triggered_gen)}"
        )


class TestD3HistoryResistance:
    """Deep chat history should not interfere with clear tool requests."""

    @pytest.mark.asyncio
    async def test_mt08_deep_chat_then_tool(self, mock_tools):
        """8 turns of small talk → '帮我出5道英语选择题' → should still call tool."""
        history = build_chat_history(8)
        result = await run_agent_phase1(
            "帮我出5道英语选择题", DEFAULT_MODEL, message_history=history,
        )

        print(f"  mt-08: tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")
        assert "generate_quiz_questions" in result.tool_names, (
            f"[mt-08] After 8 turns of chat, clear quiz request should still work, "
            f"got: {result.tool_names_list or '(none)'}"
        )
