"""Benchmark: Quiz Fast Path end-to-end latency measurement.

Measures real wall-clock time for:
1. Router classification (qwen-turbo)
2. Quiz generation (qwen-max, streaming)
3. Time-to-first-question (TTFQ)
4. Total generation time

Usage:
    cd insight-ai-agent
    python scripts/benchmark_quiz_fast_path.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

# Ensure project root is importable
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.router import classify_intent
from skills.quiz_skill import generate_quiz, build_quiz_intro

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("benchmark")


@dataclass
class BenchmarkResult:
    test_case: str
    message: str
    router_ms: float = 0.0
    router_intent: str = ""
    router_confidence: float = 0.0
    router_strategy: str = ""
    extracted_params: dict = field(default_factory=dict)
    ttfq_ms: float = 0.0  # time to first question
    total_gen_ms: float = 0.0
    question_count: int = 0
    question_times_ms: list[float] = field(default_factory=list)
    error: str | None = None


async def benchmark_router(message: str) -> tuple[dict, float]:
    """Benchmark router classification and return (result, duration_ms)."""
    t0 = time.perf_counter()
    result = await classify_intent(message)
    duration = (time.perf_counter() - t0) * 1000
    return result, duration


async def benchmark_quiz_generation(
    params: dict,
) -> tuple[int, float, float, list[float]]:
    """Benchmark quiz generation.

    Returns (question_count, ttfq_ms, total_ms, per_question_ms_list).
    """
    t0 = time.perf_counter()
    ttfq = 0.0
    question_times: list[float] = []
    count = 0
    last_t = t0

    async for question in generate_quiz(
        topic=params.get("topic", "一元二次方程"),
        count=params.get("count", 5),
        difficulty=params.get("difficulty", "medium"),
        types=params.get("types"),
        subject=params.get("subject", ""),
        grade=params.get("grade", ""),
    ):
        now = time.perf_counter()
        count += 1
        elapsed = (now - last_t) * 1000

        if count == 1:
            ttfq = (now - t0) * 1000

        question_times.append(elapsed)
        last_t = now

        logger.info(
            "  Q%d [%s] %s... (%.0fms)",
            count,
            question.question_type.value,
            question.question[:40],
            elapsed,
        )

    total = (time.perf_counter() - t0) * 1000
    return count, ttfq, total, question_times


async def run_benchmark(test_case: str, message: str) -> BenchmarkResult:
    """Run a full benchmark: router + quiz generation."""
    result = BenchmarkResult(test_case=test_case, message=message)

    # Step 1: Router
    logger.info("=" * 60)
    logger.info("Test: %s", test_case)
    logger.info("Message: %s", message)
    logger.info("-" * 60)

    try:
        router_result, router_ms = await benchmark_router(message)
        result.router_ms = round(router_ms, 1)
        result.router_intent = router_result.intent
        result.router_confidence = router_result.confidence
        result.router_strategy = router_result.strategy
        result.extracted_params = router_result.extracted_params
        logger.info(
            "Router: intent=%s confidence=%.2f strategy=%s (%.0fms)",
            router_result.intent,
            router_result.confidence,
            router_result.strategy,
            router_ms,
        )
        logger.info("Extracted params: %s", json.dumps(router_result.extracted_params, ensure_ascii=False))
    except Exception as e:
        result.error = f"Router failed: {e}"
        logger.exception("Router failed")
        return result

    # Step 2: Quiz generation (only if quiz_generate intent)
    if router_result.intent == "quiz_generate":
        logger.info("-" * 60)
        logger.info("Generating quiz...")
        try:
            params = router_result.extracted_params
            if not params.get("count"):
                params["count"] = 5  # default for benchmark

            intro = build_quiz_intro(params)
            logger.info("Intro: %s", intro)

            count, ttfq, total, qtimes = await benchmark_quiz_generation(params)
            result.question_count = count
            result.ttfq_ms = round(ttfq, 1)
            result.total_gen_ms = round(total, 1)
            result.question_times_ms = [round(t, 1) for t in qtimes]
        except Exception as e:
            result.error = f"Generation failed: {e}"
            logger.exception("Generation failed")
    else:
        logger.info("Intent is '%s', skipping quiz generation", router_result.intent)

    # Summary
    logger.info("-" * 60)
    logger.info("RESULTS:")
    logger.info("  Router:       %.0fms", result.router_ms)
    if result.question_count > 0:
        logger.info("  TTFQ:         %.0fms", result.ttfq_ms)
        logger.info("  Total gen:    %.0fms", result.total_gen_ms)
        logger.info("  E2E total:    %.0fms", result.router_ms + result.total_gen_ms)
        logger.info("  Questions:    %d", result.question_count)
        logger.info("  Avg per Q:    %.0fms", result.total_gen_ms / max(result.question_count, 1))
    logger.info("=" * 60)

    return result


async def main():
    test_cases = [
        ("Chinese quiz - 5 MCQ", "帮我出5道英语语法选择题"),
        ("English quiz - 5 MCQ", "Generate 5 MCQ questions on quadratic equations"),
        ("Chinese quiz - 10 mixed", "出10道关于一元二次方程的题，选择题和填空题混合"),
        ("Data analysis (should NOT quiz)", "分析 1A 班英语成绩"),
        ("Smalltalk (should NOT quiz)", "你好"),
    ]

    results: list[BenchmarkResult] = []
    for name, msg in test_cases:
        r = await run_benchmark(name, msg)
        results.append(r)
        # Brief pause between tests to avoid rate limiting
        await asyncio.sleep(1)

    # Final summary table
    print("\n" + "=" * 80)
    print("BENCHMARK SUMMARY")
    print("=" * 80)
    print(f"{'Test Case':<35} {'Intent':<16} {'Router':<10} {'TTFQ':<10} {'Total':<10} {'Qs':<5}")
    print("-" * 80)
    for r in results:
        ttfq = f"{r.ttfq_ms:.0f}ms" if r.ttfq_ms else "—"
        total = f"{r.total_gen_ms:.0f}ms" if r.total_gen_ms else "—"
        qs = str(r.question_count) if r.question_count else "—"
        print(f"{r.test_case:<35} {r.router_intent:<16} {r.router_ms:.0f}ms{'':<5} {ttfq:<10} {total:<10} {qs:<5}")

    # Save detailed results to JSON
    output_path = Path(__file__).parent.parent / "docs" / "testing" / "quiz-fast-path-benchmark.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total_tests": len(results),
            "quiz_tests": sum(1 for r in results if r.question_count > 0),
        },
        "results": [],
    }
    for r in results:
        entry = {
            "test_case": r.test_case,
            "message": r.message,
            "router": {
                "intent": r.router_intent,
                "confidence": r.router_confidence,
                "strategy": r.router_strategy,
                "duration_ms": r.router_ms,
                "extracted_params": r.extracted_params,
            },
        }
        if r.question_count > 0:
            entry["generation"] = {
                "question_count": r.question_count,
                "ttfq_ms": r.ttfq_ms,
                "total_ms": r.total_gen_ms,
                "e2e_ms": round(r.router_ms + r.total_gen_ms, 1),
                "per_question_ms": r.question_times_ms,
                "avg_per_question_ms": round(r.total_gen_ms / max(r.question_count, 1), 1),
            }
        if r.error:
            entry["error"] = r.error
        output_data["results"].append(entry)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\nDetailed results saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
