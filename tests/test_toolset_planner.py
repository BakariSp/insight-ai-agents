"""Tests for LLM-based toolset planner + integration with select_toolsets.

Tests the schema validation, prompt formatting, and the planner/fallback
integration logic in native_agent.select_toolsets (async).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from agents.native_agent import (
    AgentDeps,
    _select_toolsets_keyword,
    select_toolsets,
)
from agents.toolset_planner import ToolsetPlannerResult
from tools.registry import ALWAYS_TOOLSETS, TOOLSET_BASE_DATA, TOOLSET_PLATFORM


def _make_deps(**kwargs) -> AgentDeps:
    defaults = {
        "teacher_id": "t-001",
        "conversation_id": "conv-test",
    }
    defaults.update(kwargs)
    return AgentDeps(**defaults)


# ── Schema Validation ──────────────────────────────────────


class TestToolsetPlannerResult:
    """Validate the Pydantic output schema."""

    def test_valid_single_toolset(self):
        r = ToolsetPlannerResult(toolsets=["generation"], confidence=0.9)
        assert r.toolsets == ["generation"]
        assert r.confidence == 0.9

    def test_valid_multiple_toolsets(self):
        r = ToolsetPlannerResult(
            toolsets=["analysis", "generation", "artifact_ops"],
            confidence=0.8,
        )
        assert len(r.toolsets) == 3

    def test_empty_toolsets_valid(self):
        r = ToolsetPlannerResult(toolsets=[], confidence=0.95)
        assert r.toolsets == []

    def test_invalid_toolset_rejected(self):
        with pytest.raises(ValidationError):
            ToolsetPlannerResult(toolsets=["nonexistent"], confidence=0.5)

    def test_confidence_too_high(self):
        with pytest.raises(ValidationError):
            ToolsetPlannerResult(toolsets=[], confidence=1.5)

    def test_confidence_too_low(self):
        with pytest.raises(ValidationError):
            ToolsetPlannerResult(toolsets=[], confidence=-0.1)

    def test_confidence_boundaries(self):
        ToolsetPlannerResult(toolsets=[], confidence=0.0)
        ToolsetPlannerResult(toolsets=[], confidence=1.0)


# ── Async select_toolsets Integration ──────────────────────


class TestSelectToolsetsPlanner:
    """Test async select_toolsets with planner enabled/disabled."""

    @pytest.mark.asyncio
    async def test_flag_off_uses_keywords(self):
        """When planner disabled, keyword path is used."""
        deps = _make_deps()
        with patch("agents.native_agent.get_settings") as mock_settings:
            mock_settings.return_value.toolset_planner_enabled = False
            result = await select_toolsets("帮我出 5 道选择题", deps)
        assert "generation" in result
        assert TOOLSET_BASE_DATA in result
        assert TOOLSET_PLATFORM in result

    @pytest.mark.asyncio
    async def test_planner_high_confidence(self):
        """High confidence planner result is used directly."""
        deps = _make_deps()
        mock_result = ToolsetPlannerResult(
            toolsets=["generation"],
            confidence=0.95,
        )
        with (
            patch("agents.native_agent.get_settings") as mock_settings,
            patch(
                "agents.toolset_planner.plan_toolsets",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            mock_settings.return_value.toolset_planner_enabled = True
            mock_settings.return_value.toolset_planner_confidence_threshold = 0.6
            mock_settings.return_value.toolset_planner_timeout_s = 0.5
            result = await select_toolsets("帮我出 5 道选择题", deps)

        assert "generation" in result
        assert TOOLSET_BASE_DATA in result
        assert TOOLSET_PLATFORM in result
        # Planner only returned generation; artifact_ops/analysis should NOT be present
        assert "artifact_ops" not in result

    @pytest.mark.asyncio
    async def test_planner_low_confidence_falls_back(self):
        """Low confidence triggers keyword fallback."""
        deps = _make_deps()
        mock_result = ToolsetPlannerResult(
            toolsets=[],
            confidence=0.3,
        )
        with (
            patch("agents.native_agent.get_settings") as mock_settings,
            patch(
                "agents.toolset_planner.plan_toolsets",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            mock_settings.return_value.toolset_planner_enabled = True
            mock_settings.return_value.toolset_planner_confidence_threshold = 0.6
            mock_settings.return_value.toolset_planner_timeout_s = 0.5
            result = await select_toolsets("帮我出 5 道选择题", deps)

        # Keyword fallback should pick up "generation" from keywords
        assert "generation" in result

    @pytest.mark.asyncio
    async def test_planner_timeout_falls_back(self):
        """Planner timeout triggers keyword fallback."""
        deps = _make_deps()

        async def slow_planner(**kwargs):
            await asyncio.sleep(10)

        with (
            patch("agents.native_agent.get_settings") as mock_settings,
            patch(
                "agents.toolset_planner.plan_toolsets",
                side_effect=slow_planner,
            ),
        ):
            mock_settings.return_value.toolset_planner_enabled = True
            mock_settings.return_value.toolset_planner_confidence_threshold = 0.6
            mock_settings.return_value.toolset_planner_timeout_s = 0.01  # 10ms
            result = await select_toolsets("帮我出 5 道选择题", deps)

        assert "generation" in result

    @pytest.mark.asyncio
    async def test_planner_exception_falls_back(self):
        """Planner exception triggers keyword fallback."""
        deps = _make_deps()
        with (
            patch("agents.native_agent.get_settings") as mock_settings,
            patch(
                "agents.toolset_planner.plan_toolsets",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM down"),
            ),
        ):
            mock_settings.return_value.toolset_planner_enabled = True
            mock_settings.return_value.toolset_planner_confidence_threshold = 0.6
            mock_settings.return_value.toolset_planner_timeout_s = 0.5
            result = await select_toolsets("帮我出 5 道选择题", deps)

        assert "generation" in result

    @pytest.mark.asyncio
    async def test_always_toolsets_always_present(self):
        """ALWAYS_TOOLSETS present regardless of planner output."""
        deps = _make_deps()
        mock_result = ToolsetPlannerResult(
            toolsets=["generation"],
            confidence=0.95,
        )
        with (
            patch("agents.native_agent.get_settings") as mock_settings,
            patch(
                "agents.toolset_planner.plan_toolsets",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            mock_settings.return_value.toolset_planner_enabled = True
            mock_settings.return_value.toolset_planner_confidence_threshold = 0.6
            mock_settings.return_value.toolset_planner_timeout_s = 0.5
            result = await select_toolsets("test", deps)

        assert TOOLSET_BASE_DATA in result
        assert TOOLSET_PLATFORM in result


# ── Keyword Fallback (unchanged logic) ─────────────────────


class TestKeywordFallbackDirect:
    """Verify _select_toolsets_keyword still works correctly."""

    def test_generation_for_quiz(self):
        deps = _make_deps()
        result = _select_toolsets_keyword("帮我出 5 道选择题", deps)
        assert "generation" in result

    def test_artifact_ops_for_modify(self):
        deps = _make_deps()
        result = _select_toolsets_keyword("把第三题改一下", deps)
        assert "artifact_ops" in result

    def test_analysis_for_grades(self):
        deps = _make_deps()
        result = _select_toolsets_keyword("三班的成绩怎么样", deps)
        assert "analysis" in result

    def test_minimal_for_greeting(self):
        deps = _make_deps()
        result = _select_toolsets_keyword("你好", deps)
        assert TOOLSET_BASE_DATA in result
        assert TOOLSET_PLATFORM in result
        assert "generation" not in result
        assert "analysis" not in result
