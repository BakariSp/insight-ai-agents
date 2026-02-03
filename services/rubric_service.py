"""Rubric loading and retrieval service.

Phase 7: Provides access to assessment rubrics stored in data/rubrics/.
Supports loading by ID and listing/filtering rubrics.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from models.rubric import Rubric

logger = logging.getLogger(__name__)

RUBRIC_DIR = Path(__file__).parent.parent / "data" / "rubrics"


@lru_cache(maxsize=32)
def load_rubric(rubric_id: str) -> Rubric | None:
    """Load a rubric by ID from the data/rubrics directory.

    Args:
        rubric_id: The rubric ID (matches filename without .json extension).

    Returns:
        Rubric object if found, None otherwise.
    """
    # Try exact match first
    file_path = RUBRIC_DIR / f"{rubric_id.lower()}.json"
    if not file_path.exists():
        # Try with dashes instead of underscores
        file_path = RUBRIC_DIR / f"{rubric_id.lower().replace('_', '-')}.json"

    if not file_path.exists():
        logger.warning("Rubric not found: %s", rubric_id)
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Rubric(**data)
    except (json.JSONDecodeError, Exception) as e:
        logger.error("Failed to load rubric %s: %s", rubric_id, e)
        return None


def list_rubrics(
    subject: str = "",
    task_type: str = "",
    level: str = "",
) -> list[dict[str, Any]]:
    """List available rubrics, optionally filtered by subject/task_type/level.

    Args:
        subject: Filter by subject (e.g., "English", "Chinese").
        task_type: Filter by task type (e.g., "essay", "reading_comprehension").
        level: Filter by level (e.g., "DSE").

    Returns:
        List of rubric summaries with id, name, subject, taskType, level.
    """
    if not RUBRIC_DIR.exists():
        logger.warning("Rubric directory does not exist: %s", RUBRIC_DIR)
        return []

    rubrics = []
    for file_path in RUBRIC_DIR.glob("*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Apply filters
            if subject and data.get("subject", "").lower() != subject.lower():
                continue
            if task_type and data.get("taskType", "").lower() != task_type.lower():
                continue
            if level and data.get("level", "").lower() != level.lower():
                continue

            rubrics.append({
                "id": data["id"],
                "name": data["name"],
                "subject": data.get("subject", ""),
                "taskType": data.get("taskType", ""),
                "level": data.get("level", ""),
                "totalMarks": data.get("totalMarks", 0),
                "version": data.get("version", ""),
            })
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to read rubric file %s: %s", file_path, e)
            continue

    return rubrics


def get_rubric_for_task(
    subject: str,
    task_type: str,
    level: str = "DSE",
) -> Rubric | None:
    """Find the best matching rubric for a given task.

    Args:
        subject: Subject (e.g., "English").
        task_type: Task type (e.g., "essay").
        level: Level (e.g., "DSE").

    Returns:
        Best matching Rubric, or None if not found.
    """
    candidates = list_rubrics(subject=subject, task_type=task_type, level=level)

    if not candidates:
        # Try without level filter
        candidates = list_rubrics(subject=subject, task_type=task_type)

    if not candidates:
        return None

    # Return the first match
    return load_rubric(candidates[0]["id"])


def get_rubric_context(rubric: Rubric) -> dict[str, Any]:
    """Convert a Rubric to a context dict suitable for LLM prompts.

    Args:
        rubric: The Rubric object.

    Returns:
        Dictionary with formatted rubric information for prompts.
    """
    criteria_text = []
    for criterion in rubric.criteria:
        levels_text = []
        for level in criterion.levels:
            marks = f"{level.marks_range[0]}-{level.marks_range[1]}" if level.marks_range[0] != level.marks_range[1] else str(level.marks_range[0])
            levels_text.append(f"  - Level {level.level} ({marks} marks): {level.descriptor}")

        criteria_text.append(f"### {criterion.dimension.title()} ({criterion.max_marks} marks)\n" + "\n".join(levels_text))

    return {
        "rubricId": rubric.id,
        "name": rubric.name,
        "subject": rubric.subject,
        "taskType": rubric.task_type,
        "totalMarks": rubric.total_marks,
        "criteriaText": "\n\n".join(criteria_text),
        "commonErrors": rubric.common_errors,
        "instructions": rubric.instructions,
    }
