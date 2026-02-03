"""Test script for question generation with HKDSE subjects.

This script tests the question generation pipeline with Math, Chinese, and ICT
knowledge points and rubrics.

Usage:
    python scripts/test_question_generation.py
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def test_knowledge_points_loaded():
    """Test that knowledge points are loaded correctly."""
    from services.knowledge_service import (
        load_knowledge_registry,
        list_knowledge_points,
        get_knowledge_point,
    )

    print("\n" + "=" * 60)
    print("Testing Knowledge Points Loading")
    print("=" * 60)

    subjects = ["Math", "Chinese", "ICT", "English"]

    for subject in subjects:
        registry = load_knowledge_registry(subject, "DSE")
        if registry:
            kps = list_knowledge_points(subject, level="DSE")
            print(f"\n[OK] {subject}: {len(kps)} knowledge points loaded")

            # Show first 3 knowledge points
            for kp in kps[:3]:
                print(f"     - {kp.id}: {kp.name} ({kp.difficulty})")
        else:
            print(f"\n[WARN] {subject}: No registry found")


def test_rubrics_loaded():
    """Test that rubrics are loaded correctly."""
    from services.rubric_service import list_rubrics, load_rubric

    print("\n" + "=" * 60)
    print("Testing Rubrics Loading")
    print("=" * 60)

    rubrics = list_rubrics()
    print(f"\nFound {len(rubrics)} rubrics:")

    for r in rubrics:
        print(f"  - {r['id']}: {r['name']} ({r.get('subject', 'N/A')})")

        # Load and display criteria
        rubric = load_rubric(r["id"])
        if rubric:
            print(f"    Total marks: {rubric.total_marks}")
            print(f"    Criteria: {', '.join(c.dimension for c in rubric.criteria)}")


def test_rag_service():
    """Test RAG service with different subjects."""
    from services.rag_service import CurriculumRAG

    print("\n" + "=" * 60)
    print("Testing RAG Service")
    print("=" * 60)

    rag = CurriculumRAG()
    stats = rag.get_stats()

    print("\nRAG Collections:")
    for name, stat in stats.items():
        print(f"  - {name}: {stat['doc_count']} documents")

    # Test queries for different subjects
    test_queries = [
        ("quadratic equations factorization", "Math"),
        ("議論文 論點 論據", "Chinese"),
        ("SQL database query", "ICT"),
    ]

    print("\nRAG Queries:")
    for query, subject in test_queries:
        results = rag.query("official_corpus", query, n_results=3)
        print(f"\n  Query: '{query}' ({subject})")
        print(f"  Found {len(results)} results")
        for r in results[:2]:
            preview = r["content"][:100].replace("\n", " ") + "..."
            print(f"    - {r['id']}: {preview}")


async def test_question_pipeline():
    """Test question generation pipeline."""
    print("\n" + "=" * 60)
    print("Testing Question Generation Pipeline")
    print("=" * 60)

    try:
        from agents.question_pipeline import QuestionPipeline
        from services.rubric_service import load_rubric
        from services.knowledge_service import list_knowledge_points

        # Test Math question generation
        print("\n[Math] Generating questions...")
        math_spec = {
            "count": 2,
            "subject": "Math",
            "topic": "Quadratic Equations",
            "types": ["multiple_choice"],
            "difficulty": "medium",
            "knowledge_points": ["DSE-MATH-C1-QE-01", "DSE-MATH-C1-QE-02"],
        }

        # Get rubric context
        rubric = load_rubric("dse-math-multiple-choice")
        rubric_context = rubric.model_dump() if rubric else None

        pipeline = QuestionPipeline()

        # Only run if API keys are available
        import os
        if not os.getenv("OPENAI_API_KEY") and not os.getenv("ANTHROPIC_API_KEY"):
            print("  [SKIP] No LLM API key available, skipping LLM generation")
            print("  [INFO] Set OPENAI_API_KEY or ANTHROPIC_API_KEY to test generation")
            return

        questions = await pipeline.run_pipeline(
            spec=math_spec,
            rubric_context=rubric_context,
            max_repair_rounds=1,
        )

        print(f"  Generated {len(questions)} questions:")
        for q in questions:
            print(f"    - {q.id}: {q.stem[:60]}...")
            print(f"      Type: {q.type}, Difficulty: {q.difficulty}")
            print(f"      Quality Score: {q.quality_score:.2f}")

        # Test Chinese question generation
        print("\n[Chinese] Generating questions...")
        chinese_spec = {
            "count": 2,
            "subject": "Chinese",
            "topic": "閱讀理解",
            "types": ["short_answer"],
            "difficulty": "medium",
            "knowledge_points": ["DSE-CHI-RD-CM-01", "DSE-CHI-RD-CM-02"],
        }

        questions = await pipeline.run_pipeline(
            spec=chinese_spec,
            max_repair_rounds=1,
        )

        print(f"  Generated {len(questions)} questions:")
        for q in questions:
            print(f"    - {q.id}: {q.stem[:40]}...")

        # Test ICT question generation
        print("\n[ICT] Generating questions...")
        ict_spec = {
            "count": 2,
            "subject": "ICT",
            "topic": "Programming and Algorithms",
            "types": ["multiple_choice"],
            "difficulty": "medium",
            "knowledge_points": ["DSE-ICT-D-PG-04", "DSE-ICT-D-PG-07"],
        }

        questions = await pipeline.run_pipeline(
            spec=ict_spec,
            max_repair_rounds=1,
        )

        print(f"  Generated {len(questions)} questions:")
        for q in questions:
            print(f"    - {q.id}: {q.stem[:60]}...")

    except ImportError as e:
        print(f"  [SKIP] Question pipeline not available: {e}")
    except Exception as e:
        print(f"  [ERROR] Question generation failed: {e}")
        import traceback
        traceback.print_exc()


def test_error_tag_mapping():
    """Test error tag mapping for different subjects."""
    from services.knowledge_service import map_error_to_knowledge_points

    print("\n" + "=" * 60)
    print("Testing Error Tag Mapping")
    print("=" * 60)

    test_cases = [
        (["quadratic", "factorization"], "Math"),
        (["文言文", "修辭", "推斷"], "Chinese"),
        (["sql", "loop", "array"], "ICT"),
        (["grammar", "vocabulary"], "English"),
    ]

    for errors, subject in test_cases:
        kp_ids = map_error_to_knowledge_points(errors, subject)
        print(f"\n[{subject}] Errors: {errors}")
        print(f"  Mapped to {len(kp_ids)} knowledge points:")
        for kp_id in kp_ids[:5]:
            print(f"    - {kp_id}")


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("HKDSE RAG and Question Generation Test")
    print("=" * 60)

    # Run synchronous tests
    test_knowledge_points_loaded()
    test_rubrics_loaded()
    test_rag_service()
    test_error_tag_mapping()

    # Run async tests
    asyncio.run(test_question_pipeline())

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
