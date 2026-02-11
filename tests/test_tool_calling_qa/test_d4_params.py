"""D4: Parameter Fidelity — verify tool arguments are correctly extracted
from user messages.

Not just "did you call the right tool?" but "did you pass the right params?"

Uses Phase 1 mock (instant tool returns, only tests LLM decision).

Usage:
    cd insight-ai-agent
    pytest tests/test_tool_calling_qa/test_d4_params.py -v -s
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


# ── Param check helpers ──────────────────────────────────────


def _param_contains(result: QAResult, tool_name: str, param: str, expected: str) -> bool:
    """Check if a tool param value contains expected substring (case-insensitive)."""
    args = result.get_tool_args(tool_name)
    if args is None:
        return False
    value = str(args.get(param, ""))
    return expected.lower() in value.lower()


def _param_equals(result: QAResult, tool_name: str, param: str, expected) -> bool:
    """Check if a tool param equals the expected value."""
    args = result.get_tool_args(tool_name)
    if args is None:
        return False
    return args.get(param) == expected


def _param_in_range(result: QAResult, tool_name: str, param: str, low: int, high: int) -> bool:
    """Check if a numeric tool param is within range."""
    args = result.get_tool_args(tool_name)
    if args is None:
        return False
    val = args.get(param)
    if val is None:
        return False
    try:
        return low <= int(val) <= high
    except (ValueError, TypeError):
        return False


# ── Test data ────────────────────────────────────────────────


@dataclass
class ParamCase:
    id: str
    message: str
    expected_tool: str
    checks: list[dict]  # [{param, check_type, expected}]
    description: str = ""


PARAM_CASES: list[ParamCase] = [
    ParamCase(
        id="pf-01",
        message="出10道中等难度三角函数填空题",
        expected_tool="generate_quiz_questions",
        checks=[
            {"param": "count", "check": "equals", "expected": 10},
            {"param": "difficulty", "check": "contains", "expected": "中等"},
            {"param": "topic", "check": "contains", "expected": "三角函数"},
        ],
        description="Multi-param extraction: count + difficulty + topic",
    ),
    ParamCase(
        id="pf-03",
        message="生成一个关于牛顿第二定律的互动实验页面",
        expected_tool="generate_interactive_html",
        checks=[
            {"param": "topic", "check": "contains_any", "expected": ["牛顿", "F=ma", "力"]},
        ],
        description="Interactive page topic extraction",
    ),
    ParamCase(
        id="pf-05",
        message="出5道英语语法选择题，关于过去完成时",
        expected_tool="generate_quiz_questions",
        checks=[
            {"param": "count", "check": "equals", "expected": 5},
            {"param": "subject", "check": "contains_any", "expected": ["英语", "english"]},
            {"param": "topic", "check": "contains_any", "expected": ["过去完成", "past perfect"]},
        ],
        description="English quiz: count + subject + topic",
    ),
    ParamCase(
        id="pf-07",
        message="给我一份简单的数学测验，只要判断题",
        expected_tool="generate_quiz_questions",
        checks=[
            {"param": "difficulty", "check": "contains_any", "expected": ["简单", "easy", "基础"]},
            {"param": "types", "check": "contains_any", "expected": ["判断", "true", "对错"]},
        ],
        description="Difficulty + type extraction",
    ),
    ParamCase(
        id="pf-04",
        message="做一个PPT，关于期末复习",
        expected_tool="propose_pptx_outline",
        checks=[
            {"param": "title", "check": "contains_any", "expected": ["期末", "复习"]},
        ],
        description="PPT title extraction",
    ),
]


# ── Tests ────────────────────────────────────────────────────


class TestD4ParameterFidelity:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", PARAM_CASES, ids=[c.id for c in PARAM_CASES])
    async def test_param_extraction(self, mock_tools, case: ParamCase):
        result = await run_agent_phase1(case.message, DEFAULT_MODEL)

        print(f"  [{case.id}] tools={result.tool_names_list} ({result.latency_ms:.0f}ms)")

        # First: must call the expected tool
        assert case.expected_tool in result.tool_names, (
            f"[{case.id}] {case.description}\n"
            f"  Expected tool: {case.expected_tool}, got: {result.tool_names_list or '(none)'}"
        )

        # Then: check params
        args = result.get_tool_args(case.expected_tool)
        print(f"    args={args}")
        failures = []

        for check in case.checks:
            param = check["param"]
            check_type = check["check"]
            expected = check["expected"]
            actual = args.get(param, "(missing)") if args else "(no args)"

            if check_type == "equals":
                passed = _param_equals(result, case.expected_tool, param, expected)
            elif check_type == "contains":
                passed = _param_contains(result, case.expected_tool, param, expected)
            elif check_type == "contains_any":
                # Any of the expected values matches
                passed = any(
                    _param_contains(result, case.expected_tool, param, e)
                    for e in expected
                )
            elif check_type == "range":
                passed = _param_in_range(result, case.expected_tool, param, *expected)
            else:
                passed = False

            if not passed:
                failures.append(
                    f"  param '{param}': expected {check_type}={expected}, got '{actual}'"
                )

        if failures:
            pytest.fail(
                f"[{case.id}] {case.description}\n"
                f"  Parameter check failures:\n" + "\n".join(failures)
            )
