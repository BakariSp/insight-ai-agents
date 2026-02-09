"""Experiment: Does PydanticAI stream intermediate text when output_type is set?

Tests three scenarios:
  A) No output_type (baseline) — stream_text captures everything
  B) output_type=FinalResult — does stream_text capture intermediate text?
  C) output_type=FinalResult with Agent.iter() — fine-grained control

Run:
  cd insight-ai-agent
  python experiments/test_output_type_streaming.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Literal

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents.provider import create_model
from config.settings import get_settings


# ── Models ──────────────────────────────────────────────

class FinalResult(BaseModel):
    """Structured exit from agent loop."""
    status: Literal["answer_ready", "artifact_ready", "clarify_needed"]
    message: str = Field(description="Human-readable message for the teacher")
    artifacts: list[str] = Field(default_factory=list)


# ── Fake tool ───────────────────────────────────────────

def generate_fake_content(topic: str) -> str:
    """Simulate a content generation tool. Returns a fake artifact."""
    time.sleep(0.5)  # Simulate work
    return json.dumps({
        "file": f"{topic.replace(' ', '_')}.docx",
        "size": 12345,
        "status": "generated",
    })


# ── Experiment A: No output_type (baseline) ─────────────

async def experiment_a():
    """Baseline: no output_type, tool_choice=auto. How does streaming work?"""
    print("\n" + "=" * 60)
    print("EXPERIMENT A: No output_type (baseline)")
    print("=" * 60)

    settings = get_settings()
    model = create_model(settings.router_model)  # Use fast model for testing

    agent = Agent(
        model=model,
        system_prompt=(
            "You are a teacher assistant. You have a tool called generate_fake_content. "
            "When asked to generate content, you MUST call the tool first, "
            "then summarize the result. Keep responses short (1-2 sentences)."
        ),
        retries=2,
        defer_model_check=True,
    )
    agent.tool_plain()(generate_fake_content)

    chunks = []
    tool_calls_seen = []

    try:
        async with agent.run_stream(
            "Generate a lesson plan about Newton's First Law",
            model_settings={"max_tokens": 512},
        ) as stream:
            async for chunk in stream.stream_text(delta=True):
                chunks.append(chunk)
                print(f"  [text-delta] {chunk!r}")

            # Check messages for tool calls
            for msg in stream.all_messages():
                for part in msg.parts:
                    if hasattr(part, "tool_name"):
                        tool_calls_seen.append(part.tool_name)
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
        return

    print(f"\n  Summary:")
    print(f"    Text chunks received: {len(chunks)}")
    print(f"    Total text length: {sum(len(c) for c in chunks)}")
    print(f"    Tool calls seen: {tool_calls_seen}")
    print(f"    Full text: {''.join(chunks)[:200]}...")


# ── Experiment B: output_type=FinalResult + run_stream ──

async def experiment_b():
    """output_type=FinalResult. Does stream_text capture intermediate text?"""
    print("\n" + "=" * 60)
    print("EXPERIMENT B: output_type=FinalResult + run_stream")
    print("=" * 60)

    settings = get_settings()
    model = create_model(settings.router_model)

    agent = Agent(
        model=model,
        output_type=FinalResult,
        system_prompt=(
            "You are a teacher assistant. You have a tool called generate_fake_content. "
            "When asked to generate content, FIRST call generate_fake_content, "
            "THEN call the final_result output tool with status='artifact_ready'. "
            "Keep the message short (1-2 sentences)."
        ),
        retries=2,
        defer_model_check=True,
    )
    agent.tool_plain()(generate_fake_content)

    chunks = []
    tool_calls_seen = []

    try:
        async with agent.run_stream(
            "Generate a lesson plan about Newton's First Law",
            model_settings={"max_tokens": 512},
        ) as stream:
            # stream_text() CANNOT be used with output_type — try stream_output
            print("  Trying stream_text()...")
            try:
                async for chunk in stream.stream_text(delta=True):
                    chunks.append(chunk)
                    print(f"  [text-delta] {chunk!r}")
            except Exception as text_err:
                print(f"  [WARN] stream_text() failed: {text_err}")
                print(f"  Trying stream_output() instead...")
                try:
                    async for partial in stream.stream_output(debounce_by=0.01):
                        msg_preview = ""
                        if hasattr(partial, "message") and partial.message:
                            msg_preview = partial.message[:80]
                        status = getattr(partial, "status", "?")
                        chunks.append(msg_preview)
                        print(f"  [output-delta] status={status}, message={msg_preview!r}")
                except Exception as out_err:
                    print(f"  [WARN] stream_output() also failed: {out_err}")

            # Get structured output
            result = await stream.get_output()
            print(f"\n  [FinalResult] status={result.status}, message={result.message!r}")
            print(f"  [FinalResult] artifacts={result.artifacts}")

            # Check messages for tool calls
            for msg in stream.all_messages():
                for part in msg.parts:
                    if hasattr(part, "tool_name"):
                        tool_calls_seen.append(part.tool_name)
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return

    print(f"\n  Summary:")
    print(f"    Text chunks received: {len(chunks)}")
    print(f"    Total text length: {sum(len(c) for c in chunks)}")
    print(f"    Tool calls seen: {tool_calls_seen}")
    if chunks:
        print(f"    Full text: {''.join(chunks)[:200]}...")
    else:
        print(f"    [WARN] No text chunks -- intermediate text NOT streamed!")


# ── Experiment C: output_type=FinalResult + Agent.iter() ─

async def experiment_c():
    """output_type=FinalResult with Agent.iter() for fine-grained control."""
    print("\n" + "=" * 60)
    print("EXPERIMENT C: output_type=FinalResult + Agent.iter()")
    print("=" * 60)

    settings = get_settings()
    model = create_model(settings.router_model)

    agent = Agent(
        model=model,
        output_type=FinalResult,
        system_prompt=(
            "You are a teacher assistant. You have a tool called generate_fake_content. "
            "When asked to generate content, FIRST call generate_fake_content, "
            "THEN call the final_result output tool with status='artifact_ready'. "
            "Keep the message short (1-2 sentences)."
        ),
        retries=2,
        defer_model_check=True,
    )
    agent.tool_plain()(generate_fake_content)

    node_types = []
    text_from_nodes = []

    try:
        async with agent.iter(
            "Generate a lesson plan about Newton's First Law",
            model_settings={"max_tokens": 512},
        ) as agent_run:
            async for node in agent_run:
                node_type = type(node).__name__
                node_types.append(node_type)
                print(f"  [node] {node_type}: {str(node)[:120]}")

                # Try to extract text from different node types
                if hasattr(node, "text"):
                    text_from_nodes.append(node.text)
                if hasattr(node, "data"):
                    text_from_nodes.append(str(node.data)[:100])

            result = agent_run.result.output if hasattr(agent_run, "result") else None
            if result:
                print(f"\n  [FinalResult] status={result.status}, message={result.message!r}")
            else:
                # Try getting from the last End node
                print(f"\n  [FinalResult] Check last node for output")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return

    print(f"\n  Summary:")
    print(f"    Node types seen: {node_types}")
    print(f"    Text from nodes: {len(text_from_nodes)}")


# ── Experiment D: output_type + stream with structured output streaming ─

async def experiment_d():
    """output_type=FinalResult, try stream_structured() instead of stream_text()."""
    print("\n" + "=" * 60)
    print("EXPERIMENT D: output_type + stream_structured()")
    print("=" * 60)

    settings = get_settings()
    model = create_model(settings.router_model)

    agent = Agent(
        model=model,
        output_type=FinalResult,
        system_prompt=(
            "You are a teacher assistant. You have a tool called generate_fake_content. "
            "When asked to generate content, FIRST call generate_fake_content, "
            "THEN call the final_result output tool with status='artifact_ready'. "
            "Keep the message short (1-2 sentences)."
        ),
        retries=2,
        defer_model_check=True,
    )
    agent.tool_plain()(generate_fake_content)

    partial_results = []

    try:
        async with agent.run_stream(
            "Generate a lesson plan about Newton's First Law",
            model_settings={"max_tokens": 512},
        ) as stream:
            # Try streaming structured output (partial validation)
            if hasattr(stream, "stream_structured"):
                async for partial in stream.stream_structured():
                    partial_results.append(partial)
                    msg_preview = ""
                    if hasattr(partial, "message") and partial.message:
                        msg_preview = partial.message[:80]
                    print(f"  [structured-delta] status={getattr(partial, 'status', '?')}, message={msg_preview!r}")
            else:
                # Fallback: stream_output for newer versions
                async for partial in stream.stream_output():
                    partial_results.append(partial)
                    msg_preview = ""
                    if hasattr(partial, "message") and partial.message:
                        msg_preview = partial.message[:80]
                    print(f"  [output-delta] status={getattr(partial, 'status', '?')}, message={msg_preview!r}")

            result = await stream.get_output()
            print(f"\n  [FinalResult] status={result.status}, message={result.message!r}")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return

    print(f"\n  Summary:")
    print(f"    Partial results received: {len(partial_results)}")


# ── Main ────────────────────────────────────────────────

async def main():
    print("PydanticAI output_type Streaming Experiment")
    print(f"PydanticAI version: ", end="")
    try:
        import pydantic_ai
        print(pydantic_ai.__version__)
    except Exception:
        print("unknown")

    settings = get_settings()
    print(f"Model: {settings.router_model}")
    print(f"Strong model: {settings.strong_model}")

    for exp_name, exp_fn in [
        ("A", experiment_a),
        ("B", experiment_b),
        ("C", experiment_c),
        ("D", experiment_d),
    ]:
        try:
            await exp_fn()
        except Exception as e:
            print(f"\n  [FATAL] Experiment {exp_name} crashed: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print("ALL EXPERIMENTS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
