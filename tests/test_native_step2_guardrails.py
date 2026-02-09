from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import tools.native_tools  # noqa: F401
from services.metrics import get_metrics_collector
from tools import data_tools
from tools.document_tools import search_teacher_documents
from tools.native_tools import calculate_stats


def _fake_ctx() -> SimpleNamespace:
    deps = SimpleNamespace(conversation_id="conv-test", turn_id="turn-test", teacher_id="t-001")
    return SimpleNamespace(deps=deps)


def test_should_use_mock_debug_gate():
    with patch("tools.data_tools.get_settings", return_value=SimpleNamespace(debug=False, use_mock_data=True)):
        assert data_tools._should_use_mock() is False
    with patch("tools.data_tools.get_settings", return_value=SimpleNamespace(debug=True, use_mock_data=True)):
        assert data_tools._should_use_mock() is True


@pytest.mark.asyncio
async def test_data_tool_missing_teacher_returns_error():
    result = await data_tools.get_teacher_classes("")
    assert result["status"] == "error"
    assert "teacher_id" in result["reason"]


@pytest.mark.asyncio
async def test_rag_status_semantics_engine_unavailable():
    with patch("insight_backend.rag_engine.get_rag_engine", side_effect=RuntimeError("not ready")):
        result = await search_teacher_documents("t-001", "unit 5", include_public=False)
    assert result["status"] == "error"
    assert result["results"] == []


@pytest.mark.asyncio
async def test_metrics_collector_records_tool_calls():
    collector = get_metrics_collector()
    collector.reset()

    result = await calculate_stats(_fake_ctx(), data=[1, 2, 3], metrics=["mean"])
    assert result["status"] == "ok"

    snapshot = collector.snapshot()
    assert snapshot["tools"]["calculate_stats"]["count"] >= 1
    assert snapshot["tools"]["calculate_stats"]["success_rate"] > 0
