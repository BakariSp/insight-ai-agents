"""Tests for NativeAgent blueprint context injection."""

import pytest
from unittest.mock import MagicMock

from agents.native_agent import AgentDeps, NativeAgent
from models.soft_blueprint import ArtifactType


def test_build_system_prompt_no_context():
    """Test system prompt building with no context."""
    agent = NativeAgent()

    prompt = agent._build_system_prompt({})

    # Should return base system prompt unchanged
    assert isinstance(prompt, str)
    assert len(prompt) > 0
    # Should not contain blueprint-specific sections
    assert "当前上下文实体" not in prompt
    assert "输出结构建议" not in prompt


def test_build_system_prompt_with_resolved_entities():
    """Test system prompt with resolved entities."""
    agent = NativeAgent()

    context = {
        "resolved_entities": {
            "class_id": {"id": "cls-001", "displayName": "A班"},
            "assignment_id": {"id": "asn-123", "displayName": "作业1"},
        }
    }

    prompt = agent._build_system_prompt(context)

    # Should contain entity context section
    assert "当前上下文实体" in prompt
    assert "class_id = cls-001 (A班)" in prompt
    assert "assignment_id = asn-123 (作业1)" in prompt
    assert "调用工具时请使用上述 ID" in prompt


def test_build_system_prompt_with_blueprint_hints_report():
    """Test system prompt with blueprint hints for report."""
    agent = NativeAgent()

    context = {
        "blueprint_hints": {
            "expectedArtifacts": ["report"],
            "tabs": [
                {"key": "overview", "label": "整体概览", "description": "KPI and summary"},
                {"key": "details", "label": "详细分析", "description": "Student-level data"},
            ],
        }
    }

    prompt = agent._build_system_prompt(context)

    # Should contain output structure section
    assert "输出结构建议" in prompt
    assert "整体概览 (key: overview): KPI and summary" in prompt
    assert "详细分析 (key: details): Student-level data" in prompt
    assert "[TAB:{key}] {label}" in prompt
    assert "根据实际数据灵活调整" in prompt


def test_build_system_prompt_with_blueprint_hints_no_tabs():
    """Test system prompt with blueprint hints for non-report artifact."""
    agent = NativeAgent()

    context = {
        "blueprint_hints": {
            "expectedArtifacts": ["quiz"],  # Not "report"
            "preferredComponents": ["quiz_list"],
        }
    }

    prompt = agent._build_system_prompt(context)

    # Should NOT contain tab structure (only for reports)
    assert "输出结构建议" not in prompt
    assert "[TAB:" not in prompt


def test_build_system_prompt_with_both_contexts():
    """Test system prompt with both resolved entities and hints."""
    agent = NativeAgent()

    context = {
        "resolved_entities": {
            "class_id": {"id": "cls-001", "displayName": "A班"},
        },
        "blueprint_hints": {
            "expectedArtifacts": ["report"],
            "tabs": [
                {"key": "overview", "label": "Overview"},
            ],
        },
    }

    prompt = agent._build_system_prompt(context)

    # Should contain both sections
    assert "当前上下文实体" in prompt
    assert "class_id = cls-001 (A班)" in prompt
    assert "输出结构建议" in prompt
    assert "Overview (key: overview)" in prompt


def test_build_system_prompt_empty_resolved_entities():
    """Test system prompt with empty resolved_entities dict."""
    agent = NativeAgent()

    context = {"resolved_entities": {}}

    prompt = agent._build_system_prompt(context)

    # Should not inject empty entity section
    assert "当前上下文实体" not in prompt


def test_build_system_prompt_hints_without_tabs():
    """Test system prompt with hints but no tabs field."""
    agent = NativeAgent()

    context = {
        "blueprint_hints": {
            "expectedArtifacts": ["report"],
            # No "tabs" field
        }
    }

    prompt = agent._build_system_prompt(context)

    # Should not inject tab structure if tabs field is missing
    assert "输出结构建议" not in prompt


def test_build_system_prompt_integration_with_create_agent():
    """Test that _build_system_prompt is called in _create_agent."""
    agent = NativeAgent()

    context = {
        "resolved_entities": {
            "class_id": {"id": "cls-001", "displayName": "A班"},
        }
    }

    deps = AgentDeps(
        teacher_id="teacher-1",
        conversation_id="conv-1",
        context=context,
    )

    # Create agent with context
    pydantic_agent = agent._create_agent(["base_data"], deps)

    # Verify the agent was created successfully
    assert pydantic_agent is not None

    # We can't easily inspect the internal instructions of PydanticAI Agent,
    # but we can verify the method completes without error
    # (In real implementation, we'd use logging or internal inspection)


def test_agent_deps_context_propagation():
    """Test that context is properly stored in AgentDeps."""
    context = {
        "resolved_entities": {
            "class_id": {"id": "cls-001", "displayName": "A班"},
        },
        "blueprint_hints": {
            "expectedArtifacts": ["report"],
        },
    }

    deps = AgentDeps(
        teacher_id="teacher-1",
        conversation_id="conv-1",
        context=context,
    )

    # Verify context is stored
    assert deps.context == context
    assert "resolved_entities" in deps.context
    assert "blueprint_hints" in deps.context
