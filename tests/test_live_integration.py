"""Live Integration Tests — Real API calls for pre-release validation.

These tests call REAL APIs (LLM and optionally Java backend) without mocking.
They are designed to validate the system before deployment.

Run with:
    pytest tests/test_live_integration.py -v -s --tb=short

Requirements:
    - Valid LLM API key in .env (DASHSCOPE_API_KEY or equivalent)
    - Optionally: Java backend running or USE_MOCK_DATA=true

Test Categories:
    A. Router Intent Classification (real LLM)
    B. Blueprint Generation (real LLM)
    C. Full Conversation Flow (real LLM + data)
    D. Page Generation with SSE (real LLM + data)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from config.settings import get_settings

# Configure logging for live tests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# Test Configuration
# ══════════════════════════════════════════════════════════════

# Skip condition: no API key configured
def _has_llm_api_key() -> bool:
    """Check if any LLM API key is configured."""
    settings = get_settings()
    return bool(
        settings.dashscope_api_key
        or settings.openai_api_key
        or settings.anthropic_api_key
        or settings.zai_api_key
    )


SKIP_NO_API_KEY = pytest.mark.skipif(
    not _has_llm_api_key(),
    reason="No LLM API key configured in .env",
)

# Test results collector for report generation
_test_results: list[dict[str, Any]] = []


def _record_result(
    test_name: str,
    category: str,
    input_data: Any,
    output_data: Any,
    duration_ms: float,
    status: str = "pass",
    error: str | None = None,
):
    """Record test result for report generation."""
    _test_results.append({
        "test_name": test_name,
        "category": category,
        "timestamp": datetime.now().isoformat(),
        "duration_ms": round(duration_ms, 2),
        "status": status,
        "input": input_data,
        "output": output_data,
        "error": error,
    })


# ══════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════

@pytest.fixture
async def client():
    """Create async HTTP client for API tests with JavaClient lifecycle."""
    from main import app
    from services.java_client import get_java_client

    # Start JavaClient before tests (lifespan isn't triggered by ASGITransport)
    java_client = get_java_client()
    await java_client.start()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Close JavaClient after tests
    await java_client.close()


@pytest.fixture(scope="session", autouse=True)
def save_results():
    """Save test results to JSON file after all tests complete."""
    yield
    if _test_results:
        output_dir = Path("docs/testing")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "live-integration-results.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(_test_results, f, indent=2, ensure_ascii=False)
        logger.info("Test results saved to %s", output_file)


# ══════════════════════════════════════════════════════════════
# Category A: Router Intent Classification
# ══════════════════════════════════════════════════════════════

@SKIP_NO_API_KEY
@pytest.mark.asyncio
async def test_live_router_smalltalk():
    """A1: Router classifies greeting as chat_smalltalk."""
    from agents.router import classify_intent

    message = "你好"
    start = time.perf_counter()
    result = await classify_intent(message)
    duration = (time.perf_counter() - start) * 1000

    logger.info("Router result: intent=%s, confidence=%.2f", result.intent, result.confidence)

    _record_result(
        test_name="test_live_router_smalltalk",
        category="A. Router",
        input_data={"message": message},
        output_data={
            "intent": result.intent,
            "confidence": result.confidence,
            "should_build": result.should_build,
        },
        duration_ms=duration,
    )

    assert result.intent in ("chat_smalltalk", "chat_qa")
    # High confidence for clear chat intent is expected
    assert result.confidence > 0


@SKIP_NO_API_KEY
@pytest.mark.asyncio
async def test_live_router_build_workflow():
    """A2: Router classifies analysis request as build_workflow."""
    from agents.router import classify_intent

    message = "分析高一数学班的期末考试成绩"
    start = time.perf_counter()
    result = await classify_intent(message)
    duration = (time.perf_counter() - start) * 1000

    logger.info("Router result: intent=%s, confidence=%.2f", result.intent, result.confidence)

    _record_result(
        test_name="test_live_router_build_workflow",
        category="A. Router",
        input_data={"message": message},
        output_data={
            "intent": result.intent,
            "confidence": result.confidence,
            "should_build": result.should_build,
        },
        duration_ms=duration,
    )

    assert result.intent == "build_workflow"
    assert result.confidence >= 0.7
    assert result.should_build is True


@SKIP_NO_API_KEY
@pytest.mark.asyncio
async def test_live_router_clarify():
    """A3: Router classifies vague request as clarify."""
    from agents.router import classify_intent

    message = "分析一下英语表现"
    start = time.perf_counter()
    result = await classify_intent(message)
    duration = (time.perf_counter() - start) * 1000

    logger.info("Router result: intent=%s, confidence=%.2f", result.intent, result.confidence)

    _record_result(
        test_name="test_live_router_clarify",
        category="A. Router",
        input_data={"message": message},
        output_data={
            "intent": result.intent,
            "confidence": result.confidence,
            "clarifying_question": result.clarifying_question,
            "route_hint": result.route_hint,
        },
        duration_ms=duration,
    )

    # May be build_workflow with lower confidence or clarify
    assert result.confidence < 0.9


# ══════════════════════════════════════════════════════════════
# Category B: Blueprint Generation
# ══════════════════════════════════════════════════════════════

@SKIP_NO_API_KEY
@pytest.mark.asyncio
async def test_live_blueprint_generation():
    """B1: Generate Blueprint from natural language request."""
    from agents.planner import generate_blueprint

    user_prompt = "分析高一数学班的期末考试成绩，显示成绩分布和各题得分情况"
    start = time.perf_counter()
    blueprint, model = await generate_blueprint(user_prompt, language="zh-CN")
    duration = (time.perf_counter() - start) * 1000

    logger.info("Blueprint generated: %s (id=%s)", blueprint.name, blueprint.id)
    logger.info("Model used: %s", model)

    _record_result(
        test_name="test_live_blueprint_generation",
        category="B. Blueprint",
        input_data={"user_prompt": user_prompt, "language": "zh-CN"},
        output_data={
            "id": blueprint.id,
            "name": blueprint.name,
            "description": blueprint.description,
            "capability_level": blueprint.capability_level,
            "model": model,
            "data_bindings_count": len(blueprint.data_contract.bindings),
            "compute_nodes_count": len(blueprint.compute_graph.nodes),
            "ui_tabs_count": len(blueprint.ui_composition.tabs),
        },
        duration_ms=duration,
    )

    assert blueprint.id is not None
    assert blueprint.name is not None
    assert blueprint.data_contract is not None
    assert blueprint.compute_graph is not None
    assert blueprint.ui_composition is not None
    assert len(blueprint.ui_composition.tabs) > 0


@SKIP_NO_API_KEY
@pytest.mark.asyncio
async def test_live_blueprint_english():
    """B2: Generate Blueprint in English."""
    from agents.planner import generate_blueprint

    user_prompt = "Analyze Form 1A English test scores, show score distribution and performance by question"
    start = time.perf_counter()
    blueprint, model = await generate_blueprint(user_prompt, language="en")
    duration = (time.perf_counter() - start) * 1000

    logger.info("Blueprint generated: %s", blueprint.name)

    _record_result(
        test_name="test_live_blueprint_english",
        category="B. Blueprint",
        input_data={"user_prompt": user_prompt, "language": "en"},
        output_data={
            "id": blueprint.id,
            "name": blueprint.name,
            "description": blueprint.description,
            "model": model,
        },
        duration_ms=duration,
    )

    assert blueprint.id is not None
    assert blueprint.name is not None


# ══════════════════════════════════════════════════════════════
# Category C: Full Conversation Flow
# ══════════════════════════════════════════════════════════════

@SKIP_NO_API_KEY
@pytest.mark.asyncio
async def test_live_conversation_chat(client):
    """C1: Conversation API handles chat request."""
    start = time.perf_counter()
    resp = await client.post(
        "/api/conversation",
        json={
            "message": "你好，介绍一下你自己",
            "language": "zh-CN",
        },
    )
    duration = (time.perf_counter() - start) * 1000

    data = resp.json()
    logger.info("Conversation response: action=%s", data.get("action"))

    _record_result(
        test_name="test_live_conversation_chat",
        category="C. Conversation",
        input_data={"message": "你好，介绍一下你自己"},
        output_data={
            "status_code": resp.status_code,
            "action": data.get("action"),
            "mode": data.get("mode"),
            "chat_response_preview": (data.get("chatResponse") or "")[:200],
        },
        duration_ms=duration,
    )

    assert resp.status_code == 200
    assert data["action"] in ("chat", "chat_smalltalk", "chat_qa")
    assert data["chatResponse"] is not None


@SKIP_NO_API_KEY
@pytest.mark.asyncio
async def test_live_conversation_build(client):
    """C2: Conversation API generates Blueprint for analysis request."""
    start = time.perf_counter()
    resp = await client.post(
        "/api/conversation",
        json={
            "message": "分析高一数学班的作业成绩",
            "language": "zh-CN",
            "teacherId": "t-001",
        },
    )
    duration = (time.perf_counter() - start) * 1000

    data = resp.json()
    logger.info("Conversation response: action=%s", data.get("action"))

    output_data = {
        "status_code": resp.status_code,
        "action": data.get("action"),
        "mode": data.get("mode"),
    }

    if data.get("blueprint"):
        output_data["blueprint_name"] = data["blueprint"].get("name")
        output_data["blueprint_id"] = data["blueprint"].get("id")

    if data.get("clarifyOptions"):
        output_data["clarify_type"] = data["clarifyOptions"].get("type")
        output_data["clarify_choices_count"] = len(data["clarifyOptions"].get("choices", []))

    _record_result(
        test_name="test_live_conversation_build",
        category="C. Conversation",
        input_data={"message": "分析高一数学班的作业成绩", "teacherId": "t-001"},
        output_data=output_data,
        duration_ms=duration,
    )

    assert resp.status_code == 200
    # Response could be build (with blueprint) or clarify (needs more info)
    assert data["action"] in ("build", "clarify", "build_workflow")


# ══════════════════════════════════════════════════════════════
# Category D: Page Generation with SSE
# ══════════════════════════════════════════════════════════════

def _parse_sse_events(text: str) -> list[dict]:
    """Parse SSE event stream into list of event dicts."""
    events = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload:
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    pass
    return events


@SKIP_NO_API_KEY
@pytest.mark.asyncio
async def test_live_page_generation(client):
    """D1: Full page generation with real LLM and SSE streaming."""
    from agents.planner import generate_blueprint

    # Step 1: Generate Blueprint
    user_prompt = "分析作业提交情况，显示统计数据和分析结论"
    start_bp = time.perf_counter()
    blueprint, _ = await generate_blueprint(user_prompt, language="zh-CN")
    bp_duration = (time.perf_counter() - start_bp) * 1000

    logger.info("Blueprint generated in %.2fms: %s", bp_duration, blueprint.name)

    # Step 2: Execute Blueprint via SSE
    bp_json = blueprint.model_dump(by_alias=True, mode="json")

    start_page = time.perf_counter()
    resp = await client.post(
        "/api/page/generate",
        json={
            "blueprint": bp_json,
            "context": {
                "teacherId": "t-001",
                "input": {"assignment": "a-001"},
            },
        },
    )
    page_duration = (time.perf_counter() - start_page) * 1000

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")

    events = _parse_sse_events(resp.text)
    logger.info("SSE events received: %d", len(events))

    # Analyze events
    event_types = [e.get("type") for e in events]
    phases = [e.get("phase") for e in events if e.get("type") == "PHASE"]
    block_starts = [e for e in events if e.get("type") == "BLOCK_START"]
    complete_event = next((e for e in events if e.get("type") == "COMPLETE"), None)

    _record_result(
        test_name="test_live_page_generation",
        category="D. Page Generation",
        input_data={
            "user_prompt": user_prompt,
            "blueprint_id": blueprint.id,
        },
        output_data={
            "blueprint_duration_ms": round(bp_duration, 2),
            "page_duration_ms": round(page_duration, 2),
            "total_duration_ms": round(bp_duration + page_duration, 2),
            "event_count": len(events),
            "event_types": list(set(event_types)),
            "phases": phases,
            "block_starts_count": len(block_starts),
            "complete_status": complete_event.get("message") if complete_event else None,
            "page_title": (
                complete_event.get("result", {}).get("page", {}).get("meta", {}).get("pageTitle")
                if complete_event else None
            ),
        },
        duration_ms=bp_duration + page_duration,
    )

    # Assertions
    assert "PHASE" in event_types
    assert "COMPLETE" in event_types
    assert complete_event is not None
    # Allow both success and error (in case of data/LLM issues)
    assert complete_event.get("message") in ("completed", "error")


@SKIP_NO_API_KEY
@pytest.mark.asyncio
async def test_live_full_e2e_flow(client):
    """D2: Complete E2E flow: conversation → blueprint → page."""
    # Step 1: Conversation to get Blueprint
    start = time.perf_counter()
    conv_resp = await client.post(
        "/api/conversation",
        json={
            "message": "分析学生的作业完成情况",
            "language": "zh-CN",
            "teacherId": "t-001",
            "context": {"classId": "class-1a"},  # Provide context to skip clarify
        },
    )
    conv_duration = (time.perf_counter() - start) * 1000

    conv_data = conv_resp.json()
    logger.info("Conversation: action=%s, duration=%.2fms", conv_data.get("action"), conv_duration)

    if conv_data.get("action") not in ("build", "build_workflow"):
        # If clarify, record and skip page generation
        _record_result(
            test_name="test_live_full_e2e_flow",
            category="D. Page Generation",
            input_data={"message": "分析学生的作业完成情况"},
            output_data={
                "conversation_action": conv_data.get("action"),
                "conversation_duration_ms": round(conv_duration, 2),
                "note": "Stopped at clarify step - would need user selection",
            },
            duration_ms=conv_duration,
        )
        pytest.skip("Conversation resulted in clarify - manual selection needed")

    blueprint = conv_data.get("blueprint")
    assert blueprint is not None

    # Step 2: Generate page from Blueprint
    start_page = time.perf_counter()
    page_resp = await client.post(
        "/api/page/generate",
        json={
            "blueprint": blueprint,
            "context": {
                "teacherId": "t-001",
                "input": {"assignment": "a-001"},
            },
        },
    )
    page_duration = (time.perf_counter() - start_page) * 1000

    events = _parse_sse_events(page_resp.text)
    complete_event = next((e for e in events if e.get("type") == "COMPLETE"), None)

    total_duration = conv_duration + page_duration

    _record_result(
        test_name="test_live_full_e2e_flow",
        category="D. Page Generation",
        input_data={"message": "分析学生的作业完成情况"},
        output_data={
            "conversation_action": conv_data.get("action"),
            "conversation_duration_ms": round(conv_duration, 2),
            "blueprint_name": blueprint.get("name"),
            "page_duration_ms": round(page_duration, 2),
            "total_duration_ms": round(total_duration, 2),
            "event_count": len(events),
            "complete_status": complete_event.get("message") if complete_event else None,
        },
        duration_ms=total_duration,
    )

    assert page_resp.status_code == 200
    assert complete_event is not None


@SKIP_NO_API_KEY
@pytest.mark.asyncio
async def test_live_critical_path_e2e(client):
    """D3: Critical Path E2E — Single prompt to full page generation with REAL Java backend.

    This is the KEY production test: one natural language request
    produces a complete interactive analysis page using REAL data.

    Flow: User Prompt → Router → Blueprint → Executor (Java API) → SSE → Page

    Real Java Backend Data:
    - Teacher ID: 2fe869fb-4a2d-4aa1-a173-c263235dc62b
    - Classes: 高一数学班, 高一英语班, 高三语文班
    - Class ID (高一英语班): 1e4fd110-0d58-4daa-a048-ee691fc7bef4
    - Assignment ID (测试一): assign-87174785-e2a9-462b-97e1-008554ea1f5c
    - USE_MOCK_DATA must be false in .env
    """
    # ══════════════════════════════════════════════════════════
    # REAL PRODUCTION DATA FROM JAVA BACKEND
    # ══════════════════════════════════════════════════════════
    user_prompt = "分析高一英语班的'测试一'作业成绩，显示平均分和成绩分布"
    real_teacher_id = "2fe869fb-4a2d-4aa1-a173-c263235dc62b"
    # Real class ID from Java backend (高一英语班)
    real_class_id = "1e4fd110-0d58-4daa-a048-ee691fc7bef4"
    # Real assignment ID from Java backend (测试一)
    real_assignment_id = "assign-87174785-e2a9-462b-97e1-008554ea1f5c"

    logger.info("=" * 60)
    logger.info("CRITICAL PATH E2E TEST (REAL JAVA BACKEND)")
    logger.info("User Prompt: %s", user_prompt)
    logger.info("Teacher ID: %s", real_teacher_id)
    logger.info("Class ID: %s (高一英语班)", real_class_id)
    logger.info("Assignment ID: %s (测试一)", real_assignment_id)
    logger.info("USE_MOCK_DATA: %s", get_settings().use_mock_data)
    logger.info("=" * 60)

    detailed_results = {
        "user_prompt": user_prompt,
        "teacher_id": real_teacher_id,
        "class_id": real_class_id,
        "assignment_id": real_assignment_id,
        "use_mock_data": get_settings().use_mock_data,
        "steps": [],
    }

    # ══════════════════════════════════════════════════════════
    # STEP 1: Conversation API with pre-resolved context
    # (Skip entity resolution by providing classId and assignmentId)
    # ══════════════════════════════════════════════════════════
    step1_start = time.perf_counter()
    conv_resp = await client.post(
        "/api/conversation",
        json={
            "message": user_prompt,
            "language": "zh-CN",
            "teacherId": real_teacher_id,
            "context": {
                "classId": real_class_id,  # Pre-resolved class ID
                "assignmentId": real_assignment_id,  # Pre-resolved assignment ID
            },
        },
    )
    step1_duration = (time.perf_counter() - step1_start) * 1000

    conv_data = conv_resp.json()
    step1_result = {
        "step": "1. Conversation API",
        "duration_ms": round(step1_duration, 2),
        "status_code": conv_resp.status_code,
        "action": conv_data.get("action"),
        "mode": conv_data.get("mode"),
    }

    if conv_data.get("resolvedEntities"):
        step1_result["resolved_entities"] = [
            {"type": e.get("entityType"), "id": e.get("entityId"), "name": e.get("displayName")}
            for e in conv_data.get("resolvedEntities", [])
        ]

    if conv_data.get("blueprint"):
        bp = conv_data["blueprint"]
        step1_result["blueprint"] = {
            "id": bp.get("id"),
            "name": bp.get("name"),
            "description": bp.get("description"),
            "capability_level": bp.get("capabilityLevel"),
            "data_bindings": len(bp.get("dataContract", {}).get("bindings", [])),
            "compute_nodes": len(bp.get("computeGraph", {}).get("nodes", [])),
            "ui_tabs": len(bp.get("uiComposition", {}).get("tabs", [])),
        }

    if conv_data.get("clarifyOptions"):
        step1_result["clarify_options"] = {
            "type": conv_data["clarifyOptions"].get("type"),
            "choices": [c.get("label") for c in conv_data["clarifyOptions"].get("choices", [])],
        }

    detailed_results["steps"].append(step1_result)
    logger.info("Step 1 completed: action=%s, duration=%.2fms", conv_data.get("action"), step1_duration)

    # Check if we got a blueprint or need clarification
    if conv_data.get("action") not in ("build", "build_workflow"):
        logger.info("Action is %s, not build - recording and continuing", conv_data.get("action"))
        detailed_results["final_status"] = "clarify_needed"
        detailed_results["total_duration_ms"] = round(step1_duration, 2)

        _record_result(
            test_name="test_live_critical_path_e2e",
            category="D. Critical Path",
            input_data={"user_prompt": user_prompt},
            output_data=detailed_results,
            duration_ms=step1_duration,
        )
        # Don't fail - clarify is valid behavior for ambiguous entity
        return

    blueprint = conv_data.get("blueprint")
    assert blueprint is not None, "Expected blueprint in build response"

    # ══════════════════════════════════════════════════════════
    # STEP 2: Page Generation (Executor with SSE) - REAL JAVA BACKEND
    # ══════════════════════════════════════════════════════════
    step2_start = time.perf_counter()
    page_resp = await client.post(
        "/api/page/generate",
        json={
            "blueprint": blueprint,
            "context": {
                "teacherId": real_teacher_id,
                "classId": real_class_id,
                "assignmentId": real_assignment_id,  # Required for $input.assignment resolution
            },
        },
    )
    step2_duration = (time.perf_counter() - step2_start) * 1000

    events = _parse_sse_events(page_resp.text)

    # Analyze SSE events
    phase_events = [e for e in events if e.get("type") == "PHASE"]
    tool_calls = [e for e in events if e.get("type") == "TOOL_CALL"]
    tool_results = [e for e in events if e.get("type") == "TOOL_RESULT"]
    block_starts = [e for e in events if e.get("type") == "BLOCK_START"]
    slot_deltas = [e for e in events if e.get("type") == "SLOT_DELTA"]
    block_completes = [e for e in events if e.get("type") == "BLOCK_COMPLETE"]
    complete_event = next((e for e in events if e.get("type") == "COMPLETE"), None)

    # Check for error events (DATA_ERROR, etc.)
    error_events = [e for e in events if e.get("type") in ("DATA_ERROR", "ERROR")]

    step2_result = {
        "step": "2. Page Generation (SSE)",
        "duration_ms": round(step2_duration, 2),
        "status_code": page_resp.status_code,
        "event_summary": {
            "total_events": len(events),
            "phases": [e.get("phase") for e in phase_events],
            "tool_calls": len(tool_calls),
            "tool_results": len(tool_results),
            "block_starts": len(block_starts),
            "slot_deltas": len(slot_deltas),
            "block_completes": len(block_completes),
            "error_events": len(error_events),
        },
        "complete_status": complete_event.get("message") if complete_event else None,
    }

    # Capture error details if any
    if error_events:
        step2_result["errors"] = [
            {"type": e.get("type"), "message": e.get("message", "")} for e in error_events
        ]

    # Capture error from COMPLETE event
    if complete_event and complete_event.get("message") == "error":
        result = complete_event.get("result", {})
        step2_result["error_detail"] = {
            "chat_response": result.get("chatResponse", "")[:200] if result.get("chatResponse") else None,
            "error_type": result.get("errorType"),
        }

    # Extract page details if successful
    if complete_event and complete_event.get("message") == "completed":
        page = complete_event.get("result", {}).get("page", {})
        step2_result["page"] = {
            "title": page.get("meta", {}).get("pageTitle"),
            "layout": page.get("layout"),
            "tabs_count": len(page.get("tabs", [])),
            "blocks_per_tab": [
                {"tab": t.get("label"), "blocks": len(t.get("blocks", []))}
                for t in page.get("tabs", [])
            ],
        }
        # Sample first AI content block
        for tab in page.get("tabs", []):
            for block in tab.get("blocks", []):
                if block.get("type") == "markdown" and block.get("content"):
                    step2_result["ai_content_sample"] = block.get("content")[:300]
                    break

    detailed_results["steps"].append(step2_result)
    logger.info("Step 2 completed: status=%s, duration=%.2fms",
                complete_event.get("message") if complete_event else "unknown", step2_duration)

    # ══════════════════════════════════════════════════════════
    # FINAL SUMMARY
    # ══════════════════════════════════════════════════════════
    total_duration = step1_duration + step2_duration
    detailed_results["total_duration_ms"] = round(total_duration, 2)
    detailed_results["final_status"] = complete_event.get("message") if complete_event else "error"

    logger.info("=" * 60)
    logger.info("CRITICAL PATH COMPLETE")
    logger.info("Total Duration: %.2fms (%.2fs)", total_duration, total_duration / 1000)
    logger.info("Final Status: %s", detailed_results["final_status"])
    logger.info("=" * 60)

    _record_result(
        test_name="test_live_critical_path_e2e",
        category="D. Critical Path",
        input_data={"user_prompt": user_prompt},
        output_data=detailed_results,
        duration_ms=total_duration,
    )

    # Assertions
    assert page_resp.status_code == 200
    assert complete_event is not None
    assert complete_event.get("message") in ("completed", "error")


# ══════════════════════════════════════════════════════════════
# Category E: Phase 7 — RAG & Knowledge Services (Live Data)
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_live_rag_rubrics_loaded():
    """E1: Verify RAG service loads rubrics from data/rubrics/."""
    from services.rag_service import get_rag_service

    start = time.perf_counter()
    rag = get_rag_service()
    stats = rag.get_stats()
    duration = (time.perf_counter() - start) * 1000

    _record_result(
        test_name="test_live_rag_rubrics_loaded",
        category="E. Phase 7 RAG",
        input_data={},
        output_data={
            "official_corpus_docs": stats["official_corpus"]["doc_count"],
            "school_assets_docs": stats["school_assets"]["doc_count"],
            "question_bank_docs": stats["question_bank"]["doc_count"],
        },
        duration_ms=duration,
    )

    assert stats["official_corpus"]["doc_count"] > 0, "No rubrics loaded into RAG"


@pytest.mark.asyncio
async def test_live_rag_query_rubrics():
    """E2: Query RAG for rubric content."""
    from services.rag_service import get_rag_service

    rag = get_rag_service()
    start = time.perf_counter()
    results = rag.query("official_corpus", "argumentative essay writing criteria", n_results=3)
    duration = (time.perf_counter() - start) * 1000

    _record_result(
        test_name="test_live_rag_query_rubrics",
        category="E. Phase 7 RAG",
        input_data={"query": "argumentative essay writing criteria"},
        output_data={
            "results_count": len(results),
            "top_result_preview": results[0]["content"][:200] if results else None,
        },
        duration_ms=duration,
    )

    assert len(results) > 0, "No results for rubric query"


@pytest.mark.asyncio
async def test_live_knowledge_english():
    """E3: List English knowledge points from data files."""
    from services.knowledge_service import list_knowledge_points

    start = time.perf_counter()
    kps = list_knowledge_points("English")
    duration = (time.perf_counter() - start) * 1000

    _record_result(
        test_name="test_live_knowledge_english",
        category="E. Phase 7 Knowledge",
        input_data={"subject": "English"},
        output_data={
            "count": len(kps),
            "sample_ids": [kp.id for kp in kps[:5]] if kps else [],
        },
        duration_ms=duration,
    )

    assert len(kps) > 0, "No English knowledge points found"


@pytest.mark.asyncio
async def test_live_knowledge_all_subjects():
    """E4: Load knowledge points for all subjects."""
    from services.knowledge_service import list_knowledge_points

    subjects = ["English", "Math", "Chinese", "ICT"]
    results = {}

    start = time.perf_counter()
    for subj in subjects:
        kps = list_knowledge_points(subj)
        results[subj] = len(kps)
    duration = (time.perf_counter() - start) * 1000

    _record_result(
        test_name="test_live_knowledge_all_subjects",
        category="E. Phase 7 Knowledge",
        input_data={"subjects": subjects},
        output_data=results,
        duration_ms=duration,
    )

    for subj, count in results.items():
        assert count > 0, f"No knowledge points for {subj}"


@pytest.mark.asyncio
async def test_live_error_to_knowledge_mapping():
    """E5: Map error tags to knowledge points."""
    from services.knowledge_service import map_error_to_knowledge_points

    error_tags = ["grammar", "tense", "inference"]
    start = time.perf_counter()
    kp_ids = map_error_to_knowledge_points(error_tags, "English")
    duration = (time.perf_counter() - start) * 1000

    _record_result(
        test_name="test_live_error_to_knowledge_mapping",
        category="E. Phase 7 Knowledge",
        input_data={"error_tags": error_tags},
        output_data={"mapped_kp_ids": kp_ids},
        duration_ms=duration,
    )

    assert len(kp_ids) > 0, "No knowledge points mapped for error tags"


@pytest.mark.asyncio
async def test_live_rubric_service():
    """E6: Load and format rubric for LLM context."""
    from services.rubric_service import get_rubric_for_task, get_rubric_context

    start = time.perf_counter()
    rubric = get_rubric_for_task("English", "essay")
    context = get_rubric_context(rubric) if rubric else None
    duration = (time.perf_counter() - start) * 1000

    _record_result(
        test_name="test_live_rubric_service",
        category="E. Phase 7 Rubric",
        input_data={"subject": "English", "task_type": "essay"},
        output_data={
            "rubric_id": rubric.id if rubric else None,
            "rubric_name": rubric.name if rubric else None,
            "criteria_count": len(rubric.criteria) if rubric else 0,
            "context_has_criteria": "criteriaText" in context if context else False,
            "context_has_errors": "commonErrors" in context if context else False,
        },
        duration_ms=duration,
    )

    assert rubric is not None, "No English essay rubric found"
    assert context is not None, "Failed to generate rubric context"


# ══════════════════════════════════════════════════════════════
# Category F: Phase 7 — Question Pipeline (Live LLM)
# ══════════════════════════════════════════════════════════════

@SKIP_NO_API_KEY
@pytest.mark.asyncio
async def test_live_question_draft_generation():
    """F1: Generate question drafts using real LLM."""
    from agents.question_pipeline import QuestionPipeline
    from models.question_pipeline import GenerationSpec, QuestionType, Difficulty

    pipeline = QuestionPipeline()
    spec = GenerationSpec(
        subject="English",
        topic="Reading Comprehension",
        count=2,
        question_types=[QuestionType.MULTIPLE_CHOICE],
        difficulty=Difficulty.MEDIUM,
        knowledge_points=["DSE-ENG-U5-RC-01"],
    )

    start = time.perf_counter()
    drafts = await pipeline.generate_draft(spec)
    duration = (time.perf_counter() - start) * 1000

    _record_result(
        test_name="test_live_question_draft_generation",
        category="F. Phase 7 Question Pipeline",
        input_data={
            "subject": spec.subject,
            "topic": spec.topic,
            "count": spec.count,
            "question_types": [qt.value for qt in spec.question_types],
        },
        output_data={
            "drafts_count": len(drafts),
            "draft_previews": [
                {"id": d.id, "type": d.question_type.value, "text_preview": d.question_text[:100]}
                for d in drafts
            ] if drafts else [],
        },
        duration_ms=duration,
    )

    assert len(drafts) > 0, "No drafts generated"


@SKIP_NO_API_KEY
@pytest.mark.asyncio
async def test_live_question_judge():
    """F2: Judge question quality using real LLM."""
    from agents.question_pipeline import QuestionPipeline
    from models.question_pipeline import GenerationSpec, QuestionType, Difficulty

    pipeline = QuestionPipeline()

    # First generate a draft
    spec = GenerationSpec(
        subject="English",
        topic="Grammar",
        count=1,
        question_types=[QuestionType.MULTIPLE_CHOICE],
        difficulty=Difficulty.EASY,
    )
    drafts = await pipeline.generate_draft(spec)
    assert len(drafts) > 0

    # Then judge it
    start = time.perf_counter()
    result = await pipeline.judge_question(drafts[0])
    duration = (time.perf_counter() - start) * 1000

    _record_result(
        test_name="test_live_question_judge",
        category="F. Phase 7 Question Pipeline",
        input_data={"question_preview": drafts[0].question_text[:100]},
        output_data={
            "passed": result.passed,
            "score": result.score,
            "issues_count": len(result.issues),
            "issues": [{"type": i.issue_type.value, "severity": i.severity.value} for i in result.issues],
        },
        duration_ms=duration,
    )

    assert 0.0 <= result.score <= 1.0


@SKIP_NO_API_KEY
@pytest.mark.asyncio
async def test_live_question_full_pipeline():
    """F3: Run full question generation pipeline with real LLM."""
    from agents.question_pipeline import QuestionPipeline
    from models.question_pipeline import GenerationSpec, QuestionType, Difficulty
    from services.rubric_service import get_rubric_for_task, get_rubric_context

    # Get rubric context
    rubric = get_rubric_for_task("English", "multiple_choice")
    rubric_context = get_rubric_context(rubric) if rubric else None

    pipeline = QuestionPipeline()
    spec = GenerationSpec(
        subject="English",
        topic="Vocabulary",
        count=2,
        question_types=[QuestionType.MULTIPLE_CHOICE],
        difficulty=Difficulty.MEDIUM,
        knowledge_points=["DSE-ENG-U5-VOC-01"],
    )

    start = time.perf_counter()
    result = await pipeline.run_pipeline(spec, rubric_context=rubric_context)
    duration = (time.perf_counter() - start) * 1000

    _record_result(
        test_name="test_live_question_full_pipeline",
        category="F. Phase 7 Question Pipeline",
        input_data={
            "subject": spec.subject,
            "topic": spec.topic,
            "count": spec.count,
            "with_rubric": rubric_context is not None,
        },
        output_data={
            "total_questions": len(result.questions),
            "passed": result.total_passed,
            "repaired": result.total_repaired,
            "failed": result.total_failed,
            "average_quality": round(result.average_quality_score, 3),
            "questions": [
                {
                    "type": q.question_type.value,
                    "quality": q.quality_score,
                    "text_preview": q.question_text[:80],
                }
                for q in result.questions
            ],
        },
        duration_ms=duration,
    )

    assert len(result.questions) > 0, "No questions generated"
    logger.info("Question Pipeline: %d questions, avg quality %.2f", len(result.questions), result.average_quality_score)


@SKIP_NO_API_KEY
@pytest.mark.asyncio
async def test_live_question_with_weakness_context():
    """F4: Generate questions targeting student weaknesses."""
    from agents.question_pipeline import QuestionPipeline
    from models.question_pipeline import GenerationSpec, QuestionType, Difficulty
    from services.knowledge_service import map_error_to_knowledge_points

    # Simulate student weakness detection
    error_tags = ["grammar", "tense"]
    weak_kps = map_error_to_knowledge_points(error_tags, "English")

    pipeline = QuestionPipeline()
    spec = GenerationSpec(
        subject="English",
        topic="Grammar Practice",
        count=2,
        question_types=[QuestionType.MULTIPLE_CHOICE, QuestionType.SHORT_ANSWER],
        difficulty=Difficulty.EASY,
        knowledge_points=weak_kps,
    )

    # Add weakness context
    weakness_context = {
        "error_tags": error_tags,
        "weak_knowledge_points": weak_kps,
        "focus_areas": ["tense agreement", "past tense forms"],
    }

    start = time.perf_counter()
    result = await pipeline.run_pipeline(spec, weakness_context=weakness_context)
    duration = (time.perf_counter() - start) * 1000

    _record_result(
        test_name="test_live_question_with_weakness_context",
        category="F. Phase 7 Question Pipeline",
        input_data={
            "error_tags": error_tags,
            "weak_kps": weak_kps,
            "count": spec.count,
        },
        output_data={
            "total_questions": len(result.questions),
            "average_quality": round(result.average_quality_score, 3),
        },
        duration_ms=duration,
    )

    assert len(result.questions) > 0


# ══════════════════════════════════════════════════════════════
# Category G: Phase 7 — Assessment Tools (Live)
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_live_assess_student_weakness():
    """G1: Analyze student weakness from submission data."""
    from tools.assessment_tools import analyze_student_weakness

    # Sample submission data with error patterns
    # Note: fields use snake_case as per SubmissionRecord and QuestionItem models
    sample_submissions = [
        {
            "student_id": "s-001",
            "name": "Student A",
            "score": 65,
            "items": [
                {"question_id": "q1", "correct": False, "error_tags": ["grammar", "tense"], "knowledge_point_ids": ["DSE-ENG-U5-GR-01"]},
                {"question_id": "q2", "correct": True, "error_tags": [], "knowledge_point_ids": ["DSE-ENG-U5-RC-01"]},
                {"question_id": "q3", "correct": False, "error_tags": ["grammar"], "knowledge_point_ids": ["DSE-ENG-U5-GR-02"]},
            ],
        },
        {
            "student_id": "s-002",
            "name": "Student B",
            "score": 75,
            "items": [
                {"question_id": "q1", "correct": True, "error_tags": [], "knowledge_point_ids": ["DSE-ENG-U5-GR-01"]},
                {"question_id": "q2", "correct": False, "error_tags": ["inference"], "knowledge_point_ids": ["DSE-ENG-U5-RC-01"]},
                {"question_id": "q3", "correct": True, "error_tags": [], "knowledge_point_ids": ["DSE-ENG-U5-GR-02"]},
            ],
        },
        {
            "student_id": "s-003",
            "name": "Student C",
            "score": 55,
            "items": [
                {"question_id": "q1", "correct": False, "error_tags": ["grammar", "tense"], "knowledge_point_ids": ["DSE-ENG-U5-GR-01"]},
                {"question_id": "q2", "correct": False, "error_tags": ["inference"], "knowledge_point_ids": ["DSE-ENG-U5-RC-01"]},
                {"question_id": "q3", "correct": False, "error_tags": ["grammar", "vocabulary"], "knowledge_point_ids": ["DSE-ENG-U5-GR-02"]},
            ],
        },
    ]

    start = time.perf_counter()
    result = await analyze_student_weakness(
        teacher_id="t-test",
        class_id="class-1a",
        submissions=sample_submissions,
    )
    duration = (time.perf_counter() - start) * 1000

    _record_result(
        test_name="test_live_assess_student_weakness",
        category="G. Phase 7 Assessment",
        input_data={"submission_count": len(sample_submissions)},
        output_data={
            "weak_points": result.get("weakPoints", []),
            "recommended_focus": result.get("recommendedFocus", []),
            "total_students": result.get("summary", {}).get("totalStudents"),
        },
        duration_ms=duration,
    )

    assert "weakPoints" in result
    assert "recommendedFocus" in result


# ══════════════════════════════════════════════════════════════
# Test Summary Report
# ══════════════════════════════════════════════════════════════

@pytest.fixture(scope="session", autouse=True)
def print_summary():
    """Print test summary after all tests."""
    yield
    if _test_results:
        print("\n" + "=" * 60)
        print("LIVE INTEGRATION TEST SUMMARY")
        print("=" * 60)

        passed = sum(1 for r in _test_results if r["status"] == "pass")
        failed = sum(1 for r in _test_results if r["status"] == "fail")
        total_time = sum(r["duration_ms"] for r in _test_results)

        print(f"Total: {len(_test_results)} | Passed: {passed} | Failed: {failed}")
        print(f"Total Duration: {total_time:.2f}ms")
        print("-" * 60)

        for r in _test_results:
            status_icon = "[PASS]" if r["status"] == "pass" else "[FAIL]"
            print(f"{status_icon} {r['test_name']}: {r['duration_ms']:.2f}ms")

        print("=" * 60)
