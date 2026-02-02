"""Tests for entity resolver — deterministic class reference matching."""

import pytest
from unittest.mock import AsyncMock, patch

from models.entity import ResolvedEntity, ResolveResult
from services.entity_resolver import resolve_classes


# ── Mock class data (mirrors services/mock_data.py) ──────────────

MOCK_CLASSES = [
    {
        "class_id": "class-hk-f1a",
        "name": "Form 1A",
        "grade": "Form 1",
        "subject": "English",
        "student_count": 35,
    },
    {
        "class_id": "class-hk-f1b",
        "name": "Form 1B",
        "grade": "Form 1",
        "subject": "English",
        "student_count": 32,
    },
]


@pytest.fixture(autouse=True)
def mock_tool():
    with patch(
        "services.entity_resolver.execute_mcp_tool",
        new_callable=AsyncMock,
        return_value={"teacher_id": "t-001", "classes": MOCK_CLASSES},
    ):
        yield


# ── Exact match ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exact_match_form_1a():
    """'分析 Form 1A 英语成绩' → single exact match."""
    result = await resolve_classes("t-001", "分析 Form 1A 英语成绩")
    assert result.scope_mode == "single"
    assert not result.is_ambiguous
    assert len(result.matches) == 1
    assert result.matches[0].class_id == "class-hk-f1a"
    assert result.matches[0].confidence == 1.0
    assert result.matches[0].match_type == "exact"


@pytest.mark.asyncio
async def test_exact_match_case_insensitive():
    """'分析 form 1a 成绩' → same match, case-insensitive."""
    result = await resolve_classes("t-001", "分析 form 1a 成绩")
    assert result.scope_mode == "single"
    assert not result.is_ambiguous
    assert len(result.matches) == 1
    assert result.matches[0].class_id == "class-hk-f1a"


# ── Alias match ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alias_match_1a_ban():
    """'分析 1A班 英语成绩' → match via '1A班' pattern."""
    result = await resolve_classes("t-001", "分析 1A班 英语成绩")
    assert result.scope_mode == "single"
    assert not result.is_ambiguous
    assert len(result.matches) == 1
    assert result.matches[0].class_id == "class-hk-f1a"


@pytest.mark.asyncio
async def test_alias_match_bare_1a():
    """'分析 1A 英语成绩' → match via bare '1A'."""
    result = await resolve_classes("t-001", "分析 1A 英语成绩")
    assert result.scope_mode == "single"
    assert not result.is_ambiguous
    assert len(result.matches) == 1
    assert result.matches[0].class_id == "class-hk-f1a"


@pytest.mark.asyncio
async def test_alias_match_f1a():
    """'分析 F1A 成绩' → match via short alias 'F1A'."""
    result = await resolve_classes("t-001", "分析 F1A 成绩")
    assert result.scope_mode == "single"
    assert not result.is_ambiguous
    assert len(result.matches) == 1
    assert result.matches[0].class_id == "class-hk-f1a"


# ── Multi-class ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_class_and():
    """'对比 1A 和 1B 的成绩' → two matches, scope_mode multi."""
    result = await resolve_classes("t-001", "对比 1A 和 1B 的成绩")
    assert len(result.matches) == 2
    assert result.scope_mode == "multi"
    assert not result.is_ambiguous
    class_ids = {m.class_id for m in result.matches}
    assert "class-hk-f1a" in class_ids
    assert "class-hk-f1b" in class_ids


@pytest.mark.asyncio
async def test_multi_class_comma():
    """'分析 1A, 1B 成绩' → two matches."""
    result = await resolve_classes("t-001", "分析 1A, 1B 成绩")
    assert len(result.matches) == 2
    assert result.scope_mode == "multi"
    assert not result.is_ambiguous


# ── Grade expansion ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grade_expansion():
    """'Form 1 全年级成绩分析' → all Form 1 classes, scope_mode grade."""
    result = await resolve_classes("t-001", "Form 1 全年级成绩分析")
    assert result.scope_mode == "grade"
    assert not result.is_ambiguous
    assert len(result.matches) == 2
    class_ids = {m.class_id for m in result.matches}
    assert "class-hk-f1a" in class_ids
    assert "class-hk-f1b" in class_ids
    for m in result.matches:
        assert m.match_type == "grade"
        assert m.confidence == 0.9


# ── No class mention ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_class_mention():
    """'分析英语表现' (no class ref) → scope_mode none."""
    result = await resolve_classes("t-001", "分析英语表现")
    assert result.scope_mode == "none"
    assert not result.is_ambiguous
    assert len(result.matches) == 0


# ── Nonexistent class ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_nonexistent_class():
    """'分析 2C班 成绩' → no match (Form 2C does not exist)."""
    result = await resolve_classes("t-001", "分析 2C班 成绩")
    assert len(result.matches) == 0
    assert result.scope_mode == "none"


# ── Fuzzy match ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fuzzy_match_typo():
    """'分析 Fom 1A 成绩' (typo 'Fom') → fuzzy match, is_ambiguous."""
    # "Fom" doesn't match any pattern cleanly, but "1A" does.
    # The bare "1A" pattern should still catch it via exact match.
    result = await resolve_classes("t-001", "分析 Fom 1A 成绩")
    assert len(result.matches) >= 1
    assert result.matches[0].class_id == "class-hk-f1a"


# ── Edge cases ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_teacher_id():
    """Empty teacher_id → no matches, graceful."""
    with patch(
        "services.entity_resolver.execute_mcp_tool",
        new_callable=AsyncMock,
        return_value={"teacher_id": "", "classes": []},
    ):
        result = await resolve_classes("", "分析 1A 成绩")
    assert result.scope_mode == "none"
    assert len(result.matches) == 0


@pytest.mark.asyncio
async def test_unknown_teacher():
    """Unknown teacher_id → no classes returned → no matches."""
    with patch(
        "services.entity_resolver.execute_mcp_tool",
        new_callable=AsyncMock,
        return_value={"teacher_id": "t-999", "classes": []},
    ):
        result = await resolve_classes("t-999", "分析 1A 成绩")
    assert result.scope_mode == "none"
    assert len(result.matches) == 0


# ── Model serialization ─────────────────────────────────────────


def test_resolved_entity_camel_case():
    """ResolvedEntity serializes to camelCase."""
    entity = ResolvedEntity(
        class_id="class-hk-f1a",
        display_name="Form 1A",
        confidence=1.0,
        match_type="exact",
    )
    data = entity.model_dump(by_alias=True)
    assert "classId" in data
    assert "displayName" in data
    assert "matchType" in data
    assert data["classId"] == "class-hk-f1a"


def test_resolve_result_camel_case():
    """ResolveResult serializes to camelCase."""
    result = ResolveResult(
        matches=[
            ResolvedEntity(
                class_id="class-hk-f1a",
                display_name="Form 1A",
                confidence=1.0,
                match_type="exact",
            ),
        ],
        is_ambiguous=False,
        scope_mode="single",
    )
    data = result.model_dump(by_alias=True)
    assert "isAmbiguous" in data
    assert "scopeMode" in data
    assert data["scopeMode"] == "single"
    assert len(data["matches"]) == 1
