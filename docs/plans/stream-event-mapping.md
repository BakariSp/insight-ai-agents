# Stream Event Mapping: PydanticAI → Data Stream Protocol

**PydanticAI Version:** 1.56.0
**Date:** 2026-02-09
**Status:** FROZEN (Protocol Freeze v1)

## Event Mapping Table

PydanticAI uses an `event_stream_handler` callback API with structured event types.
The `stream_adapter.py` maps these events to Vercel AI SDK Data Stream Protocol SSE lines.

| PydanticAI Event | Fields | Data Stream Protocol SSE | Notes |
|---|---|---|---|
| `PartStartEvent` (part_kind=`text`) | `index`, `part: TextPart` | `{"type":"text-start","id":"t-{index}"}` | Start of text generation |
| `PartDeltaEvent` (delta_kind=`text`) | `index`, `delta: TextPartDelta` | `{"type":"text-delta","id":"t-{index}","delta":"..."}` | Incremental text content |
| `PartEndEvent` (part_kind=`text`) | `index`, `part: TextPart` | `{"type":"text-end","id":"t-{index}"}` | Text generation complete |
| `PartStartEvent` (part_kind=`tool-call`) | `index`, `part: ToolCallPart` | `{"type":"tool-input-start","toolCallId":"...","toolName":"..."}` | Tool call initiated |
| `PartDeltaEvent` (delta_kind=`tool_call`) | `index`, `delta: ToolCallPartDelta` | *(buffered, not emitted)* | Tool args streaming (buffer internally) |
| `PartEndEvent` (part_kind=`tool-call`) | `index`, `part: ToolCallPart` | `{"type":"tool-input-available","toolCallId":"...","toolName":"...","input":{...}}` | Tool args complete |
| `FunctionToolCallEvent` | `part: ToolCallPart` | *(no SSE — tool execution starting)* | Internal: tool about to execute |
| `FunctionToolResultEvent` | `result: ToolReturnPart` | `{"type":"tool-output-available","toolCallId":"...","output":{...}}` | Tool result available |
| `FinalResultEvent` | `tool_name`, `tool_call_id` | *(no SSE — handled by finish)* | Agent decided on final output |
| `AgentRunResultEvent` | `result: AgentRunResult` | — | Stream complete (trigger finish) |
| *(stream end)* | — | `{"type":"finish","finishReason":"stop"}` + `[DONE]` | Stream termination |
| *(error)* | — | `{"type":"error","errorText":"..."}` | Error during stream |

## PydanticAI Event Dataclass Details

```python
# Text streaming
PartStartEvent(index=0, part=TextPart(content="", part_kind="text"), event_kind="part_start")
PartDeltaEvent(index=0, delta=TextPartDelta(content_delta="Hello", part_delta_kind="text"), event_kind="part_delta")
PartEndEvent(index=0, part=TextPart(content="Hello world", part_kind="text"), event_kind="part_end")

# Tool calling
PartStartEvent(index=1, part=ToolCallPart(tool_name="generate_quiz", args={}, tool_call_id="tc-1", part_kind="tool-call"))
PartDeltaEvent(index=1, delta=ToolCallPartDelta(args_delta='{"topic":', part_delta_kind="tool_call"))
PartEndEvent(index=1, part=ToolCallPart(tool_name="generate_quiz", args={"topic":"..."}, tool_call_id="tc-1"))
FunctionToolCallEvent(part=ToolCallPart(...), event_kind="function_tool_call")
FunctionToolResultEvent(result=ToolReturnPart(tool_name="generate_quiz", content={...}, tool_call_id="tc-1"))
```

## message_history Serialization

PydanticAI `agent.run_stream()` accepts `message_history: Sequence[ModelMessage]` where:
- `ModelMessage = ModelRequest | ModelResponse`
- `ModelRequest.parts` contains: `UserPromptPart`, `SystemPromptPart`, `RetryPromptPart`, `ToolReturnPart`
- `ModelResponse.parts` contains: `TextPart`, `ToolCallPart`

After stream completion, `result.new_messages()` returns the full exchange.
We serialize these via `result.new_messages_json()` and deserialize for next turn.
