"""Knowledge point registry and lookup service.

Phase 7 P1-2: Provides access to structured knowledge point definitions
for curriculum alignment and weakness-targeted question generation.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from models.data import KnowledgePoint

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent / "data" / "knowledge_points"

# Subject code → full subject name mapping
# Used to resolve knowledge point IDs like "DSE-ENG-U5-RC-01"
SUBJECT_CODE_MAP: dict[str, str] = {
    "ENG": "English",
    "CHI": "Chinese",
    "MATH": "Math",
    "BIO": "Biology",
    "CHEM": "Chemistry",
    "PHY": "Physics",
    "HIST": "History",
    "GEOG": "Geography",
}

# Error tag → Knowledge point ID mapping
# This maps common error types to relevant knowledge points
ERROR_TAG_MAPPING: dict[str, list[str]] = {
    # Grammar errors
    "grammar": ["DSE-ENG-U5-GR-01", "DSE-ENG-U5-GR-02", "DSE-ENG-U5-GR-03"],
    "tense": ["DSE-ENG-U5-GR-01"],
    "tenses": ["DSE-ENG-U5-GR-01"],
    "subject-verb": ["DSE-ENG-U5-GR-02"],
    "agreement": ["DSE-ENG-U5-GR-02"],
    "conditional": ["DSE-ENG-U5-GR-03"],

    # Reading comprehension errors
    "inference": ["DSE-ENG-U5-RC-01", "DSE-ENG-U5-RC-03"],
    "main_idea": ["DSE-ENG-U5-RC-01"],
    "detail": ["DSE-ENG-U5-RC-02"],
    "supporting_detail": ["DSE-ENG-U5-RC-02"],
    "author_purpose": ["DSE-ENG-U5-RC-04"],
    "tone": ["DSE-ENG-U5-RC-04"],

    # Vocabulary errors
    "vocabulary": ["DSE-ENG-U5-VC-01", "DSE-ENG-U5-VC-02"],
    "word_choice": ["DSE-ENG-U5-VC-01"],
    "context_clues": ["DSE-ENG-U5-VC-02"],

    # Writing errors
    "organization": ["DSE-ENG-U5-WR-01", "DSE-ENG-U5-WR-03"],
    "structure": ["DSE-ENG-U5-WR-01"],
    "thesis": ["DSE-ENG-U5-WR-02"],
    "argument": ["DSE-ENG-U5-WR-02"],
    "cohesion": ["DSE-ENG-U5-WR-03"],
    "coherence": ["DSE-ENG-U5-WR-03"],
    "transition": ["DSE-ENG-U5-WR-03"],
}


@lru_cache(maxsize=32)
def load_knowledge_registry(subject: str, level: str = "DSE") -> dict[str, Any]:
    """Load knowledge point registry for a subject.

    Args:
        subject: Subject name (e.g., "English").
        level: Education level (e.g., "DSE").

    Returns:
        Registry dictionary with units and knowledge points.
    """
    file_path = KNOWLEDGE_DIR / f"{level.lower()}-{subject.lower()}.json"
    if not file_path.exists():
        logger.warning("Knowledge registry not found: %s", file_path)
        return {}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception) as e:
        logger.error("Failed to load knowledge registry: %s", e)
        return {}


def get_knowledge_point(knowledge_point_id: str) -> KnowledgePoint | None:
    """Get a single knowledge point by ID.

    Args:
        knowledge_point_id: Knowledge point ID (e.g., "DSE-ENG-U5-RC-01").

    Returns:
        KnowledgePoint object if found, None otherwise.
    """
    # Parse ID to extract subject and level
    # Format: LEVEL-SUBJECT_CODE-UNIT-TYPE-NUMBER (e.g., DSE-ENG-U5-RC-01)
    parts = knowledge_point_id.split("-")
    if len(parts) < 2:
        return None

    level, subject_code = parts[0], parts[1]

    # Map subject code to full subject name
    subject = SUBJECT_CODE_MAP.get(subject_code.upper(), subject_code)
    registry = load_knowledge_registry(subject, level)

    for unit in registry.get("units", []):
        for kp in unit.get("knowledgePoints", []):
            if kp["id"] == knowledge_point_id:
                return KnowledgePoint(
                    id=kp["id"],
                    name=kp["name"],
                    subject=registry.get("subject", ""),
                    unit=unit.get("id", ""),
                    level=registry.get("level", level),
                    description=kp.get("description", ""),
                    skill_tags=kp.get("skillTags", []),
                    prerequisites=kp.get("prerequisites", []),
                    difficulty=kp.get("difficulty", "medium"),
                )

    return None


def list_knowledge_points(
    subject: str,
    unit: str = "",
    skill_tags: list[str] | None = None,
    difficulty: str = "",
    level: str = "DSE",
) -> list[KnowledgePoint]:
    """List knowledge points with optional filters.

    Args:
        subject: Subject name (e.g., "English").
        unit: Optional unit filter.
        skill_tags: Optional skill tag filter (any match).
        difficulty: Optional difficulty filter.
        level: Education level.

    Returns:
        List of matching KnowledgePoint objects.
    """
    registry = load_knowledge_registry(subject, level)
    results = []

    for u in registry.get("units", []):
        # Unit filter
        if unit and u["id"] != unit and u["name"] != unit:
            continue

        for kp in u.get("knowledgePoints", []):
            # Skill tag filter
            if skill_tags:
                kp_tags = kp.get("skillTags", [])
                if not any(tag in kp_tags for tag in skill_tags):
                    continue

            # Difficulty filter
            if difficulty and kp.get("difficulty", "medium") != difficulty:
                continue

            results.append(KnowledgePoint(
                id=kp["id"],
                name=kp["name"],
                subject=registry.get("subject", ""),
                unit=u.get("id", ""),
                level=registry.get("level", level),
                description=kp.get("description", ""),
                skill_tags=kp.get("skillTags", []),
                prerequisites=kp.get("prerequisites", []),
                difficulty=kp.get("difficulty", "medium"),
            ))

    return results


def map_error_to_knowledge_points(
    error_tags: list[str],
    subject: str = "English",
) -> list[str]:
    """Map error tags to knowledge point IDs.

    Args:
        error_tags: List of error tags (e.g., ["grammar", "tense"]).
        subject: Subject for filtering (default "English").

    Returns:
        List of relevant knowledge point IDs.
    """
    knowledge_points = set()

    for tag in error_tags:
        tag_lower = tag.lower().replace(" ", "_")
        if tag_lower in ERROR_TAG_MAPPING:
            knowledge_points.update(ERROR_TAG_MAPPING[tag_lower])

    return list(knowledge_points)


def get_prerequisite_chain(knowledge_point_id: str) -> list[KnowledgePoint]:
    """Get the prerequisite chain for a knowledge point.

    Args:
        knowledge_point_id: Starting knowledge point ID.

    Returns:
        List of prerequisite knowledge points in order.
    """
    visited = set()
    chain = []

    def collect_prerequisites(kp_id: str) -> None:
        if kp_id in visited:
            return
        visited.add(kp_id)

        kp = get_knowledge_point(kp_id)
        if not kp:
            return

        # Process prerequisites first (depth-first)
        for prereq_id in kp.prerequisites:
            collect_prerequisites(prereq_id)

        chain.append(kp)

    collect_prerequisites(knowledge_point_id)
    return chain


def get_knowledge_points_for_weakness(
    weak_knowledge_point_ids: list[str],
    include_prerequisites: bool = True,
) -> list[KnowledgePoint]:
    """Get knowledge points to focus on based on weaknesses.

    Args:
        weak_knowledge_point_ids: IDs of weak knowledge points.
        include_prerequisites: Whether to include prerequisites.

    Returns:
        List of knowledge points to focus on.
    """
    result_ids = set()
    results = []

    for kp_id in weak_knowledge_point_ids:
        if include_prerequisites:
            chain = get_prerequisite_chain(kp_id)
            for kp in chain:
                if kp.id not in result_ids:
                    result_ids.add(kp.id)
                    results.append(kp)
        else:
            kp = get_knowledge_point(kp_id)
            if kp and kp.id not in result_ids:
                result_ids.add(kp.id)
                results.append(kp)

    return results


def get_related_knowledge_points(
    knowledge_point_id: str,
    same_unit: bool = True,
    same_skill: bool = False,
) -> list[KnowledgePoint]:
    """Get knowledge points related to the given one.

    Args:
        knowledge_point_id: Reference knowledge point ID.
        same_unit: Filter to same unit.
        same_skill: Filter to same skill tags.

    Returns:
        List of related knowledge points.
    """
    ref_kp = get_knowledge_point(knowledge_point_id)
    if not ref_kp:
        return []

    # Parse subject from ID
    parts = knowledge_point_id.split("-")
    if len(parts) < 2:
        return []

    level, subject_code = parts[0], parts[1]
    # Map subject code to full subject name
    subject = SUBJECT_CODE_MAP.get(subject_code.upper(), subject_code)

    # Get all knowledge points with filters
    filters = {}
    if same_unit:
        filters["unit"] = ref_kp.unit
    if same_skill and ref_kp.skill_tags:
        filters["skill_tags"] = ref_kp.skill_tags

    all_kps = list_knowledge_points(subject, level=level, **filters)

    # Exclude the reference knowledge point
    return [kp for kp in all_kps if kp.id != knowledge_point_id]
