"""Tests for agents/native_agent.py — keyword toolset selection logic.

Step 1.2 of AI native rewrite.  Tests the loose-inclusion keyword selector,
NOT the LLM planner (see test_toolset_planner.py).
"""

from __future__ import annotations

import pytest

from agents.native_agent import (
    AgentDeps,
    _might_analyze,
    _might_generate,
    _might_modify,
    _select_toolsets_keyword,
    TOOLSET_ANALYSIS,
    TOOLSET_ARTIFACT_OPS,
    TOOLSET_GENERATION,
)


# Import to make toolsets available
from tools.registry import ALWAYS_TOOLSETS, TOOLSET_BASE_DATA, TOOLSET_PLATFORM


def _make_deps(**kwargs) -> AgentDeps:
    defaults = {
        "teacher_id": "t-001",
        "conversation_id": "conv-test",
    }
    defaults.update(kwargs)
    return AgentDeps(**defaults)


class TestSelectToolsets:
    """Verify loose-inclusion keyword toolset selection."""

    def test_always_includes_base_and_platform(self):
        """Any message should at minimum include base_data + platform."""
        deps = _make_deps()
        result = _select_toolsets_keyword("你好", deps)
        assert TOOLSET_BASE_DATA in result
        assert TOOLSET_PLATFORM in result

    def test_generation_included_for_quiz_request(self):
        deps = _make_deps()
        result = _select_toolsets_keyword("帮我出 5 道选择题", deps)
        assert "generation" in result

    def test_generation_included_for_ppt_request(self):
        deps = _make_deps()
        result = _select_toolsets_keyword("帮我做一个 PPT", deps)
        assert "generation" in result

    def test_artifact_ops_included_when_has_artifacts(self):
        deps = _make_deps(has_artifacts=True)
        result = _select_toolsets_keyword("你好", deps)
        assert "artifact_ops" in result

    def test_artifact_ops_included_for_modify_request(self):
        deps = _make_deps()
        result = _select_toolsets_keyword("把第三题改一下", deps)
        assert "artifact_ops" in result

    def test_analysis_included_when_class_id_present(self):
        deps = _make_deps(class_id="c-001")
        result = _select_toolsets_keyword("你好", deps)
        assert "analysis" in result

    def test_analysis_included_for_grade_request(self):
        deps = _make_deps()
        result = _select_toolsets_keyword("三班的成绩怎么样", deps)
        assert "analysis" in result

    def test_simple_chat_minimal_toolsets(self):
        """Simple chat should NOT exclude base_data/platform (loose inclusion)."""
        deps = _make_deps()
        result = _select_toolsets_keyword("你好，你是谁", deps)
        assert TOOLSET_BASE_DATA in result
        assert TOOLSET_PLATFORM in result

    def test_no_exclusive_routing(self):
        """A generation request should still include base_data + platform."""
        deps = _make_deps()
        result = _select_toolsets_keyword("帮我生成一份测试题", deps)
        assert TOOLSET_BASE_DATA in result
        assert TOOLSET_PLATFORM in result
        assert "generation" in result


class TestKeywordMatchers:
    """Verify the loose keyword matching functions."""

    def test_might_generate_chinese(self):
        assert _might_generate("帮我出题")
        assert _might_generate("生成一份文稿")
        assert _might_generate("做一个PPT")

    def test_might_generate_english(self):
        assert _might_generate("create a quiz")
        assert _might_generate("generate questions")

    def test_might_generate_negative(self):
        assert not _might_generate("你好")
        assert not _might_generate("成绩怎么样")

    def test_might_modify_chinese(self):
        assert _might_modify("把第三题修改一下")
        assert _might_modify("调整难度")

    def test_might_modify_english(self):
        assert _might_modify("change question 3")
        assert _might_modify("edit the title")

    def test_might_analyze_chinese(self):
        assert _might_analyze("分析一下成绩")
        assert _might_analyze("统计数据")

    def test_might_analyze_english(self):
        assert _might_analyze("analyze performance")
        assert _might_analyze("compare grades")
