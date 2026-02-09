"""Tests for tools/registry.py — native tool registry + toolset classification.

Step 1.1.5 of AI native rewrite.
"""

from __future__ import annotations

import pytest

from tools.registry import (
    ALL_TOOLSETS,
    ALWAYS_TOOLSETS,
    TOOLSET_BASE_DATA,
    TOOLSET_ANALYSIS,
    TOOLSET_ARTIFACT_OPS,
    TOOLSET_GENERATION,
    TOOLSET_PLATFORM,
    _registry,
    get_all_tools,
    get_registered_count,
    get_tool_descriptions,
    get_tool_names,
    get_tools,
    get_toolset_counts,
    register_tool,
)


# Ensure native_tools is imported to populate the registry
import tools.native_tools  # noqa: F401


class TestRegistryPopulated:
    """Verify that tool registration via @register_tool works."""

    def test_registry_not_empty(self):
        assert get_registered_count() > 0

    def test_generate_quiz_registered(self):
        names = get_tool_names()
        assert "generate_quiz_questions" in names

    def test_search_documents_registered(self):
        names = get_tool_names()
        assert "search_teacher_documents" in names

    def test_base_data_tools_registered(self):
        names = get_tool_names(toolsets=[TOOLSET_BASE_DATA])
        assert "get_teacher_classes" in names
        assert "get_class_detail" in names

    def test_all_toolsets_have_tools(self):
        counts = get_toolset_counts()
        assert counts.get(TOOLSET_BASE_DATA, 0) == 5
        assert counts.get(TOOLSET_ANALYSIS, 0) == 5
        assert counts.get(TOOLSET_GENERATION, 0) == 7
        assert counts.get(TOOLSET_ARTIFACT_OPS, 0) == 3
        assert counts.get(TOOLSET_PLATFORM, 0) == 5

    def test_step2_total_tool_count(self):
        assert get_registered_count() == 25


class TestGetTools:
    """Verify toolset filtering returns correct PydanticAI FunctionToolset."""

    def test_get_tools_generation(self):
        ts = get_tools(["generation"])
        # FunctionToolset should contain generate_quiz_questions
        assert ts is not None

    def test_get_tools_multiple_toolsets(self):
        ts = get_tools(["generation", "platform"])
        assert ts is not None

    def test_get_all_tools(self):
        ts = get_all_tools()
        assert ts is not None


class TestToolDescriptions:
    """Verify tool description extraction."""

    def test_descriptions_not_empty(self):
        descs = get_tool_descriptions()
        assert len(descs) > 0

    def test_description_has_required_fields(self):
        descs = get_tool_descriptions()
        for d in descs:
            assert "name" in d
            assert "description" in d
            assert "toolset" in d


class TestRegisterToolValidation:
    """Verify registration validation."""

    def test_invalid_toolset_raises(self):
        with pytest.raises(ValueError, match="Unknown toolset"):
            @register_tool(toolset="nonexistent")
            async def bad_tool():
                pass
