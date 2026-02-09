"""Step 1.6 — Native Agent smoke test.

Verifies the native runtime can:
1. Import without errors
2. Registry has tools registered
3. Toolset selection works correctly
4. DataStreamEncoder produces valid SSE

Does NOT call real LLM (that requires API keys).

Usage:
    cd insight-ai-agent
    python scripts/native_smoke_test.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_imports():
    print("[1/6] Testing imports...")
    from tools.registry import get_registered_count, get_toolset_counts
    from agents.native_agent import NativeAgent, AgentDeps, select_toolsets
    from services.stream_adapter import adapt_stream
    from services.datastream import DataStreamEncoder
    from models.tool_contracts import ToolResult, Artifact, ClarifyEvent
    from config.prompts.native_agent import SYSTEM_PROMPT
    print("  OK — all modules imported successfully")


def test_registry():
    print("[2/6] Testing tool registry...")
    import tools.native_tools  # populate registry
    from tools.registry import get_registered_count, get_toolset_counts, get_tool_names

    count = get_registered_count()
    print(f"  Registered tools: {count}")
    assert count >= 6, f"Expected at least 6 tools, got {count}"

    counts = get_toolset_counts()
    print(f"  Toolset counts: {counts}")
    assert counts.get("base_data", 0) >= 1
    assert counts.get("generation", 0) >= 1
    assert counts.get("platform", 0) >= 1

    names = get_tool_names()
    print(f"  Tool names: {names}")
    assert "generate_quiz_questions" in names
    assert "search_teacher_documents" in names
    print("  OK")


def test_toolset_selection():
    print("[3/6] Testing toolset selection...")
    from agents.native_agent import AgentDeps, select_toolsets

    deps = AgentDeps(teacher_id="t-001", conversation_id="conv-test")

    # Simple chat — should have base_data + platform at minimum
    result = select_toolsets("你好", deps)
    assert "base_data" in result
    assert "platform" in result
    print(f"  '你好' → {result}")

    # Quiz generation — should include generation
    result = select_toolsets("帮我出 5 道选择题", deps)
    assert "generation" in result
    print(f"  '帮我出 5 道选择题' → {result}")

    # Analysis — should include analysis
    result = select_toolsets("分析一下三班成绩", deps)
    assert "analysis" in result
    print(f"  '分析一下三班成绩' → {result}")

    # Modify with artifacts — should include artifact_ops
    deps_with_artifacts = AgentDeps(
        teacher_id="t-001",
        conversation_id="conv-test",
        has_artifacts=True,
    )
    result = select_toolsets("改一下", deps_with_artifacts)
    assert "artifact_ops" in result
    print(f"  '改一下' (has_artifacts) → {result}")

    print("  OK")


def test_data_stream_encoder():
    print("[4/6] Testing DataStreamEncoder...")
    from services.datastream import DataStreamEncoder
    import json

    enc = DataStreamEncoder()

    # Start event
    line = enc.start(message_id="test-msg")
    payload = json.loads(line.strip().removeprefix("data: "))
    assert payload["type"] == "start"
    print(f"  start event OK")

    # Text events
    line = enc.text_start("t-0")
    payload = json.loads(line.strip().removeprefix("data: "))
    assert payload["type"] == "text-start"

    line = enc.text_delta("t-0", "Hello")
    payload = json.loads(line.strip().removeprefix("data: "))
    assert payload["delta"] == "Hello"

    line = enc.text_end("t-0")
    payload = json.loads(line.strip().removeprefix("data: "))
    assert payload["type"] == "text-end"
    print(f"  text events OK")

    # Tool events
    line = enc.tool_input_start("tc-1", "generate_quiz_questions")
    payload = json.loads(line.strip().removeprefix("data: "))
    assert payload["toolName"] == "generate_quiz_questions"

    line = enc.tool_output_available("tc-1", {"questions": []})
    payload = json.loads(line.strip().removeprefix("data: "))
    assert payload["type"] == "tool-output-available"
    print(f"  tool events OK")

    # Finish
    line = enc.finish("stop")
    assert "[DONE]" in line
    print(f"  finish event OK")

    print("  OK")


def test_contract_models():
    print("[5/6] Testing contract models...")
    from models.tool_contracts import ToolResult, Artifact, ContentFormat, ClarifyEvent

    tr = ToolResult(data={"questions": []}, artifact_type="quiz", content_format="json")
    assert tr.status == "ok"

    a = Artifact(
        artifact_id="a-1",
        artifact_type="quiz",
        content_format=ContentFormat.JSON,
        content={"questions": []},
    )
    assert a.version == 1

    ce = ClarifyEvent(question="请选择班级")
    assert ce.allow_custom_input is True

    print("  OK")


def test_conversation_gateway_structure():
    print("[6/6] Testing conversation gateway structure...")
    import api.conversation as conv_mod

    assert hasattr(conv_mod, "router")
    assert hasattr(conv_mod, "_NATIVE_ENABLED")

    # Count lines in the new conversation.py
    import inspect
    source = inspect.getsource(conv_mod)
    line_count = len(source.splitlines())
    print(f"  conversation.py: {line_count} lines (target: <200)")
    assert line_count < 250, f"conversation.py is {line_count} lines, target <200"

    print("  OK")


def main():
    print("=" * 60)
    print("Native Agent Smoke Test — Step 1.6")
    print("=" * 60)
    print()

    tests = [
        test_imports,
        test_registry,
        test_toolset_selection,
        test_data_stream_encoder,
        test_contract_models,
        test_conversation_gateway_structure,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAILED: {e}")
            failed += 1
        print()

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
