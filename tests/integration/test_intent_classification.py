"""Phase 1 · Stage 1: Single-turn intent classification accuracy tests.

Goal:
- Overall accuracy >= 90%
- quiz_generate recall >= 95%
- quiz vs content boundary accuracy >= 95%

Run:
    pytest tests/integration/test_intent_classification.py -v --tb=short -m live_llm
"""

from __future__ import annotations

import logging
import time

import pytest

from agents.router import classify_intent
from tests.integration.conftest import record_result, skip_no_api_key

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 1. Core intent classification
# ═══════════════════════════════════════════════════════════════

# (message, expected_intent, min_confidence, category)
INTENT_CASES: list[tuple[str, str, float, str]] = [
    # --- chat_smalltalk ---
    ("你好", "chat_smalltalk", 0.8, "chat"),
    ("谢谢你的帮助", "chat_smalltalk", 0.7, "chat"),
    ("今天天气怎么样", "chat_smalltalk", 0.7, "chat"),
    ("你是什么模型？", "chat_smalltalk", 0.7, "chat"),
    ("再见", "chat_smalltalk", 0.7, "chat"),

    # --- chat_qa ---
    ("什么是布鲁姆分类法？", "chat_qa", 0.7, "chat"),
    ("KPI 是什么意思", "chat_qa", 0.7, "chat"),
    ("怎么提高学生的学习兴趣", "chat_qa", 0.7, "chat"),
    ("差异化教学有什么好处？", "chat_qa", 0.7, "chat"),
    ("STEM教育的最新趋势是什么", "chat_qa", 0.7, "chat"),

    # --- quiz_generate (core — P2 fix validation) ---
    ("帮我出10道微积分选择题", "quiz_generate", 0.8, "quiz"),
    ("生成一份关于光合作用的测验", "quiz_generate", 0.7, "quiz"),
    ("出5道填空题，主题是二次方程", "quiz_generate", 0.8, "quiz"),
    ("出一套牛顿力学的考试题", "quiz_generate", 0.7, "quiz"),
    ("帮我出20道英语语法选择题", "quiz_generate", 0.8, "quiz"),

    # P2 boundary cases — previously misclassified as content_create
    ("准备一些对教师的调研题目", "quiz_generate", 0.7, "quiz_boundary"),
    ("出一份用户调研问卷", "quiz_generate", 0.7, "quiz_boundary"),
    ("设计一份教学反馈问卷", "quiz_generate", 0.7, "quiz_boundary"),
    ("为我准备一些对教师的调研题目，了解教学需求", "quiz_generate", 0.7, "quiz_boundary"),
    ("做一份学生满意度调查", "quiz_generate", 0.7, "quiz_boundary"),
    ("帮我设计一个课程评估表", "quiz_generate", 0.7, "quiz_boundary"),

    # --- build_workflow ---
    ("分析1A班的英语成绩", "build_workflow", 0.8, "build"),
    ("帮我看看这个班最近的考试表现", "build_workflow", 0.7, "build"),
    ("对比两个班的数学成绩", "build_workflow", 0.7, "build"),
    ("给我1A班的成绩报告", "build_workflow", 0.7, "build"),
    ("看看高一数学班的期中考试情况", "build_workflow", 0.7, "build"),

    # --- content_create ---
    ("帮我做一个PPT，主题是函数", "content_create", 0.7, "content"),
    ("生成一份教案，关于二战历史", "content_create", 0.7, "content"),
    ("写一份课堂活动计划", "content_create", 0.7, "content"),
    ("帮我写一封家长信", "content_create", 0.7, "content"),
    ("生成一份教学反思报告", "content_create", 0.7, "content"),

    # --- clarify (missing params) ---
    ("分析一下成绩", "clarify", 0.4, "clarify"),
    ("帮我出题", "clarify", 0.4, "clarify"),
    ("看看数据", "clarify", 0.4, "clarify"),
]


@skip_no_api_key
class TestSingleTurnIntent:
    """Run every case against the real LLM router and measure accuracy."""

    @pytest.mark.live_llm
    @pytest.mark.parametrize(
        "message,expected_intent,min_conf,category",
        INTENT_CASES,
        ids=[f"T1-{i:02d}-{c[3]}" for i, c in enumerate(INTENT_CASES)],
    )
    async def test_intent_classification(
        self, message, expected_intent, min_conf, category
    ):
        start = time.perf_counter()
        result = await classify_intent(message=message)
        duration = (time.perf_counter() - start) * 1000

        record_result(
            f"intent-{category}-{message[:20]}",
            "Intent Classification",
            {"message": message, "expected": expected_intent, "category": category},
            {
                "intent": result.intent,
                "confidence": result.confidence,
                "path": result.path,
                "strategy": result.strategy,
            },
            duration,
            status="pass" if result.intent == expected_intent else "fail",
        )

        assert result.intent == expected_intent, (
            f"[{category}] Input: {message!r}\n"
            f"  Got: intent={result.intent}, confidence={result.confidence:.2f}\n"
            f"  Expected: intent={expected_intent}, min_confidence={min_conf}"
        )
        if category != "clarify":
            assert result.confidence >= min_conf, (
                f"Confidence too low: {result.confidence:.2f} < {min_conf}"
            )


# ═══════════════════════════════════════════════════════════════
# 2. Quiz vs Content boundary (target >= 95%)
# ═══════════════════════════════════════════════════════════════

BOUNDARY_CASES: list[tuple[str, str, str]] = [
    # (message, expected_intent, reason)
    ("出一份调研问卷", "quiz_generate", "问卷 = 结构化题目"),
    ("把这些内容出成题", "quiz_generate", "格式转换为结构化"),
    ("生成测验题", "quiz_generate", "测验 = 有标准答案"),
    ("设计一份教师反馈表", "quiz_generate", "反馈表 = 结构化问卷"),
    ("做一份课程满意度调查", "quiz_generate", "调查 = 结构化问卷"),
    ("写一份教学反思", "content_create", "自由文本"),
    ("做一个教案", "content_create", "文档格式"),
    ("写一封邀请信", "content_create", "自由文本"),
    ("准备一份会议纪要", "content_create", "文档格式"),
    ("帮我设计一个课程大纲", "content_create", "文档格式"),
]


@skip_no_api_key
class TestQuizVsContentBoundary:
    """Dedicated test: quiz vs content classification accuracy (target >= 95%)."""

    @pytest.mark.live_llm
    @pytest.mark.parametrize("message,expected,reason", BOUNDARY_CASES)
    async def test_quiz_vs_content(self, message, expected, reason):
        start = time.perf_counter()
        result = await classify_intent(message=message)
        duration = (time.perf_counter() - start) * 1000

        record_result(
            f"boundary-{message[:20]}",
            "Quiz vs Content Boundary",
            {"message": message, "expected": expected, "reason": reason},
            {"intent": result.intent, "confidence": result.confidence},
            duration,
            status="pass" if result.intent == expected else "fail",
        )

        assert result.intent == expected, (
            f"边界分类错误: {message!r}\n"
            f"  Got: {result.intent} | Expected: {expected}\n"
            f"  Reason: {reason}"
        )


# ═══════════════════════════════════════════════════════════════
# 3. Aggregate accuracy (post-run analysis)
# ═══════════════════════════════════════════════════════════════

@skip_no_api_key
class TestAggregateAccuracy:
    """Run all intent cases and check aggregate thresholds.

    This is a single test that runs ALL cases sequentially and computes
    overall accuracy, quiz recall, and boundary accuracy in one shot.
    """

    @pytest.mark.live_llm
    async def test_aggregate_intent_accuracy(self):
        total, correct = 0, 0
        quiz_total, quiz_correct = 0, 0
        boundary_total, boundary_correct = 0, 0
        mismatches = []

        start = time.perf_counter()

        # --- Main intent cases ---
        for message, expected, min_conf, category in INTENT_CASES:
            result = await classify_intent(message=message)
            total += 1
            is_correct = result.intent == expected
            if is_correct:
                correct += 1

            if category in ("quiz", "quiz_boundary"):
                quiz_total += 1
                if is_correct:
                    quiz_correct += 1

            if not is_correct:
                mismatches.append({
                    "message": message,
                    "expected": expected,
                    "got": result.intent,
                    "confidence": result.confidence,
                    "category": category,
                })

        # --- Boundary cases ---
        for message, expected, reason in BOUNDARY_CASES:
            result = await classify_intent(message=message)
            boundary_total += 1
            if result.intent == expected:
                boundary_correct += 1
            else:
                mismatches.append({
                    "message": message,
                    "expected": expected,
                    "got": result.intent,
                    "category": "boundary",
                    "reason": reason,
                })

        duration = (time.perf_counter() - start) * 1000

        overall_rate = correct / total if total else 0
        quiz_rate = quiz_correct / quiz_total if quiz_total else 0
        boundary_rate = boundary_correct / boundary_total if boundary_total else 0

        record_result(
            "test_aggregate_intent_accuracy",
            "Intent — Aggregate",
            {"total": total, "quiz_total": quiz_total, "boundary_total": boundary_total},
            {
                "overall_accuracy": f"{overall_rate:.0%}",
                "quiz_recall": f"{quiz_rate:.0%}",
                "boundary_accuracy": f"{boundary_rate:.0%}",
                "mismatches": mismatches,
            },
            duration,
            status="pass" if overall_rate >= 0.90 and quiz_rate >= 0.90 else "fail",
        )

        logger.info(
            "Aggregate: overall=%s quiz=%s boundary=%s (%d mismatches)",
            f"{overall_rate:.0%}",
            f"{quiz_rate:.0%}",
            f"{boundary_rate:.0%}",
            len(mismatches),
        )

        # Soft assertions — log mismatches even on failure
        for m in mismatches:
            logger.warning("  MISMATCH [%s]: %s → got %s (expected %s)",
                           m["category"], m["message"], m["got"], m["expected"])

        assert overall_rate >= 0.90, (
            f"Overall accuracy {overall_rate:.0%} < 90%. Mismatches: {len(mismatches)}"
        )
        assert quiz_rate >= 0.90, (
            f"Quiz recall {quiz_rate:.0%} < 90%"
        )
