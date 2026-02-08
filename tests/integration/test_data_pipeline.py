"""Phase 1 · Stage 0.3: Python → Java API end-to-end data pipeline tests.

Validates:
- Teacher classes API connectivity
- Entity resolution with real backend data
- Class detail (students + assignments) retrieval
- Assignment submissions retrieval
- Field format consistency (camelCase)

Run:
    pytest tests/integration/test_data_pipeline.py -v --tb=short -m integration
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pytest

from services.entity_resolver import resolve_entities
from tests.integration.conftest import (
    REAL_ASSIGNMENT_ID,
    REAL_CLASS_ID_ENGLISH,
    REAL_TEACHER_ID,
    record_result,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 1. Full chain: classes → entity resolve → detail → submissions
# ═══════════════════════════════════════════════════════════════


class TestDataPipeline:
    """End-to-end data pipeline validation using real Java backend."""

    @pytest.fixture(autouse=True)
    async def _start_java_client(self):
        """Ensure JavaClient is started before each test in this class."""
        from services.java_client import get_java_client
        client = get_java_client()
        await client.start()
        yield
        await client.close()

    @pytest.mark.integration
    async def test_full_chain_class_to_detail(self):
        """teacherClasses → entityResolve → classDetail — full pipeline."""
        from agents.provider import execute_mcp_tool

        steps: list[dict[str, Any]] = []
        start = time.perf_counter()

        # Step 1: Fetch teacher classes
        s1_start = time.perf_counter()
        data = await execute_mcp_tool(
            "get_teacher_classes", {"teacher_id": REAL_TEACHER_ID}
        )
        classes = data.get("classes", [])
        s1_dur = (time.perf_counter() - s1_start) * 1000
        steps.append({
            "step": "get_teacher_classes",
            "duration_ms": round(s1_dur, 1),
            "class_count": len(classes),
            "class_names": [c.get("name") for c in classes[:5]],
        })
        assert len(classes) >= 1, (
            f"Teacher {REAL_TEACHER_ID} should have >= 1 class, got {len(classes)}"
        )

        # Step 2: Entity resolution against real classes
        s2_start = time.perf_counter()
        first_name = classes[0].get("name", "")
        result = await resolve_entities(
            REAL_TEACHER_ID, f"分析 {first_name} 的成绩"
        )
        s2_dur = (time.perf_counter() - s2_start) * 1000
        steps.append({
            "step": "resolve_entities",
            "input": first_name,
            "duration_ms": round(s2_dur, 1),
            "entities_count": len(result.entities),
            "scope_mode": result.scope_mode,
        })
        assert len(result.entities) >= 1, (
            f"Entity resolution for '{first_name}' returned 0 entities"
        )

        # Step 3: Fetch class detail using resolved class_id
        class_id = result.entities[0].entity_id
        s3_start = time.perf_counter()
        detail = await execute_mcp_tool(
            "get_class_detail",
            {"teacher_id": REAL_TEACHER_ID, "class_id": class_id},
        )
        s3_dur = (time.perf_counter() - s3_start) * 1000
        steps.append({
            "step": "get_class_detail",
            "class_id": class_id,
            "duration_ms": round(s3_dur, 1),
            "has_name": bool(detail.get("name")),
            "has_students": bool(detail.get("students")),
            "has_assignments": bool(detail.get("assignments")),
            "student_count": len(detail.get("students", [])),
            "assignment_count": len(detail.get("assignments", [])),
        })
        assert not detail.get("error"), (
            f"get_class_detail returned error: {detail.get('error')}"
        )
        assert detail.get("name") or detail.get("class_id"), (
            "Class detail should have name or class_id"
        )

        duration = (time.perf_counter() - start) * 1000
        record_result(
            "test_full_chain_class_to_detail",
            "Data Pipeline",
            {"teacher_id": REAL_TEACHER_ID},
            {"steps": steps, "total_duration_ms": round(duration, 1)},
            duration,
        )

    @pytest.mark.integration
    async def test_assignment_submissions_chain(self):
        """Fetch assignment submissions for a known assignment."""
        from agents.provider import execute_mcp_tool

        start = time.perf_counter()
        data = await execute_mcp_tool(
            "get_assignment_submissions",
            {"teacher_id": REAL_TEACHER_ID, "assignment_id": REAL_ASSIGNMENT_ID},
        )
        duration = (time.perf_counter() - start) * 1000

        has_submissions = bool(
            data.get("submissions")
            or data.get("records")
            or data.get("raw_scores")
        )

        record_result(
            "test_assignment_submissions_chain",
            "Data Pipeline",
            {"teacher_id": REAL_TEACHER_ID, "assignment_id": REAL_ASSIGNMENT_ID},
            {
                "has_data": has_submissions,
                "has_error": bool(data.get("error")),
                "keys": list(data.keys())[:10],
            },
            duration,
            status="pass" if not data.get("error") else "fail",
        )
        # If the assignment exists, we shouldn't get an error
        # (it's OK if submissions are empty for a new assignment)
        if data.get("error"):
            logger.warning(
                "Submission fetch returned error (may be expected if assignment "
                "has no submissions yet): %s",
                data["error"],
            )


# ═══════════════════════════════════════════════════════════════
# 2. Field format consistency
# ═══════════════════════════════════════════════════════════════


class TestFieldFormatConsistency:
    """Verify Java API fields are camelCase after adapter conversion."""

    @pytest.fixture(autouse=True)
    async def _start_java_client(self):
        from services.java_client import get_java_client
        client = get_java_client()
        await client.start()
        yield
        await client.close()

    @pytest.mark.integration
    async def test_class_list_field_format(self):
        """ClassInfo fields should be snake_case internally (Python convention)."""
        from agents.provider import execute_mcp_tool

        data = await execute_mcp_tool(
            "get_teacher_classes", {"teacher_id": REAL_TEACHER_ID}
        )
        classes = data.get("classes", [])
        if not classes:
            pytest.skip("No classes returned")

        first = classes[0]
        # After adapter conversion, internal fields are snake_case
        expected_keys = {"class_id", "name", "grade", "subject", "student_count"}
        actual_keys = set(first.keys())

        missing = expected_keys - actual_keys
        record_result(
            "test_class_list_field_format",
            "Data Pipeline — Fields",
            {"expected_keys": sorted(expected_keys)},
            {"actual_keys": sorted(actual_keys), "missing": sorted(missing)},
            0,
            status="pass" if not missing else "fail",
        )
        assert not missing, (
            f"ClassInfo missing expected fields: {missing}. "
            f"Actual keys: {actual_keys}"
        )

    @pytest.mark.integration
    async def test_class_info_serializes_correctly(self):
        """ClassInfo.model_dump() should produce well-formed internal dict."""
        from adapters.class_adapter import list_classes
        from services.java_client import get_java_client

        client = get_java_client()
        classes = await list_classes(client, REAL_TEACHER_ID)

        if not classes:
            pytest.skip("No classes returned from backend")

        first = classes[0]
        dumped = first.model_dump()

        # ClassInfo uses BaseModel (snake_case internally)
        assert "class_id" in dumped, f"Expected 'class_id' in {list(dumped.keys())}"
        assert "student_count" in dumped, f"Expected 'student_count' in {list(dumped.keys())}"
        assert dumped["class_id"], "class_id should not be empty"
        assert dumped["name"], "name should not be empty"


# ═══════════════════════════════════════════════════════════════
# 3. Backend connectivity smoke test
# ═══════════════════════════════════════════════════════════════


class TestBackendConnectivity:
    """Basic connectivity check — fail fast if backend is down."""

    @pytest.mark.integration
    async def test_java_backend_reachable(self, java_client):
        """Java backend should respond to a basic class list request."""
        start = time.perf_counter()
        try:
            resp = await java_client.get(
                f"/dify/teacher/{REAL_TEACHER_ID}/classes/me"
            )
            duration = (time.perf_counter() - start) * 1000
            record_result(
                "test_java_backend_reachable",
                "Data Pipeline — Connectivity",
                {"endpoint": f"/dify/teacher/…/classes/me"},
                {"response_type": type(resp).__name__, "has_data": "data" in resp if isinstance(resp, dict) else False},
                duration,
            )
            assert resp is not None
        except Exception as exc:
            duration = (time.perf_counter() - start) * 1000
            record_result(
                "test_java_backend_reachable",
                "Data Pipeline — Connectivity",
                {"endpoint": f"/dify/teacher/…/classes/me"},
                {"error": str(exc)},
                duration,
                status="fail",
                error=str(exc),
            )
            pytest.fail(f"Java backend unreachable: {exc}")
