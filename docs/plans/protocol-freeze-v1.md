# Protocol Freeze v1

**Date:** 2026-02-09
**Status:** FROZEN — subsequent Steps MUST NOT modify these contracts.

## Frozen Items

### 1. Stream Event Mapping

PydanticAI 1.56.0 event types → Data Stream Protocol SSE mapping is frozen.
See `docs/plans/stream-event-mapping.md` for the complete mapping table.

### 2. Artifact Data Model

```python
class Artifact(BaseModel):
    artifact_id: str
    artifact_type: str        # "quiz" | "ppt" | "doc" | "interactive"
    content_format: str       # "json" | "markdown" | "html"
    content: Any
    resources: list[ArtifactResource] = []
    version: int = 1
```

### 3. Artifact Field Naming

- Business type: `artifact_type` (NOT `kind`)
- Technical format: `content_format`

### 4. ContentFormat Enum

Only currently supported values:
- `json` — structured data (quiz, PPT slides)
- `markdown` — text documents
- `html` — interactive content

### 5. History Serialization Format

Messages serialized via PydanticAI's `new_messages_json()` / loaded via model validation.
Four message part types:
- `UserPromptPart` (part_kind="user-prompt")
- `TextPart` (part_kind="text")
- `ToolCallPart` (part_kind="tool-call")
- `ToolReturnPart` (part_kind="tool-return")

Tool call/return pairs are atomic — truncation preserves or discards entire pairs.
