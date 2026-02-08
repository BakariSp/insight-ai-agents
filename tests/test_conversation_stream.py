"""Tests for POST /api/conversation/stream — SSE Data Stream Protocol endpoint.

Validates that the streaming conversation endpoint emits correct Vercel AI SDK
Data Stream Protocol events for each conversation flow: chat, build, clarify,
follow-up chat, refine, rebuild, and error handling.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from models.blueprint import Blueprint
from models.conversation import RouterResult
from models.entity import EntityType, ResolvedEntity, ResolveResult
from services.conversation_store import ConversationSession, get_conversation_store
from services.datastream import DataStreamEncoder
from tests.test_planner import _sample_blueprint_args
from api.conversation import (
    _build_tool_result_events,
    _compose_content_request_after_clarify,
    _is_ppt_confirmation,
    _outline_to_fallback_slides,
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _parse_sse_stream(raw_text: str) -> list[dict | str]:
    """Parse raw SSE text into a list of JSON payloads and [DONE] markers."""
    results = []
    for line in raw_text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("data: "):
            payload = line[len("data: "):]
            if payload == "[DONE]":
                results.append("[DONE]")
            else:
                try:
                    results.append(json.loads(payload))
                except json.JSONDecodeError:
                    results.append(payload)
    return results


def _types(payloads: list[dict | str]) -> list[str]:
    """Extract type fields from parsed payloads."""
    return [
        p["type"] if isinstance(p, dict) else p
        for p in payloads
    ]


# ── Response headers ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_response_headers(client):
    """Streaming endpoint returns correct SSE + Data Stream Protocol headers."""
    mock_router = RouterResult(
        intent="chat_smalltalk", confidence=0.9, should_build=False
    )
    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.chat_response",
            new_callable=AsyncMock,
            return_value="Hello!",
        ),
    ):
        resp = await client.post(
            "/api/conversation/stream",
            json={"message": "Hi"},
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    assert resp.headers.get("x-vercel-ai-ui-message-stream") == "v1"


# ── Chat (smalltalk) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_chat_smalltalk(client):
    """Greeting → reasoning + data-action + text + finish."""
    mock_router = RouterResult(
        intent="chat_smalltalk", confidence=0.9, should_build=False
    )
    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.chat_response",
            new_callable=AsyncMock,
            return_value="你好！有什么可以帮你的吗？",
        ),
    ):
        resp = await client.post(
            "/api/conversation/stream",
            json={"message": "你好"},
        )

    payloads = _parse_sse_stream(resp.text)
    types = _types(payloads)

    # Must start with 'start' and end with 'finish' + [DONE]
    assert types[0] == "start"
    assert types[-2] == "finish"
    assert types[-1] == "[DONE]"

    # Should have intent reasoning
    assert "reasoning-start" in types
    assert "reasoning-delta" in types
    assert "reasoning-end" in types

    # Should have action event
    action_events = [p for p in payloads if isinstance(p, dict) and p.get("type") == "data-action"]
    assert len(action_events) >= 1
    assert action_events[0]["data"]["action"] == "chat"
    assert action_events[0]["data"]["chatKind"] == "smalltalk"

    # Should have text
    assert "text-start" in types
    assert "text-delta" in types
    text_deltas = [p for p in payloads if isinstance(p, dict) and p.get("type") == "text-delta"]
    assert any("你好" in d["delta"] for d in text_deltas)
    assert "text-end" in types


# ── Chat (QA) ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_chat_qa(client):
    """QA question → reasoning + data-action(qa) + text."""
    mock_router = RouterResult(
        intent="chat_qa", confidence=0.85, should_build=False
    )
    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.chat_response",
            new_callable=AsyncMock,
            return_value="KPI stands for Key Performance Indicator.",
        ),
    ):
        resp = await client.post(
            "/api/conversation/stream",
            json={"message": "What is KPI?"},
        )

    payloads = _parse_sse_stream(resp.text)
    action_events = [p for p in payloads if isinstance(p, dict) and p.get("type") == "data-action"]
    assert action_events[0]["data"]["chatKind"] == "qa"

    text_deltas = [p for p in payloads if isinstance(p, dict) and p.get("type") == "text-delta"]
    assert any("KPI" in d["delta"] for d in text_deltas)


# ── Build (with classId in context) ─────────────────────────────


@pytest.mark.asyncio
async def test_stream_build_with_context(client):
    """Build with classId in context → reasoning + blueprint + executor events + text."""
    mock_router = RouterResult(
        intent="build_workflow", confidence=0.9, should_build=True
    )
    mock_bp = Blueprint(**_sample_blueprint_args())

    # Mock executor to yield a few events
    async def mock_executor_stream(blueprint, context):
        yield {"type": "PHASE", "phase": "data", "message": "Fetching data..."}
        yield {"type": "TOOL_CALL", "tool": "get_class_detail", "args": {"classId": "c-1"}}
        yield {"type": "TOOL_RESULT", "tool": "get_class_detail", "status": "success", "result": {"name": "1A"}}
        yield {"type": "PHASE", "phase": "compose", "message": "Composing page..."}
        yield {
            "type": "COMPLETE",
            "message": "completed",
            "progress": 100,
            "result": {"page": {"tabs": []}},
        }

    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.generate_blueprint",
            new_callable=AsyncMock,
            return_value=(mock_bp, "test-model"),
        ),
        patch.object(
            type(client).__module__,  # dummy
            "ExecutorAgent",
            create=True,
        ) if False else
        patch(
            "api.conversation._executor.execute_blueprint_stream",
            side_effect=mock_executor_stream,
        ),
    ):
        resp = await client.post(
            "/api/conversation/stream",
            json={
                "message": "分析英语成绩",
                "context": {"classId": "class-hk-f1a"},
            },
        )

    payloads = _parse_sse_stream(resp.text)
    types = _types(payloads)

    # Protocol envelope
    assert types[0] == "start"
    assert types[-2] == "finish"
    assert types[-1] == "[DONE]"

    # Intent reasoning
    assert "reasoning-start" in types

    # Blueprint planning reasoning
    reasoning_deltas = [
        p for p in payloads
        if isinstance(p, dict) and p.get("type") == "reasoning-delta"
    ]
    assert any("Blueprint ready" in d.get("delta", "") for d in reasoning_deltas)

    # Blueprint data event
    bp_events = [p for p in payloads if isinstance(p, dict) and p.get("type") == "data-blueprint"]
    assert len(bp_events) == 1
    assert bp_events[0]["data"]["id"] == "bp-test-planner"

    # Action event
    action_events = [p for p in payloads if isinstance(p, dict) and p.get("type") == "data-action"]
    assert any(e["data"]["action"] == "build" for e in action_events)

    # Executor tool events
    assert "tool-input-start" in types
    assert "tool-input-available" in types
    assert "tool-output-available" in types

    # Page result
    page_events = [p for p in payloads if isinstance(p, dict) and p.get("type") == "data-page"]
    assert len(page_events) == 1

    # Completion text
    assert "text-start" in types
    text_deltas = [p for p in payloads if isinstance(p, dict) and p.get("type") == "text-delta"]
    assert any("Done" in d.get("delta", "") or "Generated" in d.get("delta", "") for d in text_deltas)


# ── Build with entity resolution ────────────────────────────────


@pytest.mark.asyncio
async def test_stream_build_with_entity_resolution(client):
    """Entity resolution → tool events for each resolved entity."""
    mock_router = RouterResult(
        intent="build_workflow", confidence=0.9, should_build=True
    )
    mock_bp = Blueprint(**_sample_blueprint_args())
    mock_resolve = ResolveResult(
        entities=[
            ResolvedEntity(
                entity_type=EntityType.CLASS,
                entity_id="class-hk-f1a",
                display_name="Form 1A",
                confidence=1.0,
                match_type="exact",
            ),
        ],
        is_ambiguous=False,
        scope_mode="single",
    )

    async def mock_executor_stream(blueprint, context):
        yield {"type": "COMPLETE", "message": "completed", "progress": 100, "result": {"page": {}}}

    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.resolve_entities",
            new_callable=AsyncMock,
            return_value=mock_resolve,
        ),
        patch(
            "api.conversation.generate_blueprint",
            new_callable=AsyncMock,
            return_value=(mock_bp, "test-model"),
        ),
        patch(
            "api.conversation._executor.execute_blueprint_stream",
            side_effect=mock_executor_stream,
        ),
    ):
        resp = await client.post(
            "/api/conversation/stream",
            json={"message": "分析 1A 班英语成绩", "teacherId": "t-001"},
        )

    payloads = _parse_sse_stream(resp.text)
    types = _types(payloads)

    # Entity resolution should emit tool events
    tool_inputs = [
        p for p in payloads
        if isinstance(p, dict) and p.get("type") == "tool-input-available"
    ]
    assert len(tool_inputs) >= 1
    assert tool_inputs[0]["toolName"] == "resolve_entity"

    tool_outputs = [
        p for p in payloads
        if isinstance(p, dict) and p.get("type") == "tool-output-available"
    ]
    assert len(tool_outputs) >= 1
    assert tool_outputs[0]["output"]["entityId"] == "class-hk-f1a"


# ── Clarify ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_clarify(client):
    """Clarify intent → data-action(clarify) + text."""
    mock_router = RouterResult(
        intent="clarify",
        confidence=0.55,
        should_build=False,
        clarifying_question="请问您想分析哪个班级？",
        route_hint="needClassId",
    )
    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
    ):
        resp = await client.post(
            "/api/conversation/stream",
            json={"message": "分析英语表现", "teacherId": "t-001"},
        )

    payloads = _parse_sse_stream(resp.text)
    types = _types(payloads)

    # Action
    action_events = [p for p in payloads if isinstance(p, dict) and p.get("type") == "data-action"]
    assert any(e["data"]["action"] == "clarify" for e in action_events)

    # Clarify hint
    clarify_events = [p for p in payloads if isinstance(p, dict) and p.get("type") == "data-clarify"]
    assert len(clarify_events) >= 1

    # Text with question
    text_deltas = [p for p in payloads if isinstance(p, dict) and p.get("type") == "text-delta"]
    assert any("provide more details" in d.get("delta", "") or "班级" in d.get("delta", "") for d in text_deltas)


# ── Follow-up: page chat ────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_followup_chat(client):
    """Follow-up chat about existing page → text response."""
    mock_router = RouterResult(
        intent="chat", confidence=0.85, should_build=False
    )
    bp_json = _sample_blueprint_args()

    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.page_chat_response",
            new_callable=AsyncMock,
            return_value="The average score is 78.5.",
        ),
    ):
        resp = await client.post(
            "/api/conversation/stream",
            json={
                "message": "平均分是多少？",
                "blueprint": bp_json,
                "pageContext": {"mean": 78.5},
            },
        )

    payloads = _parse_sse_stream(resp.text)
    types = _types(payloads)

    action_events = [p for p in payloads if isinstance(p, dict) and p.get("type") == "data-action"]
    assert any(e["data"]["action"] == "chat" for e in action_events)
    assert any(e["data"]["chatKind"] == "page" for e in action_events)

    text_deltas = [p for p in payloads if isinstance(p, dict) and p.get("type") == "text-delta"]
    assert any("78.5" in d.get("delta", "") for d in text_deltas)


# ── Follow-up: refine with patch ────────────────────────────────


@pytest.mark.asyncio
async def test_stream_followup_refine_patch(client):
    """Refine with patch_layout scope → reasoning + patch-plan data."""
    from models.patch import PatchPlan, RefineScope

    mock_router = RouterResult(
        intent="refine",
        confidence=0.9,
        should_build=True,
        refine_scope="patch_layout",
    )
    bp_json = _sample_blueprint_args()

    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.analyze_refine",
            new_callable=AsyncMock,
            return_value=PatchPlan(scope=RefineScope.PATCH_LAYOUT),
        ),
    ):
        resp = await client.post(
            "/api/conversation/stream",
            json={
                "message": "Change colors to blue",
                "blueprint": bp_json,
            },
        )

    payloads = _parse_sse_stream(resp.text)
    types = _types(payloads)

    # Reasoning about patch
    reasoning_deltas = [
        p for p in payloads
        if isinstance(p, dict) and p.get("type") == "reasoning-delta"
    ]
    assert any("patch" in d.get("delta", "").lower() or "refine" in d.get("delta", "").lower()
               for d in reasoning_deltas)

    # Action = refine
    action_events = [p for p in payloads if isinstance(p, dict) and p.get("type") == "data-action"]
    assert any(e["data"]["action"] == "refine" for e in action_events)

    # Patch plan data
    patch_events = [p for p in payloads if isinstance(p, dict) and p.get("type") == "data-patch-plan"]
    assert len(patch_events) == 1
    assert patch_events[0]["data"]["scope"] == "patch_layout"


# ── Follow-up: rebuild ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_followup_rebuild(client):
    """Rebuild → reasoning + blueprint + executor events."""
    mock_router = RouterResult(
        intent="rebuild", confidence=0.9, should_build=True
    )
    mock_bp = Blueprint(**_sample_blueprint_args())
    bp_json = _sample_blueprint_args()

    async def mock_executor_stream(blueprint, context):
        yield {"type": "COMPLETE", "message": "completed", "progress": 100, "result": {"page": {}}}

    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.generate_blueprint",
            new_callable=AsyncMock,
            return_value=(mock_bp, "test-model"),
        ),
        patch(
            "api.conversation._executor.execute_blueprint_stream",
            side_effect=mock_executor_stream,
        ),
    ):
        resp = await client.post(
            "/api/conversation/stream",
            json={
                "message": "完全重建分析页面",
                "blueprint": bp_json,
            },
        )

    payloads = _parse_sse_stream(resp.text)
    types = _types(payloads)

    # Should have blueprint
    bp_events = [p for p in payloads if isinstance(p, dict) and p.get("type") == "data-blueprint"]
    assert len(bp_events) == 1

    # Action = rebuild
    action_events = [p for p in payloads if isinstance(p, dict) and p.get("type") == "data-action"]
    assert any(e["data"]["action"] == "rebuild" for e in action_events)

    # Page result
    page_events = [p for p in payloads if isinstance(p, dict) and p.get("type") == "data-page"]
    assert len(page_events) == 1


# ── Error handling ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_error_in_classify(client):
    """Classification failure → error event in stream (not HTTP 502)."""
    with patch(
        "api.conversation.classify_intent",
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM timeout"),
    ):
        resp = await client.post(
            "/api/conversation/stream",
            json={"message": "test"},
        )

    # SSE endpoint returns 200 (stream started) with error inside
    assert resp.status_code == 200
    payloads = _parse_sse_stream(resp.text)
    types = _types(payloads)

    assert "error" in types
    error_events = [p for p in payloads if isinstance(p, dict) and p.get("type") == "error"]
    assert any("LLM timeout" in e.get("errorText", "") for e in error_events)

    # Stream should still finish gracefully
    assert types[-2] == "finish"
    assert types[-1] == "[DONE]"


# ── Protocol structure ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_always_starts_and_finishes(client):
    """Every stream begins with 'start' and ends with 'finish' + [DONE]."""
    mock_router = RouterResult(
        intent="chat_smalltalk", confidence=0.9, should_build=False
    )
    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.chat_response",
            new_callable=AsyncMock,
            return_value="Hi!",
        ),
    ):
        resp = await client.post(
            "/api/conversation/stream",
            json={"message": "hello"},
        )

    payloads = _parse_sse_stream(resp.text)
    types = _types(payloads)

    assert types[0] == "start"
    assert "messageId" in payloads[0]
    assert types[-2] == "finish"
    assert types[-1] == "[DONE]"


@pytest.mark.asyncio
async def test_stream_steps_are_balanced(client):
    """Every start-step has a matching finish-step."""
    mock_router = RouterResult(
        intent="chat_smalltalk", confidence=0.9, should_build=False
    )
    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.chat_response",
            new_callable=AsyncMock,
            return_value="Hi!",
        ),
    ):
        resp = await client.post(
            "/api/conversation/stream",
            json={"message": "hello"},
        )

    payloads = _parse_sse_stream(resp.text)
    types = _types(payloads)

    starts = types.count("start-step")
    finishes = types.count("finish-step")
    assert starts == finishes, f"Unbalanced steps: {starts} starts, {finishes} finishes"


# ── Legacy endpoint still works ──────────────────────────────────


@pytest.mark.asyncio
async def test_legacy_json_endpoint_still_works(client):
    """POST /api/conversation still returns JSON (backward compat)."""
    mock_router = RouterResult(
        intent="chat_smalltalk", confidence=0.9, should_build=False
    )
    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.chat_response",
            new_callable=AsyncMock,
            return_value="Hello!",
        ),
    ):
        resp = await client.post(
            "/api/conversation",
            json={"message": "Hi"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "chat"
    assert data["chatKind"] == "smalltalk"


def test_compose_content_request_after_clarify():
    """Clarify reply should be expanded into an actionable content prompt."""
    session = ConversationSession(conversation_id="conv-test")
    session.add_user_turn("生成一个实验课课程计划")
    session.add_assistant_turn("请补充年级和时长", action="clarify")
    session.add_user_turn("中学二年级，90分钟，先讲后练")

    expanded = _compose_content_request_after_clarify(
        session,
        "中学二年级，90分钟，先讲后练",
    )
    assert expanded != "中学二年级，90分钟，先讲后练"
    assert "Original request" in expanded
    assert "生成一个实验课课程计划" in expanded
    assert "Additional details from user" in expanded


@pytest.mark.asyncio
async def test_stream_persists_last_intent_and_action(client):
    """Stream endpoint should persist last_intent/last_action in session state."""
    mock_router = RouterResult(
        intent="chat_smalltalk", confidence=0.95, should_build=False
    )
    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.chat_response",
            new_callable=AsyncMock,
            return_value="Hello!",
        ),
    ):
        resp = await client.post(
            "/api/conversation/stream",
            json={"message": "hello"},
        )

    payloads = _parse_sse_stream(resp.text)
    conversation_events = [
        p for p in payloads
        if isinstance(p, dict) and p.get("type") == "data-conversation"
    ]
    assert conversation_events, "missing data-conversation event"
    conv_id = conversation_events[0]["data"]["conversationId"]

    store = get_conversation_store()
    session = await store.get(conv_id)
    assert session is not None
    assert session.last_intent == "chat_smalltalk"
    assert session.last_action == "chat_smalltalk"


def test_is_ppt_confirmation_detects_cn_and_en():
    assert _is_ppt_confirmation("确认生成PPT")
    assert _is_ppt_confirmation("Please go ahead and generate the slides")
    assert not _is_ppt_confirmation("先给我看一个大纲")


def test_outline_to_fallback_slides_generates_title_and_content():
    payload = {
        "title": "概率统计 Lesson PPT",
        "outline": [
            {"title": "导入", "key_points": ["目标", "背景"]},
            {"title": "讲解", "key_points": ["公式", "例题"]},
        ],
    }
    slides = _outline_to_fallback_slides(payload)
    assert len(slides) >= 3
    assert slides[0]["layout"] == "title"
    assert slides[0]["title"] == "概率统计 Lesson PPT"
    assert slides[1]["layout"] == "content"


def test_build_tool_result_events_for_quiz_artifacts():
    """generate_quiz_questions tool result should map to quiz SSE artifacts."""
    enc = DataStreamEncoder()
    events = _build_tool_result_events(
        enc,
        "generate_quiz_questions",
        {
            "questions": [
                {"id": "q1", "question": "1+1=?", "questionType": "SINGLE_CHOICE"},
                {"id": "q2", "question": "2+2=?", "questionType": "SINGLE_CHOICE"},
            ],
        },
    )
    payloads = _parse_sse_stream("".join(events))
    types = _types(payloads)
    assert types.count("data-quiz-question") == 2
    assert "data-quiz-complete" in types
