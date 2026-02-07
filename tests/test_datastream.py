"""Tests for DataStreamEncoder and map_executor_event.

Validates that encoded output conforms to the Vercel AI SDK
Data Stream Protocol (UI Message Stream v1).
"""

from __future__ import annotations

import json

import pytest

from services.datastream import DataStreamEncoder, map_executor_event


# ── Helpers ──────────────────────────────────────────────────────


def _parse_sse(sse_str: str) -> list[dict | str]:
    """Parse an SSE string into a list of payloads (dicts or raw strings)."""
    results = []
    for line in sse_str.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("data: "):
            payload = line[len("data: ") :]
            if payload == "[DONE]":
                results.append("[DONE]")
            else:
                results.append(json.loads(payload))
    return results


def _parse_first(sse_str: str) -> dict:
    """Parse the first JSON payload from an SSE string."""
    results = _parse_sse(sse_str)
    assert len(results) >= 1, f"Expected at least one payload, got: {sse_str!r}"
    assert isinstance(results[0], dict), f"Expected dict, got: {results[0]!r}"
    return results[0]


# ── DataStreamEncoder unit tests ─────────────────────────────────


class TestMessageControl:
    def test_start_with_custom_id(self):
        enc = DataStreamEncoder()
        payload = _parse_first(enc.start("msg-123"))
        assert payload == {"type": "start", "messageId": "msg-123"}

    def test_start_generates_id(self):
        enc = DataStreamEncoder()
        payload = _parse_first(enc.start())
        assert payload["type"] == "start"
        assert "messageId" in payload
        assert len(payload["messageId"]) == 8

    def test_finish_includes_done_marker(self):
        enc = DataStreamEncoder()
        result = enc.finish()
        payloads = _parse_sse(result)
        assert len(payloads) == 2
        assert payloads[0] == {"type": "finish"}
        assert payloads[1] == "[DONE]"

    def test_start_step(self):
        enc = DataStreamEncoder()
        payload = _parse_first(enc.start_step())
        assert payload == {"type": "start-step"}

    def test_finish_step(self):
        enc = DataStreamEncoder()
        payload = _parse_first(enc.finish_step())
        assert payload == {"type": "finish-step"}


class TestReasoning:
    def test_reasoning_lifecycle(self):
        enc = DataStreamEncoder()
        s = _parse_first(enc.reasoning_start("r-1"))
        d = _parse_first(enc.reasoning_delta("r-1", "Thinking..."))
        e = _parse_first(enc.reasoning_end("r-1"))

        assert s == {"type": "reasoning-start", "id": "r-1"}
        assert d == {"type": "reasoning-delta", "id": "r-1", "delta": "Thinking..."}
        assert e == {"type": "reasoning-end", "id": "r-1"}

    def test_reasoning_delta_unicode(self):
        enc = DataStreamEncoder()
        payload = _parse_first(enc.reasoning_delta("r-1", "正在分析请求..."))
        assert payload["delta"] == "正在分析请求..."


class TestText:
    def test_text_lifecycle(self):
        enc = DataStreamEncoder()
        s = _parse_first(enc.text_start("t-1"))
        d = _parse_first(enc.text_delta("t-1", "Hello!"))
        e = _parse_first(enc.text_end("t-1"))

        assert s == {"type": "text-start", "id": "t-1"}
        assert d == {"type": "text-delta", "id": "t-1", "delta": "Hello!"}
        assert e == {"type": "text-end", "id": "t-1"}

    def test_text_delta_empty(self):
        enc = DataStreamEncoder()
        payload = _parse_first(enc.text_delta("t-1", ""))
        assert payload["delta"] == ""


class TestToolCalls:
    def test_tool_input_start(self):
        enc = DataStreamEncoder()
        payload = _parse_first(enc.tool_input_start("tc-1", "get_class_detail"))
        assert payload == {
            "type": "tool-input-start",
            "toolCallId": "tc-1",
            "toolName": "get_class_detail",
        }

    def test_tool_input_available(self):
        enc = DataStreamEncoder()
        payload = _parse_first(
            enc.tool_input_available("tc-1", "get_class_detail", {"classId": "c-001"})
        )
        assert payload == {
            "type": "tool-input-available",
            "toolCallId": "tc-1",
            "toolName": "get_class_detail",
            "input": {"classId": "c-001"},
        }

    def test_tool_output_available(self):
        enc = DataStreamEncoder()
        payload = _parse_first(
            enc.tool_output_available("tc-1", {"studentCount": 42, "name": "1A"})
        )
        assert payload == {
            "type": "tool-output-available",
            "toolCallId": "tc-1",
            "output": {"studentCount": 42, "name": "1A"},
        }

    def test_tool_output_with_string(self):
        enc = DataStreamEncoder()
        payload = _parse_first(enc.tool_output_available("tc-1", "success"))
        assert payload["output"] == "success"


class TestCustomData:
    def test_data_blueprint(self):
        enc = DataStreamEncoder()
        bp = {"id": "bp-1", "name": "Quiz", "tabs": 2}
        payload = _parse_first(enc.data("blueprint", bp))
        assert payload == {"type": "data-blueprint", "data": bp}

    def test_data_action(self):
        enc = DataStreamEncoder()
        payload = _parse_first(
            enc.data("action", {"action": "build", "mode": "entry"})
        )
        assert payload == {
            "type": "data-action",
            "data": {"action": "build", "mode": "entry"},
        }

    def test_data_page(self):
        enc = DataStreamEncoder()
        page = {"tabs": [{"name": "Analysis"}]}
        payload = _parse_first(enc.data("page", page))
        assert payload == {"type": "data-page", "data": page}


class TestError:
    def test_error_event(self):
        enc = DataStreamEncoder()
        payload = _parse_first(enc.error("Something went wrong"))
        assert payload == {"type": "error", "errorText": "Something went wrong"}


class TestSSEFormat:
    """Verify raw SSE line formatting."""

    def test_line_format(self):
        enc = DataStreamEncoder()
        raw = enc.start_step()
        assert raw.startswith("data: ")
        assert raw.endswith("\n\n")

    def test_json_is_valid(self):
        enc = DataStreamEncoder()
        raw = enc.tool_input_available("tc-1", "test_tool", {"key": "value"})
        json_str = raw.strip().replace("data: ", "", 1)
        parsed = json.loads(json_str)
        assert parsed["type"] == "tool-input-available"

    def test_unicode_not_escaped(self):
        enc = DataStreamEncoder()
        raw = enc.reasoning_delta("r-1", "正在分析")
        assert "正在分析" in raw
        assert "\\u" not in raw


# ── map_executor_event tests ─────────────────────────────────────


class TestMapExecutorEvent:
    def setup_method(self):
        self.enc = DataStreamEncoder()

    def test_phase_event(self):
        event = {"type": "PHASE", "phase": "data", "message": "Fetching data..."}
        lines, call_id = map_executor_event(self.enc, event)
        payloads = []
        for line in lines:
            payloads.extend(_parse_sse(line))

        types = [p["type"] for p in payloads]
        assert "finish-step" in types
        assert "start-step" in types
        assert "reasoning-start" in types
        assert "reasoning-delta" in types
        assert "reasoning-end" in types

        delta = next(p for p in payloads if p["type"] == "reasoning-delta")
        assert delta["delta"] == "Fetching data..."
        assert delta["id"] == "phase-data"

    def test_tool_call_event(self):
        event = {
            "type": "TOOL_CALL",
            "tool": "get_class_detail",
            "args": {"classId": "c-001"},
        }
        lines, call_id = map_executor_event(self.enc, event)
        payloads = []
        for line in lines:
            payloads.extend(_parse_sse(line))

        assert len(payloads) == 2
        assert payloads[0]["type"] == "tool-input-start"
        assert payloads[0]["toolName"] == "get_class_detail"
        assert payloads[1]["type"] == "tool-input-available"
        assert payloads[1]["input"] == {"classId": "c-001"}

        # call_id should be set for subsequent TOOL_RESULT
        assert call_id is not None
        assert len(call_id) == 8

    def test_tool_result_with_last_call_id(self):
        event = {
            "type": "TOOL_RESULT",
            "tool": "get_class_detail",
            "status": "success",
            "result": {"studentCount": 42},
        }
        lines, call_id = map_executor_event(
            self.enc, event, last_call_id="tc-prev"
        )
        payloads = []
        for line in lines:
            payloads.extend(_parse_sse(line))

        assert len(payloads) == 1
        assert payloads[0]["type"] == "tool-output-available"
        assert payloads[0]["toolCallId"] == "tc-prev"
        assert payloads[0]["output"] == {"studentCount": 42}

    def test_tool_result_without_last_call_id(self):
        event = {"type": "TOOL_RESULT", "status": "success", "result": {"ok": True}}
        lines, call_id = map_executor_event(self.enc, event)
        payloads = []
        for line in lines:
            payloads.extend(_parse_sse(line))

        assert len(payloads) == 1
        assert payloads[0]["type"] == "tool-output-available"
        # Should have generated a call_id
        assert len(payloads[0]["toolCallId"]) == 8

    def test_block_start_event(self):
        event = {
            "type": "BLOCK_START",
            "blockId": "tab1-md",
            "componentType": "markdown",
        }
        lines, _ = map_executor_event(self.enc, event)
        payloads = []
        for line in lines:
            payloads.extend(_parse_sse(line))

        assert len(payloads) == 1
        assert payloads[0]["type"] == "data-block-start"
        assert payloads[0]["data"] == {
            "blockId": "tab1-md",
            "componentType": "markdown",
        }

    def test_slot_delta_event(self):
        event = {
            "type": "SLOT_DELTA",
            "blockId": "tab1-md",
            "slotKey": "content",
            "deltaText": "### Overview\n",
        }
        lines, _ = map_executor_event(self.enc, event)
        payloads = []
        for line in lines:
            payloads.extend(_parse_sse(line))

        assert len(payloads) == 1
        assert payloads[0]["type"] == "data-slot-delta"
        assert payloads[0]["data"]["deltaText"] == "### Overview\n"

    def test_block_complete_event(self):
        event = {"type": "BLOCK_COMPLETE", "blockId": "tab1-md"}
        lines, _ = map_executor_event(self.enc, event)
        payloads = []
        for line in lines:
            payloads.extend(_parse_sse(line))

        assert len(payloads) == 1
        assert payloads[0]["type"] == "data-block-complete"
        assert payloads[0]["data"] == {"blockId": "tab1-md"}

    def test_complete_event(self):
        page_json = {"tabs": [{"name": "Analysis"}]}
        event = {"type": "COMPLETE", "message": "completed", "result": page_json}
        lines, _ = map_executor_event(self.enc, event)
        payloads = []
        for line in lines:
            payloads.extend(_parse_sse(line))

        assert len(payloads) == 1
        assert payloads[0]["type"] == "data-page"
        assert payloads[0]["data"] == page_json

    def test_error_event(self):
        event = {"type": "ERROR", "message": "Tool timeout"}
        lines, _ = map_executor_event(self.enc, event)
        payloads = []
        for line in lines:
            payloads.extend(_parse_sse(line))

        assert len(payloads) == 1
        assert payloads[0]["type"] == "error"
        assert payloads[0]["errorText"] == "Tool timeout"

    def test_data_error_event(self):
        event = {"type": "DATA_ERROR", "message": "get_class_detail timed out"}
        lines, _ = map_executor_event(self.enc, event)
        payloads = []
        for line in lines:
            payloads.extend(_parse_sse(line))

        assert len(payloads) == 1
        assert payloads[0]["type"] == "error"

    def test_message_event(self):
        event = {"type": "MESSAGE", "message": "Processing..."}
        lines, _ = map_executor_event(self.enc, event)
        payloads = []
        for line in lines:
            payloads.extend(_parse_sse(line))

        types = [p["type"] for p in payloads]
        assert "reasoning-start" in types
        assert "reasoning-delta" in types
        assert "reasoning-end" in types

    def test_unknown_event_no_output(self):
        event = {"type": "UNKNOWN_TYPE", "foo": "bar"}
        lines, _ = map_executor_event(self.enc, event)
        assert lines == []

    def test_tool_call_then_result_chain(self):
        """Simulate a TOOL_CALL followed by TOOL_RESULT — call_id propagation."""
        call_event = {
            "type": "TOOL_CALL",
            "tool": "calculate_stats",
            "args": {"metric": "all"},
        }
        _, call_id = map_executor_event(self.enc, call_event)

        result_event = {
            "type": "TOOL_RESULT",
            "status": "success",
            "result": {"mean": 78.5},
        }
        lines, _ = map_executor_event(
            self.enc, result_event, last_call_id=call_id
        )
        payloads = []
        for line in lines:
            payloads.extend(_parse_sse(line))

        assert payloads[0]["toolCallId"] == call_id

    def test_full_phase_sequence(self):
        """Simulate a complete data phase: PHASE → TOOL_CALL → TOOL_RESULT."""
        events = [
            {"type": "PHASE", "phase": "data", "message": "Fetching data..."},
            {
                "type": "TOOL_CALL",
                "tool": "get_class_detail",
                "args": {"classId": "c-1"},
            },
            {
                "type": "TOOL_RESULT",
                "tool": "get_class_detail",
                "status": "success",
                "result": {"name": "1A"},
            },
        ]

        all_payloads = []
        call_id = None
        for event in events:
            lines, call_id = map_executor_event(
                self.enc, event, last_call_id=call_id
            )
            for line in lines:
                all_payloads.extend(_parse_sse(line))

        types = [p["type"] for p in all_payloads]
        assert "finish-step" in types
        assert "start-step" in types
        assert "reasoning-start" in types
        assert "tool-input-start" in types
        assert "tool-input-available" in types
        assert "tool-output-available" in types
