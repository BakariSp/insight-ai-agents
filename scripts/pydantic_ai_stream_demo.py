"""Step 0.5.2 — Minimal PydanticAI stream demo.

Demonstrates the actual event types produced by PydanticAI 1.56.0's
run_stream() with a simple tool.  Run this to verify the stream event mapping.

Usage:
    cd insight-ai-agent
    python scripts/pydantic_ai_stream_demo.py
"""

import asyncio
import os

from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.messages import TextPart, ToolCallPart, ToolReturnPart


async def demo_tool(ctx: RunContext[None], question: str) -> str:
    """A simple demo tool that echoes back the question."""
    return f"Echo: {question}"


async def main():
    model_name = os.environ.get("DEMO_MODEL", "dashscope/qwen-turbo-latest")

    # Import provider to create model
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from agents.provider import create_model
    model = create_model(model_name)

    agent = Agent(
        model=model,
        instructions="You are a helpful assistant. If the user asks a question, use the demo_tool to answer.",
        tools=[Tool(demo_tool)],
    )

    print(f"=== PydanticAI Stream Demo (model={model_name}) ===\n")

    async with agent.run_stream("What is 2+2? Use the demo tool.") as stream:
        print("--- stream_responses() events ---")
        async for response, is_last in stream.stream_responses():
            for idx, part in enumerate(response.parts):
                if isinstance(part, TextPart):
                    print(f"  [{idx}] TextPart: content={part.content[:80]!r} (is_last={is_last})")
                elif isinstance(part, ToolCallPart):
                    print(f"  [{idx}] ToolCallPart: name={part.tool_name}, id={part.tool_call_id}, args={part.args}")

        print("\n--- new_messages() after stream ---")
        for msg in stream.new_messages():
            for part in msg.parts:
                kind = getattr(part, "part_kind", type(part).__name__)
                if isinstance(part, ToolReturnPart):
                    print(f"  ToolReturnPart: name={part.tool_name}, id={part.tool_call_id}, content={str(part.content)[:80]}")
                elif isinstance(part, ToolCallPart):
                    print(f"  ToolCallPart: name={part.tool_name}, id={part.tool_call_id}")
                elif isinstance(part, TextPart):
                    print(f"  TextPart: {part.content[:80]!r}")
                else:
                    print(f"  {kind}: {str(part)[:80]}")

        print(f"\n--- Usage ---")
        usage = stream.usage()
        print(f"  request_tokens={getattr(usage, 'request_tokens', '?')}")
        print(f"  response_tokens={getattr(usage, 'response_tokens', '?')}")


if __name__ == "__main__":
    asyncio.run(main())
