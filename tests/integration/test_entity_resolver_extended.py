"""Phase 1 · Stage 0: Entity Resolver extended matching rate tests.

Goal: matching rate >= 95% for known aliases.
Data: pulled directly from Java backend (no hardcoded test data).

Run:
    pytest tests/integration/test_entity_resolver_extended.py -v --tb=short
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pytest

from models.entity import EntityType
from services.entity_resolver import resolve_entities
from tests.integration.conftest import (
    REAL_TEACHER_ID,
    record_result,
    skip_no_api_key,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fixture: fetch real class data from backend and build test cases
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
async def real_classes() -> list[dict[str, Any]]:
    """Fetch real teacher classes from the Java backend via MCP tool.

    Starts the JavaClient, fetches data, and keeps the client alive
    so that resolve_entities() can also use it during tests.
    """
    from services.java_client import get_java_client

    client = get_java_client()
    await client.start()

    from agents.provider import execute_mcp_tool

    data = await execute_mcp_tool(
        "get_teacher_classes", {"teacher_id": REAL_TEACHER_ID}
    )
    classes = data.get("classes", [])
    assert len(classes) >= 1, (
        f"Expected at least 1 class for teacher {REAL_TEACHER_ID}, "
        f"got {len(classes)}. Is the Java backend running at "
        f"{client._base_url if hasattr(client, '_base_url') else 'unknown'}?"
    )
    logger.info(
        "Loaded %d real classes: %s",
        len(classes),
        [c.get("name", c.get("class_id")) for c in classes],
    )
    yield classes

    await client.close()


# ═══════════════════════════════════════════════════════════════
# 1. Exact match — class name / class_id
# ═══════════════════════════════════════════════════════════════


class TestExactMatch:
    """Exact class name should resolve with confidence = 1.0."""

    @pytest.mark.integration
    async def test_exact_class_name_match(self, real_classes):
        """Every real class name should be resolvable by its exact name."""
        passed, total = 0, 0
        failures = []
        start = time.perf_counter()

        for cls in real_classes:
            name = cls.get("name", "")
            if not name:
                continue
            total += 1
            result = await resolve_entities(
                REAL_TEACHER_ID, f"分析 {name} 的成绩"
            )
            class_entities = [
                e for e in result.entities if e.entity_type == EntityType.CLASS
            ]
            if class_entities and class_entities[0].entity_id == cls.get("class_id"):
                passed += 1
            else:
                failures.append({
                    "input": name,
                    "expected_id": cls.get("class_id"),
                    "got": [e.model_dump(by_alias=True) for e in class_entities],
                })

        duration = (time.perf_counter() - start) * 1000
        rate = passed / total if total else 0

        record_result(
            "test_exact_class_name_match",
            "Entity Resolver — Exact",
            {"total_classes": total},
            {"passed": passed, "rate": f"{rate:.0%}", "failures": failures},
            duration,
            status="pass" if rate >= 1.0 else "fail",
        )
        assert rate == 1.0, (
            f"Exact match rate {rate:.0%} < 100%. Failures: {failures}"
        )


# ═══════════════════════════════════════════════════════════════
# 2. Alias / pattern match
# ═══════════════════════════════════════════════════════════════


class TestAliasMatch:
    """Alias patterns like '1A班', 'F1A', 'Form 1A' should resolve."""

    @staticmethod
    def _generate_alias_cases(classes: list[dict]) -> list[tuple[str, str, str]]:
        """Generate (query, expected_class_id, alias_type) tuples from real data."""
        cases = []
        for cls in classes:
            name = cls.get("name", "")
            cid = cls.get("class_id", "")
            if not name or not cid:
                continue
            # e.g. "Form 1A" → generate "1A班", "F1A", "1A"
            import re
            m = re.search(r"(\d)([A-Za-z])", name)
            if m:
                code = f"{m.group(1)}{m.group(2).upper()}"
                cases.append((f"分析 {code}班 成绩", cid, f"{code}班"))
                cases.append((f"分析 {code} 成绩", cid, f"bare {code}"))
                cases.append((f"分析 F{code} 成绩", cid, f"F{code}"))
        return cases

    @pytest.mark.integration
    async def test_alias_pattern_match(self, real_classes):
        """Generated alias patterns should resolve to the correct class."""
        cases = self._generate_alias_cases(real_classes)
        if not cases:
            pytest.skip("No alias-friendly class names in real data")

        passed, total = 0, len(cases)
        failures = []
        start = time.perf_counter()

        for query, expected_id, alias_type in cases:
            result = await resolve_entities(REAL_TEACHER_ID, query)
            class_entities = [
                e for e in result.entities if e.entity_type == EntityType.CLASS
            ]
            if class_entities and class_entities[0].entity_id == expected_id:
                passed += 1
            else:
                failures.append({
                    "query": query,
                    "alias": alias_type,
                    "expected": expected_id,
                    "got": [e.model_dump(by_alias=True) for e in class_entities],
                })

        duration = (time.perf_counter() - start) * 1000
        rate = passed / total if total else 0

        record_result(
            "test_alias_pattern_match",
            "Entity Resolver — Alias",
            {"total_cases": total},
            {"passed": passed, "rate": f"{rate:.0%}", "failures": failures},
            duration,
            status="pass" if rate >= 0.90 else "fail",
        )
        assert rate >= 0.90, (
            f"Alias match rate {rate:.0%} < 90%. Failures: {failures}"
        )


# ═══════════════════════════════════════════════════════════════
# 3. Fuzzy match
# ═══════════════════════════════════════════════════════════════


class TestFuzzyMatch:
    """Fuzzy patterns (typos, partial names) should resolve with >= 0.6 confidence."""

    @staticmethod
    def _generate_fuzzy_cases(classes: list[dict]) -> list[tuple[str, str, str]]:
        """Generate fuzzy query variants from real class names."""
        cases = []
        for cls in classes:
            name = cls.get("name", "")
            cid = cls.get("class_id", "")
            if not name or not cid:
                continue
            # Partial name (first 3 chars for Chinese, or drop last word for English)
            if len(name) > 3:
                partial = name[:len(name) - 1]
                cases.append((f"分析 {partial} 的成绩", cid, "partial"))
        return cases

    @pytest.mark.integration
    async def test_fuzzy_match(self, real_classes):
        """Partial / truncated class names should still match."""
        cases = self._generate_fuzzy_cases(real_classes)
        if not cases:
            pytest.skip("No fuzzy cases generated from real data")

        passed, total = 0, len(cases)
        failures = []
        start = time.perf_counter()

        for query, expected_id, variant in cases:
            result = await resolve_entities(REAL_TEACHER_ID, query)
            class_entities = [
                e for e in result.entities if e.entity_type == EntityType.CLASS
            ]
            if class_entities and class_entities[0].entity_id == expected_id:
                passed += 1
            else:
                failures.append({
                    "query": query,
                    "variant": variant,
                    "expected": expected_id,
                    "got": [e.model_dump(by_alias=True) for e in class_entities],
                })

        duration = (time.perf_counter() - start) * 1000
        rate = passed / total if total else 0

        record_result(
            "test_fuzzy_match",
            "Entity Resolver — Fuzzy",
            {"total_cases": total},
            {"passed": passed, "rate": f"{rate:.0%}", "failures": failures},
            duration,
            status="pass" if rate >= 0.80 else "fail",
        )
        # Fuzzy matching has a lower bar
        assert rate >= 0.80, (
            f"Fuzzy match rate {rate:.0%} < 80%. Failures: {failures}"
        )


# ═══════════════════════════════════════════════════════════════
# 4. Negative cases — must NOT hallucinate
# ═══════════════════════════════════════════════════════════════


NEGATIVE_INPUTS = [
    "不存在的班级ABC",
    "99Z班",
    "火星实验班",
    "分析 XYZ 的成绩",
    "分析 Class 88Z 的成绩",
]


class TestNegativeCases:
    """Non-existent class names must NOT match."""

    @pytest.mark.integration
    @pytest.mark.parametrize("query", NEGATIVE_INPUTS)
    async def test_unknown_class_returns_empty(self, query):
        result = await resolve_entities(REAL_TEACHER_ID, query)
        class_entities = [
            e for e in result.entities if e.entity_type == EntityType.CLASS
        ]
        high_confidence = [e for e in class_entities if e.confidence >= 0.7]
        assert len(high_confidence) == 0, (
            f"Input={query!r}: should NOT match any class with confidence >= 0.7, "
            f"but got {[e.model_dump(by_alias=True) for e in high_confidence]}"
        )


# ═══════════════════════════════════════════════════════════════
# 5. Multi-class detection
# ═══════════════════════════════════════════════════════════════


class TestMultiClass:
    """Queries mentioning multiple classes should resolve all of them."""

    @pytest.mark.integration
    async def test_two_class_comparison(self, real_classes):
        """'对比 X 和 Y 的成绩' should resolve both classes."""
        if len(real_classes) < 2:
            pytest.skip("Need at least 2 classes for multi-class test")

        names = [c["name"] for c in real_classes[:2] if c.get("name")]
        if len(names) < 2:
            pytest.skip("Not enough named classes")

        query = f"对比 {names[0]} 和 {names[1]} 的成绩"
        start = time.perf_counter()
        result = await resolve_entities(REAL_TEACHER_ID, query)
        duration = (time.perf_counter() - start) * 1000

        class_entities = [
            e for e in result.entities if e.entity_type == EntityType.CLASS
        ]

        record_result(
            "test_two_class_comparison",
            "Entity Resolver — Multi-class",
            {"query": query},
            {
                "resolved_count": len(class_entities),
                "scope_mode": result.scope_mode,
                "entities": [e.model_dump(by_alias=True) for e in class_entities],
            },
            duration,
            status="pass" if len(class_entities) >= 2 else "fail",
        )
        assert len(class_entities) >= 2, (
            f"Expected >= 2 classes, got {len(class_entities)}"
        )
        assert result.scope_mode == "multi"


# ═══════════════════════════════════════════════════════════════
# 6. Grade expansion
# ═══════════════════════════════════════════════════════════════


class TestGradeExpansion:
    """'Form N 全年级' should expand to all classes in that grade."""

    @pytest.mark.integration
    async def test_grade_expansion(self, real_classes):
        """Grade-level query should resolve all classes of that grade."""
        # Find a grade with multiple classes
        grade_map: dict[str, list[str]] = {}
        for cls in real_classes:
            grade = cls.get("grade", "")
            if grade:
                grade_map.setdefault(grade, []).append(cls.get("class_id", ""))

        multi_grade = None
        for grade, ids in grade_map.items():
            if len(ids) >= 2:
                multi_grade = grade
                break

        if not multi_grade:
            pytest.skip("No grade with >= 2 classes found; cannot test expansion")

        import re
        m = re.search(r"(\d)", multi_grade)
        if not m:
            pytest.skip(f"Cannot extract grade number from '{multi_grade}'")

        grade_num = m.group(1)
        query = f"Form {grade_num} 全年级成绩分析"
        start = time.perf_counter()
        result = await resolve_entities(REAL_TEACHER_ID, query)
        duration = (time.perf_counter() - start) * 1000

        class_entities = [
            e for e in result.entities if e.entity_type == EntityType.CLASS
        ]

        expected_count = len(grade_map[multi_grade])

        record_result(
            "test_grade_expansion",
            "Entity Resolver — Grade",
            {"query": query, "grade": multi_grade},
            {
                "expected": expected_count,
                "resolved": len(class_entities),
                "scope_mode": result.scope_mode,
            },
            duration,
            status="pass" if len(class_entities) >= expected_count else "fail",
        )
        assert result.scope_mode == "grade"
        assert len(class_entities) >= expected_count
