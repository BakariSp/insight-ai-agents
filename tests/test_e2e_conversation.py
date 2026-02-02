"""End-to-end tests for the unified conversation gateway.

Tests full flows: smalltalk → clarify → build → follow-up chat → refine → rebuild.
Uses mocked LLM (TestModel) but real routing logic and clarify builder.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from models.blueprint import Blueprint
from models.conversation import RouterResult
from tests.test_planner import _sample_blueprint_args


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── E2E: Full conversation lifecycle ─────────────────────────


@pytest.mark.asyncio
async def test_e2e_smalltalk_to_build(client):
    """E2E: greeting → chat, then analysis request → build_workflow."""

    # Round 1: Greeting
    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=RouterResult(
                intent="chat_smalltalk", confidence=0.95, should_build=False,
            ),
        ),
        patch(
            "api.conversation.chat_response",
            new_callable=AsyncMock,
            return_value="你好！我可以帮你分析数据。",
        ),
    ):
        resp = await client.post(
            "/api/conversation",
            json={"message": "你好", "language": "zh-CN"},
        )
    assert resp.status_code == 200
    assert resp.json()["action"] == "chat_smalltalk"

    # Round 2: Clear analysis request
    mock_bp = Blueprint(**_sample_blueprint_args())
    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=RouterResult(
                intent="build_workflow", confidence=0.9, should_build=True,
            ),
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
                "message": "分析 1A 班英语成绩",
                "language": "zh-CN",
                "teacherId": "t-001",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "build_workflow"
    assert data["blueprint"] is not None
    assert data["blueprint"]["id"] == "bp-test-planner"


@pytest.mark.asyncio
async def test_e2e_clarify_to_build(client):
    """E2E: vague request → clarify → user provides context → build."""

    # Round 1: Vague request → clarify
    with patch(
        "api.conversation.classify_intent",
        new_callable=AsyncMock,
        return_value=RouterResult(
            intent="clarify",
            confidence=0.5,
            should_build=False,
            clarifying_question="请选择班级",
            route_hint="needClassId",
        ),
    ):
        resp = await client.post(
            "/api/conversation",
            json={
                "message": "分析英语表现",
                "teacherId": "t-001",
                "conversationId": "conv-001",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "clarify"
    assert data["clarifyOptions"] is not None
    # Should have real class choices from mock data
    assert len(data["clarifyOptions"]["choices"]) == 2
    assert data["conversationId"] == "conv-001"

    # Round 2: User selects a class → build
    mock_bp = Blueprint(**_sample_blueprint_args())
    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=RouterResult(
                intent="build_workflow", confidence=0.9, should_build=True,
            ),
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
                "message": "分析 Form 1A 英语表现",
                "teacherId": "t-001",
                "context": {"classId": "class-hk-f1a"},
                "conversationId": "conv-001",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "build_workflow"
    assert data["blueprint"] is not None
    assert data["conversationId"] == "conv-001"


@pytest.mark.asyncio
async def test_e2e_build_then_followup(client):
    """E2E: build → followup chat → refine → rebuild — full follow-up lifecycle."""

    bp_json = _sample_blueprint_args()
    mock_bp = Blueprint(**bp_json)

    # Round 1: Follow-up chat about existing page
    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=RouterResult(
                intent="chat", confidence=0.85, should_build=False,
            ),
        ),
        patch(
            "api.conversation.page_chat_response",
            new_callable=AsyncMock,
            return_value="Wong Ka Ho needs attention — scored only 58.",
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

    # Round 2: Refine the page
    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=RouterResult(
                intent="refine", confidence=0.85, should_build=True,
            ),
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
                "message": "只显示不及格的学生",
                "blueprint": bp_json,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["action"] == "refine"
    assert resp.json()["blueprint"] is not None

    # Round 3: Rebuild the page
    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=RouterResult(
                intent="rebuild", confidence=0.9, should_build=True,
            ),
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
    assert resp.json()["action"] == "rebuild"
    assert resp.json()["blueprint"] is not None


@pytest.mark.asyncio
async def test_e2e_response_camel_case(client):
    """E2E: all responses use camelCase serialization."""
    with (
        patch(
            "api.conversation.classify_intent",
            new_callable=AsyncMock,
            return_value=RouterResult(
                intent="chat_smalltalk", confidence=0.9, should_build=False,
            ),
        ),
        patch(
            "api.conversation.chat_response",
            new_callable=AsyncMock,
            return_value="Hi!",
        ),
    ):
        resp = await client.post(
            "/api/conversation",
            json={"message": "hello", "conversationId": "c-1"},
        )
    data = resp.json()
    # Verify camelCase keys in response
    assert "chatResponse" in data
    assert "clarifyOptions" in data
    assert "conversationId" in data
    # Verify no snake_case keys leak through
    assert "chat_response" not in data
    assert "clarify_options" not in data
    assert "conversation_id" not in data


@pytest.mark.asyncio
async def test_e2e_existing_endpoints_still_work(client):
    """E2E: existing /api/workflow/generate and /api/health still work."""
    # Health endpoint
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"

    # Workflow endpoint (still available as direct-call)
    mock_bp = Blueprint(**_sample_blueprint_args())
    with patch(
        "api.workflow.generate_blueprint",
        new_callable=AsyncMock,
        return_value=(mock_bp, "dashscope/qwen-max"),
    ):
        resp = await client.post(
            "/api/workflow/generate",
            json={"userPrompt": "Analyze performance"},
        )
    assert resp.status_code == 200
    assert resp.json()["blueprint"]["id"] == "bp-test-planner"
