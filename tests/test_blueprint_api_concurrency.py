"""Tests for Blueprint API concurrency control."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

from main import app
from models.soft_blueprint import (
    EntitySlot,
    EntitySlotType,
    OutputHints,
    SoftBlueprint,
    ArtifactType,
)


@pytest.mark.asyncio
async def test_distill_success():
    """Test successful distillation request."""
    mock_blueprint = SoftBlueprint(
        name="Test Blueprint",
        entity_slots=[
            EntitySlot(key="class_id", label="Class", type=EntitySlotType.CLASS_SELECTOR, required=True)
        ],
        execution_prompt="Test prompt {class_name}",
        output_hints=OutputHints(expected_artifacts=[ArtifactType.REPORT]),
    )

    with patch("api.blueprint.distill_conversation", new=AsyncMock(return_value=mock_blueprint)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/blueprint/distill",
                json={
                    "teacherId": "teacher-1",
                    "conversationId": "conv-1",
                    "language": "zh",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "Test Blueprint"
            assert len(data["entitySlots"]) == 1


@pytest.mark.asyncio
async def test_distill_validation_error():
    """Test distillation with validation error."""
    with patch(
        "api.blueprint.distill_conversation",
        new=AsyncMock(side_effect=ValueError("entity_slots cannot be empty")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/blueprint/distill",
                json={
                    "teacherId": "teacher-1",
                    "conversationId": "conv-1",
                },
            )

            assert response.status_code == 400
            assert "entity_slots" in response.text


@pytest.mark.asyncio
async def test_distill_runtime_error():
    """Test distillation with runtime error."""
    with patch(
        "api.blueprint.distill_conversation",
        new=AsyncMock(side_effect=RuntimeError("LLM API failed")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/blueprint/distill",
                json={
                    "teacherId": "teacher-1",
                    "conversationId": "conv-1",
                },
            )

            assert response.status_code == 500


@pytest.mark.asyncio
async def test_distill_concurrency_limit():
    """Test that only 1 distillation can run per teacher."""
    # Create a slow distillation that blocks
    async def slow_distill(*args, **kwargs):
        await asyncio.sleep(1)  # Simulate slow LLM call
        return SoftBlueprint(
            name="Test",
            entity_slots=[
                EntitySlot(
                    key="test", label="Test", type=EntitySlotType.TEXT_INPUT, required=True
                )
            ],
            execution_prompt="Test",
        )

    with patch("api.blueprint.distill_conversation", new=slow_distill):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=5.0) as client:
            # Start first request (will block for 1 second)
            task1 = asyncio.create_task(
                client.post(
                    "/api/blueprint/distill",
                    json={
                        "teacherId": "teacher-1",
                        "conversationId": "conv-1",
                    },
                )
            )

            # Give first request time to acquire semaphore
            await asyncio.sleep(0.1)

            # Try second request immediately (should be rate limited)
            resp2 = await client.post(
                "/api/blueprint/distill",
                json={
                    "teacherId": "teacher-1",
                    "conversationId": "conv-2",
                },
            )

            assert resp2.status_code == 429  # Rate limited
            assert "蒸馏任务进行中" in resp2.text

            # Clean up first task
            task1.cancel()
            try:
                await task1
            except asyncio.CancelledError:
                pass


@pytest.mark.asyncio
async def test_distill_concurrency_different_teachers():
    """Test that different teachers can distill concurrently."""
    async def slow_distill(*args, **kwargs):
        await asyncio.sleep(0.5)
        return SoftBlueprint(
            name="Test",
            entity_slots=[
                EntitySlot(
                    key="test", label="Test", type=EntitySlotType.TEXT_INPUT, required=True
                )
            ],
            execution_prompt="Test",
        )

    with patch("api.blueprint.distill_conversation", new=slow_distill):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=5.0) as client:
            # Start requests for two different teachers
            task1 = asyncio.create_task(
                client.post(
                    "/api/blueprint/distill",
                    json={
                        "teacherId": "teacher-1",
                        "conversationId": "conv-1",
                    },
                )
            )

            task2 = asyncio.create_task(
                client.post(
                    "/api/blueprint/distill",
                    json={
                        "teacherId": "teacher-2",  # Different teacher
                        "conversationId": "conv-2",
                    },
                )
            )

            # Both should complete successfully
            resp1, resp2 = await asyncio.gather(task1, task2)

            assert resp1.status_code == 200
            assert resp2.status_code == 200
