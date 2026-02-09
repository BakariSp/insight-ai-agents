"""Tests for services/stream_adapter.py — event mapping.

Step 1.3 of AI native rewrite.  Tests the _serialize_tool_output helper
and basic adapter structure.  Full integration tests require a real LLM.
"""

from __future__ import annotations

import json
import pytest

from services.stream_adapter import _serialize_tool_output
from services.datastream import DataStreamEncoder


class TestSerializeToolOutput:
    """Verify tool output serialization."""

    def test_dict_passthrough(self):
        result = _serialize_tool_output({"status": "ok", "data": [1, 2, 3]})
        assert result == {"status": "ok", "data": [1, 2, 3]}

    def test_list_passthrough(self):
        result = _serialize_tool_output([1, 2, 3])
        assert result == [1, 2, 3]

    def test_json_string_parsed(self):
        result = _serialize_tool_output('{"key": "value"}')
        assert result == {"key": "value"}

    def test_plain_string_kept(self):
        result = _serialize_tool_output("hello world")
        assert result == "hello world"

    def test_number_stringified(self):
        result = _serialize_tool_output(42)
        assert result == "42"

    def test_none_stringified(self):
        result = _serialize_tool_output(None)
        assert result == "None"


class TestDataStreamEncoderIntegration:
    """Verify DataStreamEncoder produces valid SSE lines."""

    def test_start_event(self):
        enc = DataStreamEncoder()
        line = enc.start(message_id="msg-001")
        payload = json.loads(line.strip().removeprefix("data: "))
        assert payload["type"] == "start"
        assert payload["messageId"] == "msg-001"

    def test_text_delta_event(self):
        enc = DataStreamEncoder()
        line = enc.text_delta("t-0", "Hello")
        payload = json.loads(line.strip().removeprefix("data: "))
        assert payload["type"] == "text-delta"
        assert payload["delta"] == "Hello"

    def test_tool_input_start_event(self):
        enc = DataStreamEncoder()
        line = enc.tool_input_start("tc-1", "generate_quiz_questions")
        payload = json.loads(line.strip().removeprefix("data: "))
        assert payload["type"] == "tool-input-start"
        assert payload["toolCallId"] == "tc-1"
        assert payload["toolName"] == "generate_quiz_questions"

    def test_finish_event(self):
        enc = DataStreamEncoder()
        line = enc.finish("stop")
        assert "finish" in line
        assert "[DONE]" in line

    def test_error_event(self):
        enc = DataStreamEncoder()
        line = enc.error("something went wrong")
        payload = json.loads(line.strip().removeprefix("data: "))
        assert payload["type"] == "error"
        assert "something went wrong" in payload["errorText"]


class TestToolContractModels:
    """Verify the contract models from models/tool_contracts.py."""

    def test_tool_result_serialization(self):
        from models.tool_contracts import ToolResult

        tr = ToolResult(
            data={"questions": []},
            artifact_type="quiz",
            content_format="json",
        )
        d = tr.model_dump()
        assert d["status"] == "ok"
        assert d["artifact_type"] == "quiz"
        assert d["action"] == "complete"

    def test_clarify_event_serialization(self):
        from models.tool_contracts import ClarifyEvent, ClarifyChoice

        ce = ClarifyEvent(
            question="请选择班级",
            options=[ClarifyChoice(label="三班", value="c-003")],
        )
        d = ce.model_dump()
        assert d["question"] == "请选择班级"
        assert len(d["options"]) == 1

    def test_artifact_model(self):
        from models.tool_contracts import Artifact, ContentFormat

        a = Artifact(
            artifact_id="a-001",
            artifact_type="quiz",
            content_format=ContentFormat.JSON,
            content={"questions": []},
        )
        assert a.version == 1
        assert a.content_format == ContentFormat.JSON
