"""Tests for entity resolver — general-purpose entity reference matching."""

import pytest
from unittest.mock import AsyncMock, patch

from models.entity import EntityType, ResolvedEntity, ResolveResult
from services.entity_resolver import resolve_entities, resolve_classes


# ── Mock data ──────────────────────────────────────────────────

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

MOCK_CLASS_DETAIL_F1A = {
    "class_id": "class-hk-f1a",
    "name": "Form 1A",
    "grade": "Form 1",
    "subject": "English",
    "student_count": 35,
    "students": [
        {"student_id": "s-001", "name": "Wong Ka Ho", "number": 1},
        {"student_id": "s-002", "name": "Li Mei", "number": 2},
        {"student_id": "s-003", "name": "Chan Tai Man", "number": 3},
    ],
    "assignments": [
        {"assignment_id": "a-001", "title": "Unit 5 Test", "type": "exam", "max_score": 100},
        {"assignment_id": "a-002", "title": "Essay Writing", "type": "homework", "max_score": 50},
    ],
}


async def _mock_execute_tool(name: str, args: dict):
    """Route mock tool calls to appropriate mock data."""
    if name == "get_teacher_classes":
        return {"teacher_id": args.get("teacher_id", ""), "classes": MOCK_CLASSES}
    if name == "get_class_detail":
        class_id = args.get("class_id", "")
        if class_id == "class-hk-f1a":
            return MOCK_CLASS_DETAIL_F1A
        return {"error": f"Class {class_id} not found"}
    return {}


@pytest.fixture(autouse=True)
def mock_tool():
    with patch(
        "services.entity_resolver.execute_mcp_tool",
        new_callable=AsyncMock,
        side_effect=_mock_execute_tool,
    ):
        yield


# ═══════════════════════════════════════════════════════════════
# CLASS RESOLUTION (preserved from original tests)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_exact_match_form_1a():
    """'分析 Form 1A 英语成绩' → single exact match."""
    result = await resolve_entities("t-001", "分析 Form 1A 英语成绩")
    assert result.scope_mode == "single"
    assert not result.is_ambiguous
    assert len(result.entities) == 1
    assert result.entities[0].entity_id == "class-hk-f1a"
    assert result.entities[0].entity_type == EntityType.CLASS
    assert result.entities[0].confidence == 1.0
    assert result.entities[0].match_type == "exact"


@pytest.mark.asyncio
async def test_exact_match_case_insensitive():
    """'分析 form 1a 成绩' → same match, case-insensitive."""
    result = await resolve_entities("t-001", "分析 form 1a 成绩")
    assert result.scope_mode == "single"
    assert not result.is_ambiguous
    assert len(result.entities) == 1
    assert result.entities[0].entity_id == "class-hk-f1a"


@pytest.mark.asyncio
async def test_alias_match_1a_ban():
    """'分析 1A班 英语成绩' → match via '1A班' pattern."""
    result = await resolve_entities("t-001", "分析 1A班 英语成绩")
    assert result.scope_mode == "single"
    assert not result.is_ambiguous
    assert len(result.entities) == 1
    assert result.entities[0].entity_id == "class-hk-f1a"


@pytest.mark.asyncio
async def test_alias_match_bare_1a():
    """'分析 1A 英语成绩' → match via bare '1A'."""
    result = await resolve_entities("t-001", "分析 1A 英语成绩")
    assert result.scope_mode == "single"
    assert not result.is_ambiguous
    assert len(result.entities) == 1
    assert result.entities[0].entity_id == "class-hk-f1a"


@pytest.mark.asyncio
async def test_alias_match_f1a():
    """'分析 F1A 成绩' → match via short alias 'F1A'."""
    result = await resolve_entities("t-001", "分析 F1A 成绩")
    assert result.scope_mode == "single"
    assert not result.is_ambiguous
    assert len(result.entities) == 1
    assert result.entities[0].entity_id == "class-hk-f1a"


@pytest.mark.asyncio
async def test_multi_class_and():
    """'对比 1A 和 1B 的成绩' → two matches, scope_mode multi."""
    result = await resolve_entities("t-001", "对比 1A 和 1B 的成绩")
    assert len(result.entities) == 2
    assert result.scope_mode == "multi"
    assert not result.is_ambiguous
    entity_ids = {m.entity_id for m in result.entities}
    assert "class-hk-f1a" in entity_ids
    assert "class-hk-f1b" in entity_ids


@pytest.mark.asyncio
async def test_multi_class_comma():
    """'分析 1A, 1B 成绩' → two matches."""
    result = await resolve_entities("t-001", "分析 1A, 1B 成绩")
    assert len(result.entities) == 2
    assert result.scope_mode == "multi"
    assert not result.is_ambiguous


@pytest.mark.asyncio
async def test_grade_expansion():
    """'Form 1 全年级成绩分析' → all Form 1 classes, scope_mode grade."""
    result = await resolve_entities("t-001", "Form 1 全年级成绩分析")
    assert result.scope_mode == "grade"
    assert not result.is_ambiguous
    assert len(result.entities) == 2
    entity_ids = {m.entity_id for m in result.entities}
    assert "class-hk-f1a" in entity_ids
    assert "class-hk-f1b" in entity_ids
    for m in result.entities:
        assert m.entity_type == EntityType.CLASS
        assert m.match_type == "grade"
        assert m.confidence == 0.9


@pytest.mark.asyncio
async def test_no_class_mention():
    """'分析英语表现' (no entity ref) → scope_mode none."""
    result = await resolve_entities("t-001", "分析英语表现")
    assert result.scope_mode == "none"
    assert not result.is_ambiguous
    assert len(result.entities) == 0


@pytest.mark.asyncio
async def test_nonexistent_class():
    """'分析 2C班 成绩' → no match (Form 2C does not exist)."""
    result = await resolve_entities("t-001", "分析 2C班 成绩")
    assert len(result.entities) == 0
    assert result.scope_mode == "none"


@pytest.mark.asyncio
async def test_fuzzy_match_typo():
    """'分析 Fom 1A 成绩' (typo 'Fom') → bare '1A' pattern catches it."""
    result = await resolve_entities("t-001", "分析 Fom 1A 成绩")
    assert len(result.entities) >= 1
    assert result.entities[0].entity_id == "class-hk-f1a"


@pytest.mark.asyncio
async def test_empty_teacher_id():
    """Empty teacher_id → no matches, graceful."""
    with patch(
        "services.entity_resolver.execute_mcp_tool",
        new_callable=AsyncMock,
        return_value={"teacher_id": "", "classes": []},
    ):
        result = await resolve_entities("", "分析 1A 成绩")
    assert result.scope_mode == "none"
    assert len(result.entities) == 0


@pytest.mark.asyncio
async def test_unknown_teacher():
    """Unknown teacher_id → no classes returned → no matches."""
    with patch(
        "services.entity_resolver.execute_mcp_tool",
        new_callable=AsyncMock,
        return_value={"teacher_id": "t-999", "classes": []},
    ):
        result = await resolve_entities("t-999", "分析 1A 成绩")
    assert result.scope_mode == "none"
    assert len(result.entities) == 0


# ═══════════════════════════════════════════════════════════════
# STUDENT RESOLUTION
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_student_exact_match_with_class():
    """'分析 1A 班学生 Wong Ka Ho 的成绩' → class + student resolved."""
    result = await resolve_entities("t-001", "分析 1A 班学生 Wong Ka Ho 的成绩")
    class_entities = [e for e in result.entities if e.entity_type == EntityType.CLASS]
    student_entities = [e for e in result.entities if e.entity_type == EntityType.STUDENT]
    assert len(class_entities) == 1
    assert class_entities[0].entity_id == "class-hk-f1a"
    assert len(student_entities) == 1
    assert student_entities[0].entity_id == "s-001"
    assert student_entities[0].display_name == "Wong Ka Ho"
    assert student_entities[0].confidence == 1.0
    assert student_entities[0].match_type == "exact"


@pytest.mark.asyncio
async def test_student_with_context_classid():
    """Student mentioned with classId in context → resolves student."""
    result = await resolve_entities(
        "t-001",
        "分析学生 Li Mei 的成绩",
        context={"classId": "class-hk-f1a"},
    )
    student_entities = [e for e in result.entities if e.entity_type == EntityType.STUDENT]
    assert len(student_entities) == 1
    assert student_entities[0].entity_id == "s-002"
    assert student_entities[0].display_name == "Li Mei"


@pytest.mark.asyncio
async def test_student_without_class_triggers_missing_context():
    """Student mentioned without class context → missing_context=['class']."""
    result = await resolve_entities("t-001", "分析学生 Wong Ka Ho 的成绩")
    assert "class" in result.missing_context
    # No student resolved because no class context
    student_entities = [e for e in result.entities if e.entity_type == EntityType.STUDENT]
    assert len(student_entities) == 0


@pytest.mark.asyncio
async def test_student_keyword_without_name():
    """'学生成绩分析' (keyword but no name) without class → missing_context."""
    result = await resolve_entities("t-001", "学生成绩分析")
    assert "class" in result.missing_context


@pytest.mark.asyncio
async def test_student_english_keyword():
    """'Analyze student Chan Tai Man's grades' → resolves student with class context."""
    result = await resolve_entities(
        "t-001",
        "Analyze student Chan Tai Man's grades",
        context={"classId": "class-hk-f1a"},
    )
    student_entities = [e for e in result.entities if e.entity_type == EntityType.STUDENT]
    assert len(student_entities) == 1
    assert student_entities[0].entity_id == "s-003"


# ═══════════════════════════════════════════════════════════════
# ASSIGNMENT RESOLUTION
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_assignment_exact_match_with_class():
    """'分析 1A 班 Unit 5 Test 的提交情况' → class + assignment resolved."""
    result = await resolve_entities(
        "t-001", "分析 1A 班 Test Unit 5 Test 的提交情况"
    )
    class_entities = [e for e in result.entities if e.entity_type == EntityType.CLASS]
    assignment_entities = [e for e in result.entities if e.entity_type == EntityType.ASSIGNMENT]
    assert len(class_entities) == 1
    assert class_entities[0].entity_id == "class-hk-f1a"
    assert len(assignment_entities) == 1
    assert assignment_entities[0].entity_id == "a-001"
    assert assignment_entities[0].display_name == "Unit 5 Test"


@pytest.mark.asyncio
async def test_assignment_with_context_classid():
    """Assignment mentioned with classId in context → resolves assignment."""
    result = await resolve_entities(
        "t-001",
        "分析作业 Essay Writing 的成绩",
        context={"classId": "class-hk-f1a"},
    )
    assignment_entities = [e for e in result.entities if e.entity_type == EntityType.ASSIGNMENT]
    assert len(assignment_entities) == 1
    assert assignment_entities[0].entity_id == "a-002"
    assert assignment_entities[0].display_name == "Essay Writing"


@pytest.mark.asyncio
async def test_assignment_without_class_triggers_missing_context():
    """Assignment mentioned without class → missing_context=['class']."""
    result = await resolve_entities("t-001", "分析考试 Unit 5 Test 的成绩")
    assert "class" in result.missing_context


@pytest.mark.asyncio
async def test_assignment_keyword_without_title():
    """'作业分析' (keyword but no specific title) without class → missing_context."""
    result = await resolve_entities("t-001", "作业分析")
    assert "class" in result.missing_context


# ═══════════════════════════════════════════════════════════════
# MIXED ENTITY RESOLUTION
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_class_and_student_together():
    """'分析 1A 班学生 Li Mei 的成绩' → both class and student."""
    result = await resolve_entities("t-001", "分析 1A 班学生 Li Mei 的成绩")
    types = {e.entity_type for e in result.entities}
    assert EntityType.CLASS in types
    assert EntityType.STUDENT in types
    assert not result.missing_context


@pytest.mark.asyncio
async def test_class_and_assignment_together():
    """'分析 1A 班 Test Unit 5 Test' → both class and assignment."""
    result = await resolve_entities("t-001", "分析 1A 班 Test Unit 5 Test")
    types = {e.entity_type for e in result.entities}
    assert EntityType.CLASS in types
    assert EntityType.ASSIGNMENT in types


@pytest.mark.asyncio
async def test_student_and_assignment_without_class():
    """Student + assignment without class → missing_context=['class']."""
    result = await resolve_entities("t-001", "分析学生 Wong Ka Ho 的作业 Essay Writing")
    assert "class" in result.missing_context


# ═══════════════════════════════════════════════════════════════
# BACKWARD COMPATIBILITY
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_resolve_classes_backward_compat():
    """resolve_classes() still works as thin wrapper."""
    result = await resolve_classes("t-001", "分析 Form 1A 英语成绩")
    assert len(result.entities) == 1
    assert result.entities[0].entity_id == "class-hk-f1a"
    assert result.entities[0].entity_type == EntityType.CLASS


# ═══════════════════════════════════════════════════════════════
# MODEL SERIALIZATION
# ═══════════════════════════════════════════════════════════════


def test_resolved_entity_camel_case():
    """ResolvedEntity serializes to camelCase."""
    entity = ResolvedEntity(
        entity_type=EntityType.CLASS,
        entity_id="class-hk-f1a",
        display_name="Form 1A",
        confidence=1.0,
        match_type="exact",
    )
    data = entity.model_dump(by_alias=True)
    assert "entityType" in data
    assert "entityId" in data
    assert "displayName" in data
    assert "matchType" in data
    assert data["entityId"] == "class-hk-f1a"
    assert data["entityType"] == "class"


def test_resolve_result_camel_case():
    """ResolveResult serializes to camelCase with new fields."""
    result = ResolveResult(
        entities=[
            ResolvedEntity(
                entity_type=EntityType.STUDENT,
                entity_id="s-001",
                display_name="Wong Ka Ho",
                confidence=1.0,
                match_type="exact",
            ),
        ],
        is_ambiguous=False,
        scope_mode="single",
        missing_context=[],
    )
    data = result.model_dump(by_alias=True)
    assert "isAmbiguous" in data
    assert "scopeMode" in data
    assert "missingContext" in data
    assert data["scopeMode"] == "single"
    assert len(data["entities"]) == 1
    assert data["entities"][0]["entityType"] == "student"
