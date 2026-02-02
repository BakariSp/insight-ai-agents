"""Entity resolver — deterministic matching of natural-language class references.

Resolves class names like "1A班", "Form 1A", "1A and 1B", "Form 1 全年级"
to concrete class IDs by matching against the teacher's actual class list.

All matching is deterministic (no LLM calls).  Data is fetched via the
registered ``get_teacher_classes`` MCP tool, which handles mock/real switching.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from agents.provider import execute_mcp_tool
from models.entity import ResolvedEntity, ResolveResult

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
# Regex pattern banks
# ---------------------------------------------------------------------------

# Patterns that capture a single class code like "1A"
_CLASS_PATTERNS: list[re.Pattern[str]] = [
    # "Form 1A", "form 1a", "Form  1A"
    re.compile(r"[Ff](?:orm)?\s*(\d[A-Za-z])", re.UNICODE),
    # "1A班", "1A 班"
    re.compile(r"(\d[A-Za-z])\s*班", re.UNICODE),
    # "Class 1A", "class 1a"
    re.compile(r"[Cc]lass\s*(\d[A-Za-z])", re.UNICODE),
    # Chinese: "中一A", "中二B"
    re.compile(r"中([一二三四五六][A-Za-z])", re.UNICODE),
    # Bare "1A" / "1B" — broadest, used as fallback
    re.compile(r"\b(\d[A-Za-z])\b", re.UNICODE),
]

# Grade-level patterns (capture the grade number/char)
_GRADE_PATTERNS: list[re.Pattern[str]] = [
    # "Form 1 全年级", "Form 1 all classes", "Form1 全部"
    re.compile(
        r"[Ff](?:orm)?\s*(\d)\s*(?:全年级|全部|all\s*classes?)",
        re.IGNORECASE | re.UNICODE,
    ),
    # "中一全部", "中二全年级"
    re.compile(r"中([一二三四五六])\s*(?:全部|全年级)", re.UNICODE),
]

# Delimiters used to split multi-class mentions
_MULTI_DELIM = re.compile(r"[,，、]|\s+(?:和|与|and|&)\s+", re.IGNORECASE | re.UNICODE)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_mention(mention: str) -> str:
    """Normalize a raw mention to a canonical uppercase form like ``1A``."""
    s = mention.strip().upper()
    # Strip common suffixes
    for suffix in ("班", "CLASS", "FORM"):
        s = s.replace(suffix, "")
    s = s.strip()
    # Map Chinese numerals
    for cn, digit in _CN_DIGIT.items():
        s = s.replace(cn.upper(), digit)  # upper() is no-op for CJK but harmless
        s = s.replace(cn, digit)
    return s.strip()


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


def _extract_grade_mentions(text: str) -> list[str]:
    """Extract grade-level mentions that request all classes in a grade.

    Returns normalized grade numbers like ``["1", "2"]``.
    """
    grades: list[str] = []
    for pat in _GRADE_PATTERNS:
        for m in pat.finditer(text):
            raw = m.group(1)
            normalized = _CN_DIGIT.get(raw, raw)
            if normalized not in grades:
                grades.append(normalized)
    return grades


def _build_alias_map(
    classes: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Build lookup structures from a teacher's class list.

    Returns:
        (alias_map, grade_index)
        - alias_map: normalized alias string → class info dict
        - grade_index: grade number string → list of class info dicts
    """
    alias_map: dict[str, dict[str, Any]] = {}
    grade_index: dict[str, list[dict[str, Any]]] = {}

    for cls in classes:
        name: str = cls.get("name", "")
        class_id: str = cls.get("class_id", "")
        grade: str = cls.get("grade", "")

        # Direct name aliases
        if name:
            # "Form 1A" → "FORM 1A"
            alias_map[name.upper()] = cls
            # Normalized code: "Form 1A" → "1A"
            code = _normalize_mention(name)
            if code:
                alias_map[code] = cls
            # Short form: "F1A"
            short = re.sub(r"\s+", "", name.upper())
            if short.startswith("FORM"):
                short_alias = "F" + short[4:]
                alias_map[short_alias] = cls

        # ID as alias
        if class_id:
            alias_map[class_id.upper()] = cls

        # Grade index
        grade_num = ""
        if grade:
            # Extract digit from "Form 1", "Form 2", etc.
            gm = re.search(r"(\d)", grade)
            if gm:
                grade_num = gm.group(1)
            else:
                # Try Chinese: "中一" → "1"
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


def _match_mentions(
    mentions: list[str],
    grade_mentions: list[str],
    alias_map: dict[str, dict[str, Any]],
    grade_index: dict[str, list[dict[str, Any]]],
) -> ResolveResult:
    """Match extracted mentions against the alias map and grade index."""
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
                        class_id=cid,
                        display_name=cls.get("name", cid),
                        confidence=0.9,
                        match_type="grade",
                    )
                )

    if grade_mentions and matched:
        return ResolveResult(
            matches=matched,
            is_ambiguous=False,
            scope_mode="grade",
        )

    # 2) Per-mention matching
    has_fuzzy = False

    for mention in mentions:
        # Exact alias lookup
        cls = alias_map.get(mention)
        if cls:
            cid = cls.get("class_id", "")
            if cid and cid not in matched_ids:
                matched_ids.add(cid)
                matched.append(
                    ResolvedEntity(
                        class_id=cid,
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
                has_fuzzy = True
                matched.append(
                    ResolvedEntity(
                        class_id=cid,
                        display_name=best_cls.get("name", cid),
                        confidence=round(best_score, 2),
                        match_type="fuzzy",
                    )
                )

    # Determine scope and ambiguity
    if not matched:
        return ResolveResult(matches=[], is_ambiguous=False, scope_mode="none")

    is_ambiguous = has_fuzzy
    if len(matched) == 1:
        scope_mode = "single"
    else:
        scope_mode = "multi"

    return ResolveResult(
        matches=matched,
        is_ambiguous=is_ambiguous,
        scope_mode=scope_mode,
    )


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def resolve_classes(
    teacher_id: str,
    query_text: str,
) -> ResolveResult:
    """Resolve class references in *query_text* to concrete class IDs.

    Args:
        teacher_id: Teacher identifier to scope the class lookup.
        query_text: The user's natural-language message.

    Returns:
        A :class:`ResolveResult` with matched classes, ambiguity flag,
        and scope mode.
    """
    # Extract mentions
    class_mentions = _extract_class_mentions(query_text)
    grade_mentions = _extract_grade_mentions(query_text)

    if not class_mentions and not grade_mentions:
        return ResolveResult(matches=[], is_ambiguous=False, scope_mode="none")

    # Fetch teacher's class list
    classes = await _fetch_teacher_classes(teacher_id)
    if not classes:
        return ResolveResult(matches=[], is_ambiguous=False, scope_mode="none")

    # Build lookup and match
    alias_map, grade_idx = _build_alias_map(classes)
    return _match_mentions(class_mentions, grade_mentions, alias_map, grade_idx)
