"""D5: Chain Integrity — verify multi-step tool chains are complete and ordered.

Tests that the agent follows required data retrieval chains
(e.g., get_teacher_classes → get_class_detail → get_assignment_submissions)
and doesn't skip prerequisite steps.

Uses Phase 1 mock (instant tool returns, only tests LLM decision).

Usage:
    cd insight-ai-agent
    pytest tests/test_tool_calling_qa/test_d5_chain.py -v -s
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass, field

import tools.native_tools  # noqa: F401

from agents.native_agent import AgentDeps
from tests.test_tool_calling_qa.conftest import (
    DEFAULT_MODEL,
    run_agent_phase1,
    QAResult,
    _has_api_key,
)

pytestmark = pytest.mark.skipif(not _has_api_key, reason="No LLM API key")


# ── Chain check helpers ──────────────────────────────────────


def _check_chain_order(result: QAResult, required_chain: list[str]) -> tuple[bool, str]:
    """Check that required tools appear in order (other tools may appear between them)."""
    called = result.tool_names_list
    chain_idx = 0
    for name in called:
        if chain_idx < len(required_chain) and name == required_chain[chain_idx]:
            chain_idx += 1
    if chain_idx == len(required_chain):
        return True, ""
    missing = required_chain[chain_idx:]
    return False, f"Chain incomplete: called {called}, missing {missing} from {required_chain}"


def _check_prerequisite(result: QAResult, prerequisite: str, target: str) -> tuple[bool, str]:
    """Check that prerequisite was called before target (if target was called)."""
    called = result.tool_names_list
    if target not in called:
        return True, ""  # target not called → no violation
    target_idx = called.index(target)
    if prerequisite in called[:target_idx]:
        return True, ""
    return False, f"'{target}' called at position {target_idx} without prerequisite '{prerequisite}'"


# ── Test data ────────────────────────────────────────────────


@dataclass
class ChainCase:
    id: str
    message: str
    required_chain: list[str]  # ordered tools that must appear in sequence
    prerequisites: list[tuple[str, str]]  # (prerequisite, target) pairs
    forbidden_without: dict[str, str] = field(default_factory=dict)  # tool → must have prerequisite
    description: str = ""
    deps_overrides: dict = field(default_factory=dict)


CHAIN_CASES: list[ChainCase] = [
    ChainCase(
        id="ci-01",
        message="三年一班有哪些学生",
        required_chain=["get_teacher_classes", "get_class_detail"],
        prerequisites=[("get_teacher_classes", "get_class_detail")],
        description="Student list requires classes → detail chain",
    ),
    ChainCase(
        id="ci-04",
        message="根据知识库出题",
        required_chain=["search_teacher_documents", "generate_quiz_questions"],
        prerequisites=[("search_teacher_documents", "generate_quiz_questions")],
        description="RAG quiz requires search → generate chain",
    ),
    ChainCase(
        id="ci-08",
        message="做一个PPT，主题是二次函数复习课",
        required_chain=["propose_pptx_outline"],
        prerequisites=[],
        forbidden_without={"generate_pptx": "propose_pptx_outline"},
        description="PPT must propose outline first, never skip to generate_pptx",
    ),
]

# Cases needing class_id for analysis toolset
CHAIN_CASES_WITH_CLASS = [
    ChainCase(
        id="ci-03",
        message="对比两个班的平均分",
        required_chain=["get_teacher_classes"],
        prerequisites=[("get_teacher_classes", "calculate_stats"),
                       ("get_teacher_classes", "compare_performance")],
        description="Comparison needs class data first",
        deps_overrides={"class_id": "c-001"},
    ),
    ChainCase(
        id="ci-05",
        message="三年一班上次考试的提交情况",
        required_chain=["get_teacher_classes"],
        prerequisites=[],
        description="Submission data requires class data chain",
        deps_overrides={"class_id": "c-001"},
    ),
]


# ── Tests ────────────────────────────────────────────────────


class TestD5ChainIntegrity:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", CHAIN_CASES, ids=[c.id for c in CHAIN_CASES])
    async def test_chain_order(self, mock_tools, case: ChainCase):
        deps = AgentDeps(
            teacher_id="t-qa-001",
            conversation_id="conv-qa-chain",
            language="zh-CN",
            **case.deps_overrides,
        )
        result = await run_agent_phase1(case.message, DEFAULT_MODEL, deps=deps)

        print(f"  [{case.id}] tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")

        # Check that the required chain is followed
        chain_ok, chain_msg = _check_chain_order(result, case.required_chain)
        assert chain_ok, f"[{case.id}] {case.description}\n  {chain_msg}"

        # Check prerequisites
        for prereq, target in case.prerequisites:
            prereq_ok, prereq_msg = _check_prerequisite(result, prereq, target)
            assert prereq_ok, f"[{case.id}] {case.description}\n  {prereq_msg}"

        # Check forbidden-without (e.g., generate_pptx without propose_pptx_outline)
        for target, required_prereq in case.forbidden_without.items():
            if target in result.tool_names:
                assert required_prereq in result.tool_names, (
                    f"[{case.id}] {case.description}\n"
                    f"  '{target}' called without required '{required_prereq}'"
                )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", CHAIN_CASES_WITH_CLASS,
                             ids=[c.id for c in CHAIN_CASES_WITH_CLASS])
    async def test_chain_with_class(self, mock_tools, case: ChainCase):
        deps = AgentDeps(
            teacher_id="t-qa-001",
            conversation_id="conv-qa-chain",
            language="zh-CN",
            **case.deps_overrides,
        )
        result = await run_agent_phase1(case.message, DEFAULT_MODEL, deps=deps)

        print(f"  [{case.id}] tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")

        # Must call at least one data tool (not just text)
        data_tools = {"get_teacher_classes", "get_class_detail",
                      "get_assignment_submissions", "get_student_grades",
                      "calculate_stats", "compare_performance"}
        assert result.tool_names & data_tools, (
            f"[{case.id}] {case.description}\n"
            f"  Must call data tools, got: {result.tool_names_list or '(none)'}"
        )

        # Check chain
        chain_ok, chain_msg = _check_chain_order(result, case.required_chain)
        assert chain_ok, f"[{case.id}] {case.description}\n  {chain_msg}"

        # Check prerequisites
        for prereq, target in case.prerequisites:
            prereq_ok, prereq_msg = _check_prerequisite(result, prereq, target)
            assert prereq_ok, f"[{case.id}] {case.description}\n  {prereq_msg}"


class TestD5NoDataFabrication:
    """Agent must NOT produce specific data numbers without calling data tools."""

    @pytest.mark.asyncio
    async def test_no_fabricated_grades(self, mock_tools):
        """Ask about student grades — must call data tool, not fabricate."""
        result = await run_agent_phase1("帮我看看张三的成绩", DEFAULT_MODEL)

        print(f"  [ci-02] tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")

        data_tools = {"get_student_grades", "resolve_entity", "get_teacher_classes"}
        assert result.tool_names & data_tools, (
            "[ci-02] Student grade query must call data tools, "
            f"got: {result.tool_names_list or '(none)'}"
        )
