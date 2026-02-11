"""D2: Boundary Confusion — adversarial samples that probe decision boundaries.

Two categories:
  - Traps: messages that SOUND like tool requests but should NOT trigger tools
  - Implicit: messages that DON'T sound explicit but MUST trigger tools

Uses Phase 1 mock (instant tool returns, only tests LLM decision).

Usage:
    cd insight-ai-agent
    pytest tests/test_tool_calling_qa/test_d2_boundary.py -v -s
    pytest tests/test_tool_calling_qa/test_d2_boundary.py -v -s -k "trap"
    pytest tests/test_tool_calling_qa/test_d2_boundary.py -v -s -k "implicit"
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass, field

import tools.native_tools  # noqa: F401

from agents.native_agent import AgentDeps
from tests.test_tool_calling_qa.conftest import (
    DEFAULT_MODEL,
    MODELS_TO_TEST,
    run_agent_phase1,
    print_dimension_report,
    _has_api_key,
)

pytestmark = pytest.mark.skipif(not _has_api_key, reason="No LLM API key")


@dataclass
class BoundaryCase:
    id: str
    message: str
    should_call_tool: bool
    expected_tools: list[str] = field(default_factory=list)
    forbidden_tools: list[str] = field(default_factory=list)
    description: str = ""


# ── Should-NOT-Call traps ──

TRAP_CASES: list[BoundaryCase] = [
    BoundaryCase(
        id="trap-01", message="上次你帮我出的题还不错",
        should_call_tool=False,
        description="Praise/recall, not a new request",
    ),
    BoundaryCase(
        id="trap-02", message="生成式 AI 是什么意思？请帮我解释一下",
        should_call_tool=False,
        description="'生成' in knowledge Q&A, not a command",
    ),
    BoundaryCase(
        id="trap-03", message="我之前上传过一个关于光合作用的文档，你还记得吗",
        should_call_tool=False,
        description="Stating a past fact, not a search request",
    ),
    BoundaryCase(
        id="trap-04", message="你能帮我出题吗？我想先了解一下你的能力",
        should_call_tool=False,
        description="Capability inquiry, not execution",
    ),
    BoundaryCase(
        id="trap-05", message="我想了解一下成绩分析功能是怎么用的",
        should_call_tool=False,
        description="Asking about feature, not requesting analysis",
    ),
    BoundaryCase(
        id="trap-06", message="分析一下人工智能在教育领域的发展历程",
        should_call_tool=False,
        description="'分析' for general knowledge, not data analysis",
    ),
    BoundaryCase(
        id="trap-07", message="这个互动网页的技术原理是什么",
        should_call_tool=False,
        description="Asking about tech, not creating a page",
    ),
    BoundaryCase(
        id="trap-08", message="互动教学和传统教学的区别是什么",
        should_call_tool=False,
        description="'互动' in knowledge context, not interactive page",
    ),
    BoundaryCase(
        id="trap-09", message="题目设计有哪些原则和方法论",
        should_call_tool=False,
        description="'题目' in pedagogical discussion",
    ),
    BoundaryCase(
        id="trap-10", message="PPT制作的技巧有哪些",
        should_call_tool=False,
        description="'PPT' in knowledge Q&A, not creation",
    ),
]

# ── Must-Call implicit requests ──

IMPLICIT_CASES: list[BoundaryCase] = [
    BoundaryCase(
        id="impl-01", message="来点题给学生练练手",
        should_call_tool=True,
        expected_tools=["generate_quiz_questions", "ask_clarification"],
        description="Colloquial but clearly wants quiz",
    ),
    BoundaryCase(
        id="impl-02", message="弄个酷炫的页面讲一下细胞分裂的过程",
        should_call_tool=True,
        expected_tools=["generate_interactive_html"],
        description="'弄个页面' = create interactive page",
    ),
    BoundaryCase(
        id="impl-03", message="三年一班最近怎么样",
        should_call_tool=True,
        expected_tools=["get_teacher_classes", "get_class_detail", "ask_clarification"],
        description="Implicit data query",
    ),
    BoundaryCase(
        id="impl-04", message="把知识库里的重点整理一下出成题目",
        should_call_tool=True,
        expected_tools=["search_teacher_documents", "generate_quiz_questions"],
        description="RAG + quiz generation",
    ),
    BoundaryCase(
        id="impl-05", message="帮学生们准备点复习材料",
        should_call_tool=True,
        expected_tools=["generate_quiz_questions", "ask_clarification",
                        "propose_pptx_outline", "generate_interactive_html"],
        description="Vague but actionable",
    ),
    BoundaryCase(
        id="impl-06", message="给我出一套卷子",
        should_call_tool=True,
        expected_tools=["generate_quiz_questions", "ask_clarification"],
        description="'卷子' = exam paper",
    ),
    BoundaryCase(
        id="impl-07", message="搞个小测验看看学生水平",
        should_call_tool=True,
        expected_tools=["generate_quiz_questions", "ask_clarification"],
        description="'搞个小测验' = create quiz",
    ),
]

ALL_BOUNDARY_CASES = TRAP_CASES + IMPLICIT_CASES


# ── Tests ─────────────────────────────────────────────────────


class TestD2Traps:
    """Messages that should NOT trigger tool calls."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", TRAP_CASES, ids=[c.id for c in TRAP_CASES])
    async def test_trap_no_tools(self, mock_tools, case: BoundaryCase):
        result = await run_agent_phase1(case.message, DEFAULT_MODEL)

        if result.tool_calls_made:
            tool_names = result.tool_names_list
            # ask_clarification is a soft failure (model is cautious, not harmful)
            non_clarify = [t for t in tool_names if t != "ask_clarification"]
            if non_clarify:
                pytest.fail(
                    f"[{case.id}] {case.description}\n"
                    f"  Should NOT call tools, but called: {tool_names}\n"
                    f"  Message: {case.message!r}\n"
                    f"  Output: {result.output_text[:200]}"
                )


class TestD2Implicit:
    """Messages that MUST trigger tool calls despite being implicit."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", IMPLICIT_CASES, ids=[c.id for c in IMPLICIT_CASES])
    async def test_implicit_calls_tool(self, mock_tools, case: BoundaryCase):
        result = await run_agent_phase1(case.message, DEFAULT_MODEL)

        assert result.called_any_tool, (
            f"[{case.id}] {case.description}\n"
            f"  MUST call tools, but none called.\n"
            f"  Message: {case.message!r}\n"
            f"  Output: {result.output_text[:200]}"
        )

        if case.expected_tools:
            assert result.tool_names & set(case.expected_tools), (
                f"[{case.id}] {case.description}\n"
                f"  Expected one of {case.expected_tools}, got: {result.tool_names_list}"
            )


# ── Multi-model comparison ────────────────────────────────────


@pytest.mark.asyncio
async def test_d2_model_comparison(mock_tools):
    """Run all D2 cases across all available models — models run concurrently."""
    import asyncio

    if len(MODELS_TO_TEST) < 2:
        pytest.skip("Need >= 2 models for comparison")

    async def _run_one_model(model_info):
        model_id = model_info["id"]
        label = model_info["label"]
        items: list[tuple[str, bool, str, float]] = []

        for case in ALL_BOUNDARY_CASES:
            result = await run_agent_phase1(case.message, model_id)
            tools = result.tool_names_list

            if case.should_call_tool:
                passed = result.called_any_tool and (
                    not case.expected_tools
                    or bool(result.tool_names & set(case.expected_tools))
                )
                detail = f"tools={tools}" if passed else f"MISS tools={tools}"
            else:
                non_clarify = [t for t in tools if t != "ask_clarification"]
                passed = len(non_clarify) == 0
                detail = "clean" if passed else f"TRIGGERED {tools}"

            status = "PASS" if passed else "FAIL"
            print(f"    [{label}] {case.id}: [{status}] {detail} ({result.latency_ms:.0f}ms)")
            items.append((case.id, passed, detail, result.latency_ms))

        return label, items

    print(f"\n  === D2 Boundary: running {len(MODELS_TO_TEST)} models concurrently ===")
    tasks = [_run_one_model(m) for m in MODELS_TO_TEST]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: dict[str, list[tuple[str, bool, str, float]]] = {}
    for r in results_list:
        if isinstance(r, Exception):
            print(f"    ERROR: {r}")
            continue
        label, items = r
        all_results[label] = items

    print_dimension_report("D2: BOUNDARY CONFUSION", all_results)
