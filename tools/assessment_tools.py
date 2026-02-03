"""Assessment analysis tools — weakness detection and error pattern analysis.

Phase 7: These tools analyze student performance at the question level,
identifying weak knowledge points and error patterns to support targeted
question generation.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from models.data import (
    ErrorPattern,
    KnowledgePoint,
    QuestionItem,
    StudentMastery,
    SubmissionRecord,
)


async def analyze_student_weakness(
    teacher_id: str,
    class_id: str,
    subject: str = "",
    submissions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Analyze weak knowledge points for a class based on submission data.

    Args:
        teacher_id: Teacher ID for authorization.
        class_id: Class ID to analyze.
        subject: Optional subject filter.
        submissions: Optional pre-fetched submission data with items.

    Returns:
        Dictionary containing:
        - classId: The analyzed class ID
        - weakPoints: List of weak knowledge points with error rates
        - recommendedFocus: Top knowledge points to focus on
        - summary: Overall analysis summary
    """
    # If no submissions provided, return empty analysis
    # In production, this would fetch from the data layer
    if not submissions:
        return {
            "classId": class_id,
            "weakPoints": [],
            "recommendedFocus": [],
            "summary": {
                "totalStudents": 0,
                "totalQuestions": 0,
                "analyzedItems": 0,
            },
        }

    # Aggregate error data by knowledge point
    kp_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "errorCount": 0,
            "totalAttempts": 0,
            "affectedStudents": set(),
            "errorTags": defaultdict(int),
        }
    )

    total_students = 0
    total_items = 0

    for sub_data in submissions:
        sub = SubmissionRecord(**sub_data) if isinstance(sub_data, dict) else sub_data
        if not sub.items:
            continue

        total_students += 1

        for item in sub.items:
            total_items += 1
            for kp_id in item.knowledge_point_ids:
                kp_stats[kp_id]["totalAttempts"] += 1
                if not item.correct:
                    kp_stats[kp_id]["errorCount"] += 1
                    kp_stats[kp_id]["affectedStudents"].add(sub.student_id)
                    for tag in item.error_tags:
                        kp_stats[kp_id]["errorTags"][tag] += 1

    # Build weak points list sorted by error rate
    weak_points = []
    for kp_id, stats in kp_stats.items():
        if stats["totalAttempts"] > 0:
            error_rate = stats["errorCount"] / stats["totalAttempts"]
            weak_points.append({
                "knowledgePointId": kp_id,
                "errorRate": round(error_rate, 3),
                "errorCount": stats["errorCount"],
                "totalAttempts": stats["totalAttempts"],
                "affectedStudents": len(stats["affectedStudents"]),
                "commonErrorTags": sorted(
                    stats["errorTags"].keys(),
                    key=lambda t: stats["errorTags"][t],
                    reverse=True,
                )[:5],
            })

    # Sort by error rate descending
    weak_points.sort(key=lambda x: x["errorRate"], reverse=True)

    # Recommend top 3 focus areas
    recommended_focus = [wp["knowledgePointId"] for wp in weak_points[:3]]

    return {
        "classId": class_id,
        "weakPoints": weak_points,
        "recommendedFocus": recommended_focus,
        "summary": {
            "totalStudents": total_students,
            "totalQuestions": total_items,
            "analyzedItems": total_items,
            "knowledgePointsCovered": len(kp_stats),
        },
    }


async def get_student_error_patterns(
    teacher_id: str,
    student_id: str,
    class_id: str = "",
    submissions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Get error patterns for a single student.

    Args:
        teacher_id: Teacher ID for authorization.
        student_id: Student ID to analyze.
        class_id: Optional class ID filter.
        submissions: Optional pre-fetched submission data.

    Returns:
        Dictionary containing:
        - studentId: The analyzed student ID
        - errorPatterns: List of error patterns by knowledge point
        - overallMastery: Average mastery rate across all knowledge points
    """
    if not submissions:
        return {
            "studentId": student_id,
            "errorPatterns": [],
            "overallMastery": 0.0,
        }

    # Aggregate by knowledge point
    kp_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "correct": 0,
            "total": 0,
            "errorTags": defaultdict(int),
        }
    )

    for sub_data in submissions:
        sub = SubmissionRecord(**sub_data) if isinstance(sub_data, dict) else sub_data
        if sub.student_id != student_id:
            continue
        if not sub.items:
            continue

        for item in sub.items:
            for kp_id in item.knowledge_point_ids:
                kp_stats[kp_id]["total"] += 1
                if item.correct:
                    kp_stats[kp_id]["correct"] += 1
                else:
                    for tag in item.error_tags:
                        kp_stats[kp_id]["errorTags"][tag] += 1

    # Build error patterns
    error_patterns = []
    total_mastery = 0.0

    for kp_id, stats in kp_stats.items():
        if stats["total"] > 0:
            mastery = stats["correct"] / stats["total"]
            error_count = stats["total"] - stats["correct"]
            total_mastery += mastery

            if error_count > 0:
                error_patterns.append({
                    "knowledgePointId": kp_id,
                    "errorCount": error_count,
                    "totalAttempts": stats["total"],
                    "masteryRate": round(mastery, 3),
                    "errorTags": sorted(
                        stats["errorTags"].keys(),
                        key=lambda t: stats["errorTags"][t],
                        reverse=True,
                    )[:5],
                })

    # Sort by mastery rate ascending (worst first)
    error_patterns.sort(key=lambda x: x["masteryRate"])

    overall_mastery = total_mastery / len(kp_stats) if kp_stats else 0.0

    return {
        "studentId": student_id,
        "errorPatterns": error_patterns,
        "overallMastery": round(overall_mastery, 3),
        "knowledgePointsAssessed": len(kp_stats),
    }


def calculate_class_mastery(
    submissions: list[dict[str, Any]],
    knowledge_point_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Calculate mastery rates for a class across knowledge points.

    Args:
        submissions: List of submission records with items.
        knowledge_point_ids: Optional filter for specific knowledge points.

    Returns:
        Dictionary with mastery statistics per knowledge point.
    """
    kp_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"correct": 0, "total": 0}
    )

    for sub_data in submissions:
        sub = SubmissionRecord(**sub_data) if isinstance(sub_data, dict) else sub_data
        if not sub.items:
            continue

        for item in sub.items:
            for kp_id in item.knowledge_point_ids:
                if knowledge_point_ids and kp_id not in knowledge_point_ids:
                    continue
                kp_stats[kp_id]["total"] += 1
                if item.correct:
                    kp_stats[kp_id]["correct"] += 1

    mastery_data = []
    for kp_id, stats in kp_stats.items():
        if stats["total"] > 0:
            mastery_data.append({
                "knowledgePointId": kp_id,
                "masteryRate": round(stats["correct"] / stats["total"], 3),
                "correctCount": stats["correct"],
                "totalAttempts": stats["total"],
            })

    # Sort by mastery rate
    mastery_data.sort(key=lambda x: x["masteryRate"])

    return {
        "knowledgePointMastery": mastery_data,
        "averageMastery": round(
            sum(m["masteryRate"] for m in mastery_data) / len(mastery_data), 3
        ) if mastery_data else 0.0,
    }
