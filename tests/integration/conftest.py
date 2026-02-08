"""Shared fixtures for Phase 1–3 integration tests.

Provides:
- skip_no_api_key: auto-skip when no LLM API key is configured
- java_client: started JavaClient instance for backend calls
- client: async HTTP client bound to the FastAPI app (ASGI transport)
- test_results: session-scoped collector for structured test reports
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from config.settings import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Real backend teacher / class IDs
# ---------------------------------------------------------------------------

REAL_TEACHER_ID = "ad09ddd5-d688-4409-9b1b-e418d80ef5cf"  # teacher1@insight.com (id=3)
REAL_CLASS_ID_MATH = "1167ccd0-12e9-4523-9e30-d45bd80fc2ce"  # 高一数学班
REAL_CLASS_ID_ENGLISH = "fa0279f1-e53d-417c-8830-dc536362c177"  # 高一英语班
REAL_CLASS_ID_CHINESE = "7178887b-f529-45c5-a5b2-38c57ef355ab"  # 高三语文班
REAL_ASSIGNMENT_ID = "assign-201436ca-ced8-4d82-b4eb-481d0b35979c"  # 数学小测验 (5 submissions)


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

def _has_llm_api_key() -> bool:
    settings = get_settings()
    return bool(
        settings.dashscope_api_key
        or settings.openai_api_key
        or settings.anthropic_api_key
        or getattr(settings, "zai_api_key", "")
    )


skip_no_api_key = pytest.mark.skipif(
    not _has_llm_api_key(),
    reason="No LLM API key configured in .env",
)


# ---------------------------------------------------------------------------
# Test result collector
# ---------------------------------------------------------------------------

_test_results: list[dict[str, Any]] = []


def record_result(
    test_name: str,
    category: str,
    input_data: Any,
    output_data: Any,
    duration_ms: float,
    status: str = "pass",
    error: str | None = None,
):
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


@pytest.fixture(scope="session", autouse=True)
def save_integration_results():
    """Persist integration test results to JSON after the session ends."""
    yield
    if _test_results:
        out = Path("docs/testing")
        out.mkdir(parents=True, exist_ok=True)
        path = out / "phase1-integration-results.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_test_results, f, indent=2, ensure_ascii=False)
        logger.info("Phase 1 results saved to %s (%d entries)", path, len(_test_results))

        # Print summary
        passed = sum(1 for r in _test_results if r["status"] == "pass")
        failed = sum(1 for r in _test_results if r["status"] == "fail")
        total_ms = sum(r["duration_ms"] for r in _test_results)
        print(f"\n{'=' * 60}")
        print(f"PHASE 1 INTEGRATION TEST SUMMARY")
        print(f"{'=' * 60}")
        print(f"Total: {len(_test_results)} | Passed: {passed} | Failed: {failed}")
        print(f"Total Duration: {total_ms:.0f}ms")
        print(f"{'-' * 60}")
        for r in _test_results:
            icon = "PASS" if r["status"] == "pass" else "FAIL"
            print(f"  [{icon}] {r['test_name']}: {r['duration_ms']:.0f}ms")
        print(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# Java client fixture
# ---------------------------------------------------------------------------

@pytest.fixture
async def java_client():
    """Provide a started JavaClient that connects to the real backend."""
    from services.java_client import get_java_client

    jc = get_java_client()
    await jc.start()
    yield jc
    await jc.close()


# ---------------------------------------------------------------------------
# ASGI HTTP client fixture
# ---------------------------------------------------------------------------

@pytest.fixture
async def client():
    """Async HTTP client for API-level tests."""
    from main import app
    from services.java_client import get_java_client

    jc = get_java_client()
    await jc.start()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await jc.close()
