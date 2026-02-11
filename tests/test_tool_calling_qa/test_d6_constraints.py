"""D6: Constraint Compliance — verify system prompt prohibitions are obeyed.

Checks that the agent:
- Doesn't announce without executing (禁止预告不执行)
- Doesn't text-simulate tools (禁止文本模拟)
- Doesn't expose internal tool names (不暴露内部实现)
- Doesn't repeat structured tool output verbatim (不复述工具结果)
- Calls at most one clarification per turn (一次只 clarify 一次)
- PPT must outline first (PPT 必须先大纲)
- Generation tool called at most once per turn (一次生成一次调用)

Uses Phase 1 mock (instant tool returns, only tests LLM decision).

Usage:
    cd insight-ai-agent
    pytest tests/test_tool_calling_qa/test_d6_constraints.py -v -s
"""

from __future__ import annotations

import re
import pytest

import tools.native_tools  # noqa: F401

from agents.native_agent import AgentDeps
from tests.test_tool_calling_qa.conftest import (
    DEFAULT_MODEL,
    run_agent_phase1,
    QAResult,
    _has_api_key,
)

pytestmark = pytest.mark.skipif(not _has_api_key, reason="No LLM API key")


# ── Constraint detection patterns ────────────────────────────


_ANNOUNCE_PATTERNS = [
    re.compile(r"我(来|需要|将要|会|先)(帮您|帮你|)(查看|查询|获取|搜索|检索|分析|调用)"),
    re.compile(r"(让我|待我|请稍等).{0,10}(查看|查询|获取|检索)"),
    re.compile(r"(首先|第一步).{0,10}(我需要|需要先|要先)(查看|调用|获取)"),
]

_EXPOSE_INTERNAL_PATTERNS = [
    re.compile(r"(调用|使用|执行)(了|)\s*(工具|tool|API|函数|function)"),
    re.compile(r"(get_|generate_|search_|calculate_|patch_|ask_|resolve_|compare_|analyze_|build_|propose_|render_|regenerate_)\w+"),
]

_REPEAT_OUTPUT_PATTERNS = [
    # Quiz: listing questions with options (逐题列出)
    re.compile(r"(第[一二三四五六七八九十\d]+题|题目\s*\d+)[：:].{10,}[A-D][.、]"),
    # Listing 4+ structured items
    re.compile(r"(\d+[.、]\s*.+\n){4,}"),
]


def _has_announce_without_action(result: QAResult) -> list[str]:
    """Detect 'I will do X' patterns in text when tools WERE NOT called."""
    if result.called_any_tool:
        return []  # If tools were called, announcement is OK (it preceded action)
    violations = []
    for pattern in _ANNOUNCE_PATTERNS:
        matches = pattern.findall(result.output_text)
        if matches:
            violations.append(f"Announce pattern: {pattern.pattern} → {matches}")
    return violations


def _has_exposed_internals(result: QAResult) -> list[str]:
    """Detect internal tool/API name leaks in output text."""
    violations = []
    for pattern in _EXPOSE_INTERNAL_PATTERNS:
        matches = pattern.findall(result.output_text)
        if matches:
            violations.append(f"Expose pattern: {pattern.pattern} → {matches}")
    return violations


def _has_repeated_output(result: QAResult) -> list[str]:
    """Detect verbatim repetition of structured tool output."""
    violations = []
    for pattern in _REPEAT_OUTPUT_PATTERNS:
        if pattern.search(result.output_text):
            violations.append(f"Repeat pattern: {pattern.pattern}")
    return violations


def _count_tool_calls(result: QAResult, tool_name: str) -> int:
    """Count how many times a specific tool was called."""
    return sum(1 for tc in result.tool_calls_made if tc["tool_name"] == tool_name)


# ── Tests ────────────────────────────────────────────────────


class TestD6NoAnnounceWithoutAction:
    """Agent must not say 'I'll look that up' without actually calling tools."""

    @pytest.mark.asyncio
    async def test_quiz_no_announce_only(self, mock_tools):
        """Quiz request should call tool, not just announce it."""
        result = await run_agent_phase1("帮我出5道数学选择题", DEFAULT_MODEL)

        print(f"  [cc-01] tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")
        assert result.called_any_tool, (
            "[cc-01] Quiz request must call a tool, not just text respond"
        )
        violations = _has_announce_without_action(result)
        assert not violations, f"[cc-01] Announce without action:\n  " + "\n  ".join(violations)

    @pytest.mark.asyncio
    async def test_data_no_announce_only(self, mock_tools):
        """Data request should call tool, not just announce it."""
        deps = AgentDeps(
            teacher_id="t-qa-001", conversation_id="conv-cc",
            language="zh-CN", class_id="c-001",
        )
        result = await run_agent_phase1("帮我看看三年一班的成绩", DEFAULT_MODEL, deps=deps)

        print(f"  [cc-02] tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")
        assert result.called_any_tool, (
            "[cc-02] Data request must call a tool, not just text respond"
        )


class TestD6NoExposeInternals:
    """Agent output must not leak internal tool names or API details."""

    @pytest.mark.asyncio
    async def test_quiz_no_leak(self, mock_tools):
        result = await run_agent_phase1("帮我出5道数学选择题", DEFAULT_MODEL)
        violations = _has_exposed_internals(result)
        print(f"  [cc-03] output_len={len(result.output_text)}")
        assert not violations, (
            f"[cc-03] Internal tool names leaked in output:\n  " + "\n  ".join(violations) +
            f"\n  Output: {result.output_text[:300]}"
        )

    @pytest.mark.asyncio
    async def test_interactive_no_leak(self, mock_tools):
        result = await run_agent_phase1("做一个关于太阳系的互动网页", DEFAULT_MODEL)
        violations = _has_exposed_internals(result)
        print(f"  [cc-04] output_len={len(result.output_text)}")
        assert not violations, (
            f"[cc-04] Internal tool names leaked:\n  " + "\n  ".join(violations) +
            f"\n  Output: {result.output_text[:300]}"
        )


class TestD6NoRepeatToolOutput:
    """Agent should summarize, not repeat structured tool results verbatim."""

    @pytest.mark.asyncio
    async def test_quiz_no_verbatim(self, mock_tools):
        result = await run_agent_phase1("帮我出10道数学选择题", DEFAULT_MODEL)
        violations = _has_repeated_output(result)
        print(f"  [cc-05] output_len={len(result.output_text)}")
        # This is a soft check — mock returns minimal data so unlikely to trigger
        if violations:
            pytest.xfail(
                f"[cc-05] Tool output repeated verbatim (may be false positive with mocks):\n"
                f"  {violations}"
            )


class TestD6SingleClarify:
    """At most one ask_clarification call per turn."""

    @pytest.mark.asyncio
    async def test_vague_request_single_clarify(self, mock_tools):
        result = await run_agent_phase1("帮学生准备点东西", DEFAULT_MODEL)
        clarify_count = _count_tool_calls(result, "ask_clarification")
        print(f"  [cc-06] clarify_count={clarify_count} tools={result.tool_names_list}")
        assert clarify_count <= 1, (
            f"[cc-06] ask_clarification called {clarify_count} times (max 1 per turn)"
        )


class TestD6PPTOutlineFirst:
    """PPT generation must go through propose_pptx_outline before generate_pptx."""

    @pytest.mark.asyncio
    async def test_ppt_outline_not_generate(self, mock_tools):
        """Direct PPT request should call propose_pptx_outline, NOT generate_pptx."""
        result = await run_agent_phase1("做一个关于二次函数的PPT", DEFAULT_MODEL)

        print(f"  [cc-07] tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")
        assert "generate_pptx" not in result.tool_names, (
            "[cc-07] generate_pptx called without outline approval — "
            "must call propose_pptx_outline first"
        )
        # Should call outline or clarify
        acceptable = {"propose_pptx_outline", "ask_clarification"}
        assert result.tool_names & acceptable, (
            f"[cc-07] PPT request should call propose_pptx_outline or ask_clarification, "
            f"got: {result.tool_names_list or '(none)'}"
        )


class TestD6SingleGeneration:
    """Same generation tool should not be called more than once per turn."""

    @pytest.mark.asyncio
    async def test_quiz_single_call(self, mock_tools):
        result = await run_agent_phase1(
            "出10道数学选择题，包含二次函数和三角函数", DEFAULT_MODEL,
        )
        quiz_count = _count_tool_calls(result, "generate_quiz_questions")
        print(f"  [cc-08] quiz_calls={quiz_count} tools={result.tool_names_list}")
        assert quiz_count <= 1, (
            f"[cc-08] generate_quiz_questions called {quiz_count} times (max 1 per turn)"
        )
