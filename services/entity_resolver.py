"""General-purpose entity resolver — deterministic matching of natural-language references.

Resolves entity mentions in user input to concrete IDs by matching against
the teacher's actual data.  Supports three entity types:

- **Class**: "1A班", "Form 1A", "F1A", "Form 1 全年级", "1A and 1B"
- **Student**: "学生 Wong Ka Ho", "student Li Mei"
- **Assignment**: "Unit 5 Test", "作业 Essay Writing"

All matching is deterministic (no LLM calls).  Data is fetched via the
registered MCP tools, which handle mock/real switching.

Student and assignment resolution depend on class context — if a class
is not resolvable from the input or existing context, the resolver returns
``missing_context=["class"]`` so the caller can trigger a clarify.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from agents.provider import execute_mcp_tool
from models.entity import EntityType, ResolvedEntity, ResolveResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chinese numeral mapping
# ---------------------------------------------------------------------------

_CN_DIGIT: dict[str, str] = {
    "一": "1",
    "二": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
}

# ---------------------------------------------------------------------------
# Class-detection regex patterns (preserved from original implementation)
# ---------------------------------------------------------------------------

_CLASS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[Ff](?:orm)?\s*(\d[A-Za-z])", re.UNICODE),
    re.compile(r"(\d[A-Za-z])\s*班", re.UNICODE),
    re.compile(r"[Cc]lass\s*(\d[A-Za-z])", re.UNICODE),
    re.compile(r"中([一二三四五六][A-Za-z])", re.UNICODE),
    re.compile(r"\b(\d[A-Za-z])\b", re.UNICODE),
]

# Chinese-style class name patterns: "高一数学班", "高三语文班", etc.
_CN_CLASS_NAME_PATTERNS: list[re.Pattern[str]] = [
    # "高一数学班", "高二英语班", "初三语文班"
    re.compile(r"((?:高|初)[一二三四五六][\u4e00-\u9fff]*班)", re.UNICODE),
    # "数学班", "英语班" (bare subject + 班)
    re.compile(r"([\u4e00-\u9fff]{2,4}班)", re.UNICODE),
    # "高一数学", "高三语文" (without 班 — handles partial/truncated names)
    re.compile(r"((?:高|初)[一二三四五六][\u4e00-\u9fff]{1,2})(?![\u4e00-\u9fff])", re.UNICODE),
]

_GRADE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"[Ff](?:orm)?\s*(\d)\s*(?:全年级|全部|all\s*classes?)",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(r"中([一二三四五六])\s*(?:全部|全年级)", re.UNICODE),
]

_MULTI_DELIM = re.compile(
    r"[,，、]|\s+(?:和|与|and|&)\s+", re.IGNORECASE | re.UNICODE
)

# ---------------------------------------------------------------------------
# Student-detection patterns
# ---------------------------------------------------------------------------

_STUDENT_KEYWORDS: list[re.Pattern[str]] = [
    re.compile(r"学生\s*(.+?)(?:\s*的|$)", re.UNICODE),
    re.compile(r"[Ss]tudent\s+(.+?)(?:'s|\s+的|\s*$)", re.UNICODE),
    re.compile(r"同学\s*(.+?)(?:\s*的|$)", re.UNICODE),
]

# ---------------------------------------------------------------------------
# Assignment-detection patterns
# ---------------------------------------------------------------------------

_ASSIGNMENT_KEYWORDS: list[re.Pattern[str]] = [
    re.compile(r"作业\s*(.+?)(?:\s*的|$)", re.UNICODE),
    re.compile(r"[Aa]ssignment\s+(.+?)(?:'s|\s+的|\s*$)", re.UNICODE),
    re.compile(r"考试\s*(.+?)(?:\s*的|$)", re.UNICODE),
    re.compile(r"[Tt]est\s+(.+?)(?:'s|\s+的|\s*$)", re.UNICODE),
    re.compile(r"[Qq]uiz\s+(.+?)(?:'s|\s+的|\s*$)", re.UNICODE),
    re.compile(r"[Ee]ssay\s+(.+?)(?:'s|\s+的|\s*$)", re.UNICODE),
]

# Broad keyword triggers (no capture group) — used to detect whether
# the user is *talking about* students/assignments even without a name.
_STUDENT_TRIGGER = re.compile(
    r"学生|[Ss]tudent|同学", re.UNICODE
)
_ASSIGNMENT_TRIGGER = re.compile(
    r"作业|[Aa]ssignment|考试|[Tt]est|[Qq]uiz|[Ee]ssay|测验|试卷|练习",
    re.UNICODE,
)


# ---------------------------------------------------------------------------
# Internal helpers — normalisation
# ---------------------------------------------------------------------------


def _normalize_mention(mention: str) -> str:
    """Normalize a raw mention to a canonical uppercase form like ``1A``."""
    s = mention.strip().upper()
    for suffix in ("班", "CLASS", "FORM"):
        s = s.replace(suffix, "")
    s = s.strip()
    for cn, digit in _CN_DIGIT.items():
        s = s.replace(cn.upper(), digit)
        s = s.replace(cn, digit)
    return s.strip()


# ---------------------------------------------------------------------------
# Internal helpers — class extraction (preserved)
# ---------------------------------------------------------------------------


def _extract_class_mentions(text: str) -> list[str]:
    """Extract potential class code mentions from *text*.

    Returns a **deduplicated** list of normalized codes like ``["1A", "1B"]``.
    """
    seen: set[str] = set()
    result: list[str] = []

    for pat in _CLASS_PATTERNS:
        for m in pat.finditer(text):
            code = _normalize_mention(m.group(1))
            if code and code not in seen:
                seen.add(code)
                result.append(code)

    return result


def _extract_cn_class_name_mentions(text: str) -> list[str]:
    """Extract Chinese-style class name mentions like '高一数学班'.

    Returns raw mention strings (not normalized to codes) for direct
    matching against the alias map which stores full class names.
    """
    seen: set[str] = set()
    result: list[str] = []

    for pat in _CN_CLASS_NAME_PATTERNS:
        for m in pat.finditer(text):
            name = m.group(1).strip()
            if name and name not in seen:
                seen.add(name)
                result.append(name)

    return result


def _extract_grade_mentions(text: str) -> list[str]:
    """Extract grade-level mentions that request all classes in a grade."""
    grades: list[str] = []
    for pat in _GRADE_PATTERNS:
        for m in pat.finditer(text):
            raw = m.group(1)
            normalized = _CN_DIGIT.get(raw, raw)
            if normalized not in grades:
                grades.append(normalized)
    return grades


# ---------------------------------------------------------------------------
# Internal helpers — student extraction
# ---------------------------------------------------------------------------


def _extract_student_mentions(text: str) -> list[str]:
    """Extract student name mentions from *text* using keyword patterns.

    Returns a list of candidate name strings (not yet matched against data).
    """
    names: list[str] = []
    seen: set[str] = set()
    for pat in _STUDENT_KEYWORDS:
        for m in pat.finditer(text):
            name = m.group(1).strip()
            # Clean trailing punctuation / particles
            name = re.sub(r"[,，。!！?？]+$", "", name).strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                names.append(name)
    return names


def _has_student_mentions(text: str) -> bool:
    """Return True if text contains student-related keywords."""
    return bool(_STUDENT_TRIGGER.search(text))


# ---------------------------------------------------------------------------
# Internal helpers — assignment extraction
# ---------------------------------------------------------------------------


def _extract_assignment_mentions(text: str) -> list[str]:
    """Extract assignment title mentions from *text* using keyword patterns."""
    titles: list[str] = []
    seen: set[str] = set()
    for pat in _ASSIGNMENT_KEYWORDS:
        for m in pat.finditer(text):
            title = m.group(1).strip()
            title = re.sub(r"[,，。!！?？]+$", "", title).strip()
            if title and title.lower() not in seen:
                seen.add(title.lower())
                titles.append(title)
    return titles


def _has_assignment_mentions(text: str) -> bool:
    """Return True if text contains assignment-related keywords."""
    return bool(_ASSIGNMENT_TRIGGER.search(text))


# ---------------------------------------------------------------------------
# Internal helpers — alias maps and matching
# ---------------------------------------------------------------------------


def _build_class_alias_map(
    classes: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Build lookup structures from a teacher's class list.

    Returns (alias_map, grade_index).
    """
    alias_map: dict[str, dict[str, Any]] = {}
    grade_index: dict[str, list[dict[str, Any]]] = {}

    for cls in classes:
        name: str = cls.get("name", "")
        class_id: str = cls.get("class_id", "")
        grade: str = cls.get("grade", "")

        if name:
            alias_map[name.upper()] = cls
            code = _normalize_mention(name)
            if code:
                alias_map[code] = cls
            short = re.sub(r"\s+", "", name.upper())
            if short.startswith("FORM"):
                short_alias = "F" + short[4:]
                alias_map[short_alias] = cls

        if class_id:
            alias_map[class_id.upper()] = cls

        grade_num = ""
        if grade:
            gm = re.search(r"(\d)", grade)
            if gm:
                grade_num = gm.group(1)
            else:
                for cn, digit in _CN_DIGIT.items():
                    if cn in grade:
                        grade_num = digit
                        break
        if grade_num:
            grade_index.setdefault(grade_num, []).append(cls)

    return alias_map, grade_index


def _simple_edit_distance(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if not a:
        return len(b)
    if not b:
        return len(a)
    m, n = len(a), len(b)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
    return dp[n]


def _fuzzy_score(mention: str, candidate: str) -> float:
    """Return a similarity score between 0.0 and 1.0."""
    if not mention or not candidate:
        return 0.0
    distance = _simple_edit_distance(mention, candidate)
    max_len = max(len(mention), len(candidate))
    return max(0.0, 1.0 - distance / max_len)


# ---------------------------------------------------------------------------
# Class matching
# ---------------------------------------------------------------------------


def _match_class_mentions(
    mentions: list[str],
    grade_mentions: list[str],
    alias_map: dict[str, dict[str, Any]],
    grade_index: dict[str, list[dict[str, Any]]],
) -> list[ResolvedEntity]:
    """Match class mentions against alias map/grade index.

    Returns list of resolved class entities.
    """
    matched: list[ResolvedEntity] = []
    matched_ids: set[str] = set()

    # 1) Grade-level expansion
    for g in grade_mentions:
        for cls in grade_index.get(g, []):
            cid = cls.get("class_id", "")
            if cid and cid not in matched_ids:
                matched_ids.add(cid)
                matched.append(
                    ResolvedEntity(
                        entity_type=EntityType.CLASS,
                        entity_id=cid,
                        display_name=cls.get("name", cid),
                        confidence=0.9,
                        match_type="grade",
                    )
                )

    if grade_mentions and matched:
        return matched

    # 2) Per-mention matching
    for mention in mentions:
        cls = alias_map.get(mention)
        if cls:
            cid = cls.get("class_id", "")
            if cid and cid not in matched_ids:
                matched_ids.add(cid)
                matched.append(
                    ResolvedEntity(
                        entity_type=EntityType.CLASS,
                        entity_id=cid,
                        display_name=cls.get("name", cid),
                        confidence=1.0,
                        match_type="exact",
                    )
                )
            continue

        # Fuzzy matching
        best_score = 0.0
        best_cls: dict[str, Any] | None = None
        for alias_key, alias_cls in alias_map.items():
            score = _fuzzy_score(mention, alias_key)
            if score > best_score:
                best_score = score
                best_cls = alias_cls

        if best_cls and best_score >= 0.6:
            cid = best_cls.get("class_id", "")
            if cid and cid not in matched_ids:
                matched_ids.add(cid)
                matched.append(
                    ResolvedEntity(
                        entity_type=EntityType.CLASS,
                        entity_id=cid,
                        display_name=best_cls.get("name", cid),
                        confidence=round(best_score, 2),
                        match_type="fuzzy",
                    )
                )

    return matched


# ---------------------------------------------------------------------------
# Chinese class name matching
# ---------------------------------------------------------------------------


def _match_cn_class_names(
    mentions: list[str],
    alias_map: dict[str, dict[str, Any]],
) -> list[ResolvedEntity]:
    """Match Chinese class name mentions against the alias map.

    Tries exact match first (case-insensitive), then fuzzy.
    """
    matched: list[ResolvedEntity] = []
    matched_ids: set[str] = set()

    for mention in mentions:
        mention_upper = mention.upper()

        # Exact match
        cls = alias_map.get(mention_upper)
        if cls:
            cid = cls.get("class_id", "")
            if cid and cid not in matched_ids:
                matched_ids.add(cid)
                matched.append(
                    ResolvedEntity(
                        entity_type=EntityType.CLASS,
                        entity_id=cid,
                        display_name=cls.get("name", cid),
                        confidence=1.0,
                        match_type="exact",
                    )
                )
            continue

        # Fuzzy match against all alias keys
        best_score = 0.0
        best_cls: dict[str, Any] | None = None
        for alias_key, alias_cls in alias_map.items():
            score = _fuzzy_score(mention_upper, alias_key)
            if score > best_score:
                best_score = score
                best_cls = alias_cls

        if best_cls and best_score >= 0.6:
            cid = best_cls.get("class_id", "")
            if cid and cid not in matched_ids:
                matched_ids.add(cid)
                matched.append(
                    ResolvedEntity(
                        entity_type=EntityType.CLASS,
                        entity_id=cid,
                        display_name=best_cls.get("name", cid),
                        confidence=round(best_score, 2),
                        match_type="fuzzy",
                    )
                )

    return matched


# ---------------------------------------------------------------------------
# Student matching
# ---------------------------------------------------------------------------


def _match_student_mentions(
    mentions: list[str],
    students: list[dict[str, Any]],
) -> list[ResolvedEntity]:
    """Match student name mentions against a student roster.

    Args:
        mentions: Candidate name strings extracted from user input.
        students: Student dicts from class detail (each has ``student_id``, ``name``).

    Returns list of resolved student entities.
    """
    matched: list[ResolvedEntity] = []
    matched_ids: set[str] = set()

    for mention in mentions:
        mention_lower = mention.lower()
        best_score = 0.0
        best_student: dict[str, Any] | None = None
        exact = False

        for student in students:
            student_name = student.get("name", "")
            if not student_name:
                continue

            # Exact match (case-insensitive)
            if student_name.lower() == mention_lower:
                best_student = student
                best_score = 1.0
                exact = True
                break

            # Partial match — mention is contained in student name or vice versa
            if mention_lower in student_name.lower():
                score = len(mention) / len(student_name)
                if score > best_score:
                    best_score = max(score, 0.8)
                    best_student = student
            elif student_name.lower() in mention_lower:
                score = len(student_name) / len(mention)
                if score > best_score:
                    best_score = max(score, 0.7)
                    best_student = student
            else:
                # Fuzzy fallback
                score = _fuzzy_score(mention_lower, student_name.lower())
                if score > best_score:
                    best_score = score
                    best_student = student

        if best_student and best_score >= 0.6:
            sid = best_student.get("student_id", "")
            if sid and sid not in matched_ids:
                matched_ids.add(sid)
                matched.append(
                    ResolvedEntity(
                        entity_type=EntityType.STUDENT,
                        entity_id=sid,
                        display_name=best_student.get("name", sid),
                        confidence=round(best_score, 2),
                        match_type="exact" if exact else "fuzzy",
                    )
                )

    return matched


# ---------------------------------------------------------------------------
# Assignment matching
# ---------------------------------------------------------------------------


def _match_assignment_mentions(
    mentions: list[str],
    assignments: list[dict[str, Any]],
) -> list[ResolvedEntity]:
    """Match assignment title mentions against an assignment list.

    Args:
        mentions: Candidate title strings extracted from user input.
        assignments: Assignment dicts from class detail
                     (each has ``assignment_id``, ``title``).

    Returns list of resolved assignment entities.
    """
    matched: list[ResolvedEntity] = []
    matched_ids: set[str] = set()

    for mention in mentions:
        mention_lower = mention.lower()
        best_score = 0.0
        best_assignment: dict[str, Any] | None = None
        exact = False

        for assignment in assignments:
            title = assignment.get("title", "")
            if not title:
                continue

            if title.lower() == mention_lower:
                best_assignment = assignment
                best_score = 1.0
                exact = True
                break

            if mention_lower in title.lower():
                score = len(mention) / len(title)
                if score > best_score:
                    best_score = max(score, 0.8)
                    best_assignment = assignment
            elif title.lower() in mention_lower:
                score = len(title) / len(mention)
                if score > best_score:
                    best_score = max(score, 0.7)
                    best_assignment = assignment
            else:
                score = _fuzzy_score(mention_lower, title.lower())
                if score > best_score:
                    best_score = score
                    best_assignment = assignment

        if best_assignment and best_score >= 0.6:
            aid = best_assignment.get("assignment_id", "")
            if aid and aid not in matched_ids:
                matched_ids.add(aid)
                matched.append(
                    ResolvedEntity(
                        entity_type=EntityType.ASSIGNMENT,
                        entity_id=aid,
                        display_name=best_assignment.get("title", aid),
                        confidence=round(best_score, 2),
                        match_type="exact" if exact else "fuzzy",
                    )
                )

    return matched


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


async def _fetch_teacher_classes(teacher_id: str) -> list[dict[str, Any]]:
    """Fetch teacher's classes via the registered MCP tool."""
    if not teacher_id:
        return []
    try:
        data = await execute_mcp_tool(
            "get_teacher_classes", {"teacher_id": teacher_id}
        )
        return data.get("classes", [])
    except Exception:
        logger.exception("Failed to fetch classes for entity resolution")
        return []


async def _fetch_class_detail(
    teacher_id: str, class_id: str
) -> dict[str, Any] | None:
    """Fetch class detail (students + assignments) via MCP tool."""
    try:
        data = await execute_mcp_tool(
            "get_class_detail",
            {"teacher_id": teacher_id, "class_id": class_id},
        )
        if data.get("error"):
            return None
        return data
    except Exception:
        logger.exception("Failed to fetch class detail for entity resolution")
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def resolve_entities(
    teacher_id: str,
    query_text: str,
    context: dict[str, Any] | None = None,
) -> ResolveResult:
    """Resolve all entity references in *query_text* to concrete IDs.

    Detects what entity types are mentioned in the input and resolves each
    against the appropriate data source.  Student and assignment resolution
    depend on class context — if no class is determinable, ``missing_context``
    will include ``"class"``.

    Args:
        teacher_id: Teacher identifier to scope the data lookup.
        query_text: The user's natural-language message.
        context: Optional existing context dict (may contain ``classId``).

    Returns:
        A :class:`ResolveResult` with all matched entities, ambiguity flag,
        scope mode, and any missing context.
    """
    ctx = context or {}
    all_entities: list[ResolvedEntity] = []
    is_ambiguous = False
    scope_mode = "none"
    missing_context: list[str] = []

    # ── 1. Class resolution (always attempted) ──

    class_mentions = _extract_class_mentions(query_text)
    cn_class_mentions = _extract_cn_class_name_mentions(query_text)
    grade_mentions = _extract_grade_mentions(query_text)

    classes: list[dict[str, Any]] = []
    class_entities: list[ResolvedEntity] = []

    if class_mentions or cn_class_mentions or grade_mentions:
        classes = await _fetch_teacher_classes(teacher_id)
        if classes:
            alias_map, grade_idx = _build_class_alias_map(classes)
            # Match code-based mentions (1A, Form 1A, etc.)
            class_entities = _match_class_mentions(
                class_mentions, grade_mentions, alias_map, grade_idx
            )
            # Match Chinese class name mentions (高一数学班, etc.)
            if cn_class_mentions:
                cn_entities = _match_cn_class_names(
                    cn_class_mentions, alias_map
                )
                # Avoid duplicates
                existing_ids = {e.entity_id for e in class_entities}
                for e in cn_entities:
                    if e.entity_id not in existing_ids:
                        class_entities.append(e)
                        existing_ids.add(e.entity_id)
            all_entities.extend(class_entities)

    # Determine class scope mode
    has_fuzzy_class = any(
        e.match_type == "fuzzy" for e in class_entities
    )
    if class_entities:
        if grade_mentions and class_entities:
            scope_mode = "grade"
        elif len(class_entities) == 1:
            scope_mode = "single"
        else:
            scope_mode = "multi"
        if has_fuzzy_class:
            is_ambiguous = True

    # ── 2. Determine class context for dependent resolution ──
    # Priority: explicit context > resolved single class
    class_id_for_detail: str | None = ctx.get("classId")
    if not class_id_for_detail and len(class_entities) == 1:
        class_id_for_detail = class_entities[0].entity_id

    # ── 3. Detect student / assignment mentions ──
    student_mentions = _extract_student_mentions(query_text)
    has_student_trigger = _has_student_mentions(query_text)
    needs_student = bool(student_mentions or has_student_trigger)

    assignment_mentions = _extract_assignment_mentions(query_text)
    has_assignment_trigger = _has_assignment_mentions(query_text)
    needs_assignment = bool(assignment_mentions or has_assignment_trigger)

    # ── 4. Fetch class detail once (shared by student + assignment) ──
    detail: dict[str, Any] | None = None
    if (needs_student or needs_assignment) and class_id_for_detail:
        detail = await _fetch_class_detail(teacher_id, class_id_for_detail)

    # ── 5. Student resolution ──
    if needs_student:
        if class_id_for_detail:
            students = detail.get("students", []) if detail else []
            if student_mentions and students:
                student_entities = _match_student_mentions(
                    student_mentions, students
                )
                all_entities.extend(student_entities)
                if any(e.match_type == "fuzzy" for e in student_entities):
                    is_ambiguous = True
        else:
            if "class" not in missing_context:
                missing_context.append("class")

    # ── 6. Assignment resolution ──
    if needs_assignment:
        if class_id_for_detail:
            assignments = detail.get("assignments", []) if detail else []
            if assignment_mentions and assignments:
                assignment_entities = _match_assignment_mentions(
                    assignment_mentions, assignments
                )
                all_entities.extend(assignment_entities)
                if any(e.match_type == "fuzzy" for e in assignment_entities):
                    is_ambiguous = True
        else:
            if "class" not in missing_context:
                missing_context.append("class")

    # If nothing was detected at all
    if not all_entities and not missing_context:
        scope_mode = "none"

    return ResolveResult(
        entities=all_entities,
        is_ambiguous=is_ambiguous,
        scope_mode=scope_mode,
        missing_context=missing_context,
    )


async def resolve_classes(
    teacher_id: str,
    query_text: str,
) -> ResolveResult:
    """Resolve class references only (backward-compatible wrapper).

    .. deprecated::
        Use :func:`resolve_entities` instead for general entity resolution.
    """
    return await resolve_entities(teacher_id, query_text)
