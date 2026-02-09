"""Shared pytest fixtures for AI native agent tests.

Provides:
- ``native_deps``: Basic AgentDeps for testing
- ``native_deps_with_artifacts``: AgentDeps with has_artifacts=True
- ``native_deps_with_class``: AgentDeps with class_id set
- ``artifact_store``: Fresh InMemoryArtifactStore per test
- ``metrics_collector``: Fresh MetricsCollector per test
"""

from __future__ import annotations

import pytest

# Ensure native tools are registered at test startup
import tools.native_tools  # noqa: F401

from agents.native_agent import AgentDeps
from services.artifact_store import InMemoryArtifactStore
from services.metrics import MetricsCollector


@pytest.fixture
def native_deps() -> AgentDeps:
    """Basic AgentDeps for testing — teacher with no class context."""
    return AgentDeps(
        teacher_id="t-test-001",
        conversation_id="conv-test-001",
        language="zh-CN",
    )


@pytest.fixture
def native_deps_with_artifacts() -> AgentDeps:
    """AgentDeps with existing artifacts in the conversation."""
    return AgentDeps(
        teacher_id="t-test-001",
        conversation_id="conv-test-002",
        language="zh-CN",
        has_artifacts=True,
    )


@pytest.fixture
def native_deps_with_class() -> AgentDeps:
    """AgentDeps with class_id set for analysis scenarios."""
    return AgentDeps(
        teacher_id="t-test-001",
        conversation_id="conv-test-003",
        language="zh-CN",
        class_id="c-test-001",
    )


@pytest.fixture
def artifact_store() -> InMemoryArtifactStore:
    """Fresh artifact store — isolated per test."""
    return InMemoryArtifactStore()


@pytest.fixture
def metrics_collector() -> MetricsCollector:
    """Fresh metrics collector — isolated per test."""
    return MetricsCollector()
