from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import tools.native_tools  # noqa: F401
from services.metrics import MetricsCollector, get_metrics_collector
from tools import data_tools
from tools.document_tools import search_teacher_documents
from tools.native_tools import (
    _apply_json_patch,
    _is_error,
    calculate_stats,
    get_teacher_classes,
)


def _fake_ctx(teacher_id: str = "t-001") -> SimpleNamespace:
    deps = SimpleNamespace(conversation_id="conv-test", turn_id="turn-test", teacher_id=teacher_id)
    return SimpleNamespace(deps=deps)


# ---------------------------------------------------------------------------
# Existing tests (unchanged logic)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# CRITICAL: native_tools error passthrough from data_tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_native_get_teacher_classes_forwards_backend_error():
    """When data_tools returns status='error', native_tools must propagate it —
    not silently return ok with empty classes."""
    error_result = {"status": "error", "reason": "connection refused", "teacher_id": "t-001", "classes": []}
    with patch("tools.data_tools.get_teacher_classes", new_callable=AsyncMock, return_value=error_result):
        result = await get_teacher_classes(_fake_ctx())
    assert result["status"] == "error"
    assert "connection refused" in result["reason"]


@pytest.mark.asyncio
async def test_native_get_teacher_classes_legacy_error_key():
    """Backward compat: legacy tools returning {"error": "..."} are also caught."""
    error_result = {"error": "timeout", "teacher_id": "t-001", "classes": []}
    with patch("tools.data_tools.get_teacher_classes", new_callable=AsyncMock, return_value=error_result):
        result = await get_teacher_classes(_fake_ctx())
    assert result["status"] == "error"
    assert "timeout" in result["reason"]


# ---------------------------------------------------------------------------
# _is_error helper
# ---------------------------------------------------------------------------


def test_is_error_detects_status_error():
    assert _is_error({"status": "error", "reason": "bad"}) is True


def test_is_error_detects_legacy_error_key():
    assert _is_error({"error": "bad"}) is True


def test_is_error_ignores_ok():
    assert _is_error({"status": "ok", "data": 1}) is False


def test_is_error_ignores_no_result():
    assert _is_error({"status": "no_result"}) is False


# ---------------------------------------------------------------------------
# _apply_json_patch defensive handling
# ---------------------------------------------------------------------------


def test_apply_json_patch_invalid_index():
    """Non-numeric index on a list should raise ValueError, not crash."""
    content = {"questions": [{"text": "q1"}]}
    ops = [{"op": "replace", "path": "/questions/abc", "value": "x"}]
    with pytest.raises(ValueError, match="patch operation 0 failed"):
        _apply_json_patch(content, ops)


def test_apply_json_patch_missing_key():
    """Accessing a missing key should raise ValueError."""
    content = {"a": 1}
    ops = [{"op": "replace", "path": "/nonexistent/deep", "value": 2}]
    with pytest.raises(ValueError, match="patch operation 0 failed"):
        _apply_json_patch(content, ops)


def test_apply_json_patch_happy_path():
    content = {"questions": [{"text": "q1"}, {"text": "q2"}]}
    ops = [{"op": "replace", "path": "/questions/0/text", "value": "updated"}]
    result = _apply_json_patch(content, ops)
    assert result["questions"][0]["text"] == "updated"
    # Original unchanged (deep copy).
    assert content["questions"][0]["text"] == "q1"


# ---------------------------------------------------------------------------
# Metrics: non-error statuses should not inflate tool_error_count
# ---------------------------------------------------------------------------


def test_metrics_no_result_not_counted_as_error():
    """'no_result' is a legitimate status, not an error."""
    collector = MetricsCollector()
    collector.record_tool_call(tool_name="search", status="no_result", latency_ms=10, turn_id="t1")
    collector.record_tool_call(tool_name="search", status="ok", latency_ms=5, turn_id="t1")

    turn = collector.get_turn_summary("t1")
    assert turn["tool_call_count"] == 2
    assert turn["tool_error_count"] == 0  # no_result is NOT an error


def test_metrics_planned_not_counted_as_error():
    """'planned' status (from render_tools) should not be counted as error."""
    collector = MetricsCollector()
    collector.record_tool_call(tool_name="request_interactive", status="planned", latency_ms=10, turn_id="t2")

    turn = collector.get_turn_summary("t2")
    assert turn["tool_error_count"] == 0


def test_metrics_real_error_counted():
    """Only status='error' should increment tool_error_count."""
    collector = MetricsCollector()
    collector.record_tool_call(tool_name="get_classes", status="error", latency_ms=10, turn_id="t3")

    turn = collector.get_turn_summary("t3")
    assert turn["tool_error_count"] == 1


# ---------------------------------------------------------------------------
# Metrics: capacity limits
# ---------------------------------------------------------------------------


def test_metrics_latency_cap():
    collector = MetricsCollector()
    for i in range(collector.MAX_LATENCIES_PER_TOOL + 500):
        collector.record_tool_call(tool_name="cap_test", status="ok", latency_ms=float(i))
    snapshot = collector.snapshot()
    assert snapshot["tools"]["cap_test"]["count"] == collector.MAX_LATENCIES_PER_TOOL + 500
    # Latency list should have been trimmed.
    assert len(collector._tool_latencies["cap_test"]) <= collector.MAX_LATENCIES_PER_TOOL
