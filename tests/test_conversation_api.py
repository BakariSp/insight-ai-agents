"""Tests for POST /api/conversation — unified conversation endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from models.blueprint import Blueprint
from models.conversation import ClarifyChoice, ClarifyOptions, RouterResult
from models.entity import EntityType, ResolvedEntity, ResolveResult
from tests.test_planner import _sample_blueprint_args


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Initial mode: chat_smalltalk ──────────────────────────────


@pytest.mark.asyncio
async def test_conversation_smalltalk(client):
    """Greeting → chat_smalltalk action with chatResponse."""
    mock_router = RouterResult(
        intent="chat_smalltalk", confidence=0.9, should_build=False,
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
            "/api/conversation",
            json={"message": "你好"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "chat_smalltalk"
    assert data["chatResponse"] is not None
    assert data["blueprint"] is None


# ── Initial mode: chat_qa ─────────────────────────────────────


@pytest.mark.asyncio
async def test_conversation_chat_qa(client):
    """QA question → chat_qa action."""
    mock_router = RouterResult(
        intent="chat_qa", confidence=0.85, should_build=False,
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
            "/api/conversation",
            json={"message": "What is KPI?"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "chat_qa"
    assert "KPI" in data["chatResponse"]


# ── Initial mode: build_workflow ──────────────────────────────


@pytest.mark.asyncio
async def test_conversation_build_workflow(client):
    """Clear analysis request → build_workflow with blueprint."""
    mock_router = RouterResult(
        intent="build_workflow", confidence=0.9, should_build=True,
    )
    mock_bp = Blueprint(**_sample_blueprint_args())

    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.generate_blueprint",
            new_callable=AsyncMock,
            return_value=(mock_bp, "dashscope/qwen-max"),
        ),
    ):
        resp = await client.post(
            "/api/conversation",
            json={"message": "分析 1A 班英语成绩", "language": "zh-CN"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "build_workflow"
    assert data["blueprint"] is not None
    assert data["blueprint"]["id"] == "bp-test-planner"
    assert data["chatResponse"] is not None


# ── Initial mode: clarify ─────────────────────────────────────


@pytest.mark.asyncio
async def test_conversation_clarify(client):
    """Vague request → clarify with options."""
    mock_router = RouterResult(
        intent="clarify",
        confidence=0.55,
        should_build=False,
        clarifying_question="请问您想分析哪个班级？",
        route_hint="needClassId",
    )
    mock_options = ClarifyOptions(
        type="single_select",
        choices=[
            ClarifyChoice(label="Form 1A", value="class-hk-f1a"),
            ClarifyChoice(label="Form 1B", value="class-hk-f1b"),
        ],
    )

    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.build_clarify_options",
            new_callable=AsyncMock,
            return_value=mock_options,
        ),
    ):
        resp = await client.post(
            "/api/conversation",
            json={"message": "分析英语表现", "teacherId": "t-001"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "clarify"
    assert data["chatResponse"] == "请问您想分析哪个班级？"
    assert data["clarifyOptions"] is not None
    assert len(data["clarifyOptions"]["choices"]) == 2


# ── Follow-up mode: chat ──────────────────────────────────────


@pytest.mark.asyncio
async def test_conversation_followup_chat(client):
    """Follow-up question about existing page → chat action."""
    mock_router = RouterResult(
        intent="chat", confidence=0.85, should_build=False,
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
            return_value="Wong Ka Ho scored the lowest at 58.",
        ),
    ):
        resp = await client.post(
            "/api/conversation",
            json={
                "message": "哪些学生需要关注？",
                "blueprint": bp_json,
                "pageContext": {"mean": 74.2},
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "chat"
    assert "Wong Ka Ho" in data["chatResponse"]
    assert data["blueprint"] is None


# ── Follow-up mode: refine ────────────────────────────────────


@pytest.mark.asyncio
async def test_conversation_followup_refine(client):
    """Tweak request → refine with new blueprint."""
    mock_router = RouterResult(
        intent="refine", confidence=0.8, should_build=True,
    )
    mock_bp = Blueprint(**_sample_blueprint_args())
    bp_json = _sample_blueprint_args()

    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.generate_blueprint",
            new_callable=AsyncMock,
            return_value=(mock_bp, "dashscope/qwen-max"),
        ),
    ):
        resp = await client.post(
            "/api/conversation",
            json={
                "message": "把图表颜色换成蓝色",
                "blueprint": bp_json,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "refine"
    assert data["blueprint"] is not None


# ── Follow-up mode: rebuild ───────────────────────────────────


@pytest.mark.asyncio
async def test_conversation_followup_rebuild(client):
    """Structural change request → rebuild with new blueprint."""
    mock_router = RouterResult(
        intent="rebuild", confidence=0.9, should_build=True,
    )
    mock_bp = Blueprint(**_sample_blueprint_args())
    bp_json = _sample_blueprint_args()

    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.generate_blueprint",
            new_callable=AsyncMock,
            return_value=(mock_bp, "dashscope/qwen-max"),
        ),
    ):
        resp = await client.post(
            "/api/conversation",
            json={
                "message": "加一个语法分析板块",
                "blueprint": bp_json,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "rebuild"
    assert data["blueprint"] is not None


# ── Error handling ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_conversation_missing_message(client):
    """Missing message field → 422."""
    resp = await client.post("/api/conversation", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_conversation_agent_error(client):
    """Agent failure → 502."""
    with patch(
        "api.conversation.classify_intent",
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM timeout"),
    ):
        resp = await client.post(
            "/api/conversation",
            json={"message": "test"},
        )

    assert resp.status_code == 502
    assert "Conversation processing failed" in resp.json()["detail"]


# ── Clarify multi-turn flow ───────────────────────────────────


@pytest.mark.asyncio
async def test_conversation_clarify_then_build(client):
    """Simulate: clarify → user selects → build_workflow."""
    # Round 2: User provides the missing info in context
    mock_router = RouterResult(
        intent="build_workflow", confidence=0.9, should_build=True,
    )
    mock_bp = Blueprint(**_sample_blueprint_args())

    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.generate_blueprint",
            new_callable=AsyncMock,
            return_value=(mock_bp, "dashscope/qwen-max"),
        ),
    ):
        resp = await client.post(
            "/api/conversation",
            json={
                "message": "分析英语表现",
                "context": {"classId": "class-hk-f1a"},
                "conversationId": "conv-123",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "build_workflow"
    assert data["blueprint"] is not None
    assert data["conversationId"] == "conv-123"


# ── Entity resolution: auto-resolve single class ─────────────


@pytest.mark.asyncio
async def test_conversation_build_with_auto_resolve(client):
    """Class mention in message → auto-resolve classId, include resolvedEntities."""
    mock_router = RouterResult(
        intent="build_workflow", confidence=0.9, should_build=True,
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
            return_value=(mock_bp, "dashscope/qwen-max"),
        ),
    ):
        resp = await client.post(
            "/api/conversation",
            json={"message": "分析 1A 班英语成绩", "teacherId": "t-001"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "build_workflow"
    assert data["resolvedEntities"] is not None
    assert len(data["resolvedEntities"]) == 1
    assert data["resolvedEntities"][0]["entityId"] == "class-hk-f1a"
    assert data["resolvedEntities"][0]["entityType"] == "class"


# ── Entity resolution: ambiguous → clarify ───────────────────


@pytest.mark.asyncio
async def test_conversation_build_ambiguous_downgrade_to_clarify(client):
    """Ambiguous class mention → downgrade to clarify with options."""
    mock_router = RouterResult(
        intent="build_workflow", confidence=0.9, should_build=True,
    )
    mock_resolve = ResolveResult(
        entities=[
            ResolvedEntity(
                entity_type=EntityType.CLASS,
                entity_id="class-hk-f1a",
                display_name="Form 1A",
                confidence=0.6,
                match_type="fuzzy",
            ),
            ResolvedEntity(
                entity_type=EntityType.CLASS,
                entity_id="class-hk-f1b",
                display_name="Form 1B",
                confidence=0.5,
                match_type="fuzzy",
            ),
        ],
        is_ambiguous=True,
        scope_mode="multi",
    )

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
    ):
        resp = await client.post(
            "/api/conversation",
            json={"message": "分析 F1 成绩", "teacherId": "t-001"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "clarify"
    assert data["clarifyOptions"] is not None
    assert len(data["clarifyOptions"]["choices"]) == 2


# ── Entity resolution: no mention → normal flow ─────────────


@pytest.mark.asyncio
async def test_conversation_build_no_class_mention(client):
    """No class mention → bypass entity resolution, normal build."""
    mock_router = RouterResult(
        intent="build_workflow", confidence=0.9, should_build=True,
    )
    mock_bp = Blueprint(**_sample_blueprint_args())
    mock_resolve = ResolveResult(entities=[], is_ambiguous=False, scope_mode="none")

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
            return_value=(mock_bp, "dashscope/qwen-max"),
        ),
    ):
        resp = await client.post(
            "/api/conversation",
            json={"message": "分析英语表现", "teacherId": "t-001"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "build_workflow"
    assert data["resolvedEntities"] is None


# ── Entity resolution: context already has classId ───────────


@pytest.mark.asyncio
async def test_conversation_build_skips_resolve_when_context_has_class(client):
    """When context already has classId, skip entity resolution entirely."""
    mock_router = RouterResult(
        intent="build_workflow", confidence=0.9, should_build=True,
    )
    mock_bp = Blueprint(**_sample_blueprint_args())

    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=mock_router,
        ),
        patch(
            "api.conversation.generate_blueprint",
            new_callable=AsyncMock,
            return_value=(mock_bp, "dashscope/qwen-max"),
        ),
        patch(
            "api.conversation.resolve_entities",
            new_callable=AsyncMock,
        ) as mock_resolve_fn,
    ):
        resp = await client.post(
            "/api/conversation",
            json={
                "message": "分析英语表现",
                "context": {"classId": "class-hk-f1a"},
                "teacherId": "t-001",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "build_workflow"
    mock_resolve_fn.assert_not_called()
