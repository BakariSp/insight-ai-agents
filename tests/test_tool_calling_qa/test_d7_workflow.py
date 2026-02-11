"""D7: Studio Workflow — end-to-end multi-turn product flows.

Simulates actual Studio usage patterns:
  - PPT full flow (clarify → outline → approve → generate)
  - Quiz → Modify flow
  - RAG → Quiz flow
  - Artifact modification flow

Each test is a multi-turn sequence where each turn's result becomes
the next turn's message_history.

Uses Phase 1 mock (instant tool returns, only tests LLM decision).

Usage:
    cd insight-ai-agent
    pytest tests/test_tool_calling_qa/test_d7_workflow.py -v -s
"""

from __future__ import annotations

import json
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
    QAResult,
    _has_api_key,
)

pytestmark = pytest.mark.skipif(not _has_api_key, reason="No LLM API key")


# ── Helpers ──────────────────────────────────────────────────


def _extract_history(result: QAResult, user_msg: str) -> list[ModelMessage]:
    """Build a synthetic history from a QAResult for the next turn.

    Since mock returns don't give us real PydanticAI messages,
    we construct a realistic history manually.
    """
    history: list[ModelMessage] = []

    # User message
    history.append(ModelRequest(parts=[UserPromptPart(content=user_msg)]))

    # Tool calls + returns
    for tc in result.tool_calls_made:
        tool_name = tc["tool_name"]
        args = tc["args"]
        call_id = tc.get("tool_call_id", f"tc-{tool_name}")

        history.append(ModelResponse(parts=[
            ToolCallPart(tool_name=tool_name, args=json.dumps(args), tool_call_id=call_id),
        ]))
        mock_return = MOCK_RETURNS.get(tool_name, {"status": "ok"})
        history.append(ModelRequest(parts=[
            ToolReturnPart(tool_name=tool_name, content=json.dumps(mock_return), tool_call_id=call_id),
        ]))

    # Final assistant text
    history.append(ModelResponse(parts=[
        TextPart(content=result.output_text or "已完成。"),
    ]))

    return history


def _merge_history(prev_history: list[ModelMessage] | None, new_history: list[ModelMessage]) -> list[ModelMessage]:
    """Append new history to previous history."""
    if prev_history is None:
        return new_history
    return list(prev_history) + list(new_history)


# ── Tests ────────────────────────────────────────────────────


class TestSW01PPTFlow:
    """PPT Full Flow: request → clarify/outline → approve → generate."""

    @pytest.mark.asyncio
    async def test_ppt_turn1_outline_or_clarify(self, mock_tools):
        """Turn 1: '做一个PPT' → should propose outline or clarify topic."""
        result = await run_agent_phase1("做一个PPT", DEFAULT_MODEL)

        print(f"  [sw-01-t1] tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")
        acceptable = {"propose_pptx_outline", "ask_clarification"}
        assert result.tool_names & acceptable, (
            f"[sw-01-t1] PPT request should outline or clarify, "
            f"got: {result.tool_names_list or '(none)'}"
        )
        assert "generate_pptx" not in result.tool_names, (
            "[sw-01-t1] Must NOT skip to generate_pptx without outline"
        )

    @pytest.mark.asyncio
    async def test_ppt_turn2_after_clarify(self, mock_tools):
        """Turn 2: After clarify → provide topic → should propose outline."""
        # Simulate Turn 1: clarify
        t1_history = [
            ModelRequest(parts=[UserPromptPart(content="做一个PPT")]),
            ModelResponse(parts=[
                ToolCallPart(
                    tool_name="ask_clarification",
                    args=json.dumps({"question": "请问PPT主题是什么？", "options": ["数学", "物理"]}),
                    tool_call_id="tc-ppt-clarify",
                ),
            ]),
            ModelRequest(parts=[
                ToolReturnPart(
                    tool_name="ask_clarification",
                    content=json.dumps(MOCK_RETURNS["ask_clarification"]),
                    tool_call_id="tc-ppt-clarify",
                ),
            ]),
            ModelResponse(parts=[TextPart(content="请问PPT的主题是什么？")]),
        ]

        result = await run_agent_phase1(
            "二次函数复习课", DEFAULT_MODEL, message_history=t1_history,
        )

        print(f"  [sw-01-t2] tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")
        assert "propose_pptx_outline" in result.tool_names, (
            f"[sw-01-t2] After clarify + topic, should propose outline, "
            f"got: {result.tool_names_list or '(none)'}"
        )
        assert "generate_pptx" not in result.tool_names, (
            "[sw-01-t2] Must NOT skip to generate_pptx"
        )


class TestSW04QuizThenModify:
    """Quiz → Modify: generate quiz, then modify specific question."""

    @pytest.mark.asyncio
    async def test_quiz_modify_turn2(self, mock_tools):
        """After quiz generation → '把第3题改成填空题' → should use artifact ops."""
        # Simulate Turn 1: quiz generated
        t1_history = [
            ModelRequest(parts=[UserPromptPart(content="帮我出10道数学选择题")]),
            ModelResponse(parts=[
                ToolCallPart(
                    tool_name="generate_quiz_questions",
                    args=json.dumps({"topic": "数学", "count": 10}),
                    tool_call_id="tc-quiz-gen",
                ),
            ]),
            ModelRequest(parts=[
                ToolReturnPart(
                    tool_name="generate_quiz_questions",
                    content=json.dumps(MOCK_RETURNS["generate_quiz_questions"]),
                    tool_call_id="tc-quiz-gen",
                ),
            ]),
            ModelResponse(parts=[TextPart(content="已为您生成10道数学选择题。")]),
        ]

        deps = AgentDeps(
            teacher_id="t-qa-001",
            conversation_id="conv-qa-sw04",
            language="zh-CN",
            has_artifacts=True,  # Signal that artifacts exist
        )

        result = await run_agent_phase1(
            "把第3题改成填空题", DEFAULT_MODEL,
            deps=deps, message_history=t1_history,
        )

        print(f"  [sw-04] tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")
        acceptable = {"patch_artifact", "get_artifact", "regenerate_from_previous"}
        assert result.tool_names & acceptable, (
            f"[sw-04] Modify request should use artifact ops, "
            f"got: {result.tool_names_list or '(none)'}"
        )


class TestSW05RAGQuiz:
    """RAG → Quiz: search documents first, then generate quiz from results."""

    @pytest.mark.asyncio
    async def test_rag_then_quiz(self, mock_tools):
        """'根据知识库出题' → should search docs then generate quiz."""
        result = await run_agent_phase1("根据知识库出题", DEFAULT_MODEL)

        print(f"  [sw-05] tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")
        assert "search_teacher_documents" in result.tool_names, (
            f"[sw-05] RAG quiz must search docs first, "
            f"got: {result.tool_names_list or '(none)'}"
        )
        # May also call generate_quiz_questions in same turn (chain)
        # or ask_clarification if model wants more info
        gen_or_clarify = {"generate_quiz_questions", "ask_clarification"}
        assert result.tool_names & gen_or_clarify, (
            f"[sw-05] After search, should generate or clarify, "
            f"got: {result.tool_names_list}"
        )


class TestSW02ArtifactModify:
    """Artifact modification with has_artifacts=True."""

    @pytest.mark.asyncio
    async def test_modify_with_artifacts(self, mock_tools):
        """With artifacts present, '修改第二页的标题' → should use artifact ops."""
        deps = AgentDeps(
            teacher_id="t-qa-001",
            conversation_id="conv-qa-sw02",
            language="zh-CN",
            has_artifacts=True,
        )

        # Simulate having an artifact in history
        history = [
            ModelRequest(parts=[UserPromptPart(content="做一个关于二次函数的互动网页")]),
            ModelResponse(parts=[
                ToolCallPart(
                    tool_name="generate_interactive_html",
                    args=json.dumps({"topic": "二次函数", "description": "互动探索二次函数图像"}),
                    tool_call_id="tc-html-gen",
                ),
            ]),
            ModelRequest(parts=[
                ToolReturnPart(
                    tool_name="generate_interactive_html",
                    content=json.dumps(MOCK_RETURNS["generate_interactive_html"]),
                    tool_call_id="tc-html-gen",
                ),
            ]),
            ModelResponse(parts=[TextPart(content="已为您生成关于二次函数的互动网页。")]),
        ]

        result = await run_agent_phase1(
            "修改一下标题，改成'二次函数图像探索'", DEFAULT_MODEL,
            deps=deps, message_history=history,
        )

        print(f"  [sw-02] tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")
        acceptable = {"patch_artifact", "get_artifact", "regenerate_from_previous"}
        assert result.tool_names & acceptable, (
            f"[sw-02] Modify request with artifacts should use artifact ops, "
            f"got: {result.tool_names_list or '(none)'}"
        )
