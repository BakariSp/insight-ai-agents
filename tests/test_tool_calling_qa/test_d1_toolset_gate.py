"""D1: Toolset Gate — pure function tests for select_toolsets / keyword matching.

No LLM calls. Tests that the keyword heuristic layer correctly includes/excludes
toolsets based on message content, deps, and conversation history.

Usage:
    cd insight-ai-agent
    pytest tests/test_tool_calling_qa/test_d1_toolset_gate.py -v
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass

from agents.native_agent import (
    AgentDeps,
    _select_toolsets_keyword,
    _might_generate,
    _might_modify,
    _might_analyze,
)
from tools.registry import (
    ALWAYS_TOOLSETS,
    TOOLSET_ANALYSIS,
    TOOLSET_ARTIFACT_OPS,
    TOOLSET_GENERATION,
)


@dataclass
class GateCase:
    id: str
    message: str
    deps_kwargs: dict
    recent_context: str = ""
    expect_in: list[str] | None = None
    expect_not_in: list[str] | None = None
    description: str = ""


GATE_CASES: list[GateCase] = [
    # ═══ Should NOT include generation ═══
    GateCase(
        id="gate-01", message="帮我看看学生情况",
        deps_kwargs={},
        expect_not_in=[TOOLSET_GENERATION],
        description="'看看' is not a generation keyword",
    ),
    GateCase(
        id="gate-04", message="二次函数",
        deps_kwargs={},
        expect_not_in=[TOOLSET_GENERATION, TOOLSET_ANALYSIS, TOOLSET_ARTIFACT_OPS],
        description="Pure noun — only ALWAYS toolsets",
    ),
    GateCase(
        id="gate-05", message="你好",
        deps_kwargs={},
        expect_not_in=[TOOLSET_GENERATION, TOOLSET_ANALYSIS, TOOLSET_ARTIFACT_OPS],
        description="Greeting — only ALWAYS toolsets",
    ),
    GateCase(
        id="gate-12", message="这个班怎么样",
        deps_kwargs={},
        expect_not_in=[TOOLSET_ANALYSIS],
        description="No analysis keyword + no class_id",
    ),

    # ═══ Should include generation ═══
    GateCase(
        id="gate-02", message="做一个总结",
        deps_kwargs={},
        expect_in=[TOOLSET_GENERATION],
        description="'做一个' hits _GENERATE_KEYWORDS",
    ),
    # gate-14 moved to TestToolsetGateGaps (standalone '题' is a keyword gap)
    GateCase(
        id="gate-16", message="帮我出5道英语选择题",
        deps_kwargs={},
        expect_in=[TOOLSET_GENERATION],
        description="Standard quiz request",
    ),
    GateCase(
        id="gate-17", message="生成一个互动网页关于太阳系",
        deps_kwargs={},
        expect_in=[TOOLSET_GENERATION],
        description="Standard interactive request",
    ),
    GateCase(
        id="gate-18", message="帮我做一个PPT",
        deps_kwargs={},
        expect_in=[TOOLSET_GENERATION],
        description="Standard PPT request",
    ),
    GateCase(
        id="gate-19", message="写一份教学设计",
        deps_kwargs={},
        expect_in=[TOOLSET_GENERATION],
        description="'写' hits _GENERATE_KEYWORDS",
    ),

    # ═══ Artifact ops ═══
    GateCase(
        id="gate-03", message="把第三题换成更难的",
        deps_kwargs={"has_artifacts": False},
        expect_in=[TOOLSET_ARTIFACT_OPS],
        description="'换' hits _MODIFY_KEYWORDS even without has_artifacts",
    ),
    GateCase(
        id="gate-20", message="修改第二页的标题",
        deps_kwargs={"has_artifacts": True},
        expect_in=[TOOLSET_ARTIFACT_OPS],
        description="has_artifacts=True + modify keyword",
    ),
    GateCase(
        id="gate-21", message="帮我看看这个内容",
        deps_kwargs={"has_artifacts": True},
        expect_in=[TOOLSET_ARTIFACT_OPS],
        description="has_artifacts=True alone triggers artifact_ops",
    ),

    # ═══ Analysis ═══
    GateCase(
        id="gate-10", message="帮我分析",
        deps_kwargs={},
        expect_in=[TOOLSET_ANALYSIS],
        description="'分析' keyword triggers analysis",
    ),
    GateCase(
        id="gate-11", message="帮我看看数据",
        deps_kwargs={"class_id": "c-001"},
        expect_in=[TOOLSET_ANALYSIS],
        description="class_id alone triggers analysis",
    ),
    GateCase(
        id="gate-22", message="成绩怎么样",
        deps_kwargs={},
        expect_in=[TOOLSET_ANALYSIS],
        description="'成绩' keyword triggers analysis",
    ),

    # ═══ Context inheritance ═══
    GateCase(
        id="gate-07", message="引力系统",
        deps_kwargs={},
        recent_context="生成一个粒子互动网页",
        expect_in=[TOOLSET_GENERATION],
        description="Clarify follow-up inherits generation from context",
    ),
    GateCase(
        id="gate-08", message="数学二次函数",
        deps_kwargs={},
        recent_context="帮我出题",
        expect_in=[TOOLSET_GENERATION],
        description="Clarify follow-up inherits quiz intent",
    ),
    GateCase(
        id="gate-09", message="你好",
        deps_kwargs={},
        recent_context="生成5道选择题",
        expect_in=[TOOLSET_GENERATION],
        description="Context contamination: greeting after gen — known FP",
    ),
    GateCase(
        id="gate-23", message="三年一班",
        deps_kwargs={},
        recent_context="帮我分析成绩",
        expect_in=[TOOLSET_ANALYSIS],
        description="Clarify follow-up inherits analysis intent",
    ),
]


def _make_deps(**kwargs) -> AgentDeps:
    defaults = {"teacher_id": "t-test", "conversation_id": "c-test"}
    defaults.update(kwargs)
    return AgentDeps(**defaults)


# ── Keyword matcher unit tests ────────────────────────────────


class TestKeywordFunctions:

    @pytest.mark.parametrize("msg,expected", [
        ("帮我出5道题", True),
        ("生成一个互动网页", True),
        ("做一个PPT", True),
        ("写一份教案", True),
        ("再出5道", True),
        ("你好", False),
        ("帮我看看学生情况", False),
        ("这个班怎么样", False),
    ])
    def test_might_generate(self, msg, expected):
        assert _might_generate(msg) == expected

    @pytest.mark.parametrize("msg,expected", [
        ("把第三题换成更难的", True),
        ("修改标题", True),
        ("删掉最后一页", True),
        ("添加一个图片", True),
        ("你好", False),
        ("帮我出5道题", False),
    ])
    def test_might_modify(self, msg, expected):
        assert _might_modify(msg) == expected

    @pytest.mark.parametrize("msg,expected", [
        ("分析成绩", True),
        ("统计一下平均分", True),
        ("对比两个班", True),
        ("你好", False),
        ("帮我出5道题", False),
    ])
    def test_might_analyze(self, msg, expected):
        assert _might_analyze(msg) == expected


# ── Toolset selection tests ───────────────────────────────────


class TestToolsetGate:

    @pytest.mark.parametrize("case", GATE_CASES, ids=[c.id for c in GATE_CASES])
    def test_toolset_gate(self, case: GateCase):
        deps = _make_deps(**case.deps_kwargs)
        result = _select_toolsets_keyword(case.message, deps, case.recent_context)

        if case.expect_in:
            for ts in case.expect_in:
                assert ts in result, (
                    f"[{case.id}] {case.description}\n"
                    f"  Expected '{ts}' IN result, got: {result}\n"
                    f"  Message: {case.message!r}"
                )

        if case.expect_not_in:
            for ts in case.expect_not_in:
                assert ts not in result, (
                    f"[{case.id}] {case.description}\n"
                    f"  Expected '{ts}' NOT IN result, got: {result}\n"
                    f"  Message: {case.message!r}"
                )

        for ts in ALWAYS_TOOLSETS:
            assert ts in result, f"[{case.id}] ALWAYS toolset '{ts}' missing"


# ── Known keyword gaps (xfail) ────────────────────────────────


class TestToolsetGateGaps:

    @pytest.mark.xfail(reason="'来点题' — standalone '题' not in _GENERATE_KEYWORDS", strict=False)
    def test_gap_来点题(self):
        deps = _make_deps()
        result = _select_toolsets_keyword("来点题给学生练练手", deps)
        assert TOOLSET_GENERATION in result

    @pytest.mark.xfail(reason="'弄' not in _GENERATE_KEYWORDS", strict=False)
    def test_gap_弄(self):
        deps = _make_deps()
        result = _select_toolsets_keyword("弄个酷炫的页面讲一下细胞分裂", deps)
        assert TOOLSET_GENERATION in result

    @pytest.mark.xfail(reason="'课件' not in _GENERATE_KEYWORDS", strict=False)
    def test_gap_课件(self):
        deps = _make_deps()
        result = _select_toolsets_keyword("课件需要一个关于勾股定理的", deps)
        assert TOOLSET_GENERATION in result

    @pytest.mark.xfail(reason="'整理' not in _GENERATE_KEYWORDS", strict=False)
    def test_gap_整理(self):
        deps = _make_deps()
        result = _select_toolsets_keyword("帮我整理一下知识库的重点", deps)
        assert TOOLSET_GENERATION in result

    @pytest.mark.xfail(reason="'准备' not in _GENERATE_KEYWORDS", strict=False)
    def test_gap_准备(self):
        deps = _make_deps()
        result = _select_toolsets_keyword("帮学生准备一些复习材料", deps)
        assert TOOLSET_GENERATION in result

    def test_false_positive_生成式AI(self):
        """'生成式AI' triggers generation — document this known FP."""
        deps = _make_deps()
        result = _select_toolsets_keyword("生成式 AI 是什么意思", deps)
        # This is a known false positive — acceptable cost
        assert TOOLSET_GENERATION in result, (
            "Expected FP: '生成' in '生成式AI' no longer triggers — keyword changed?"
        )
