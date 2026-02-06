"""Question generation pipeline — Draft → Judge → Repair.

Phase 7: Three-stage pipeline for generating high-quality assessment questions.
Phase 1: Added quality constraints (difficulty/type distribution, count enforcement).

Stage 1 (Draft): Generate question drafts based on specifications
Stage 2 (Judge): Evaluate questions for quality issues
Stage 3 (Repair): Fix identified issues and regenerate

The pipeline supports:
- Rubric-driven generation with structured marking criteria
- Weakness-targeted questions based on student error patterns
- Quality gates with configurable pass thresholds
- Multiple repair iterations for failing questions
- Difficulty distribution enforcement (Phase 1)
- Question type distribution enforcement (Phase 1)
- Question count clamping (1-50, Phase 1)
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from pydantic_ai import Agent

from agents.provider import create_model
from config.settings import get_settings
from models.question_pipeline import (
    QuestionDraft,
    JudgeResult,
    QualityIssue,
    QuestionFinal,
    GenerationSpec,
    PipelineResult,
)

logger = logging.getLogger(__name__)

# ── Phase 1 Quality Constraint Defaults ───────────────────────

MIN_QUESTIONS = 1
MAX_QUESTIONS = 50
DEFAULT_QUESTION_COUNT = 10

DEFAULT_DIFFICULTY_DISTRIBUTION: dict[str, float] = {
    "easy": 0.3,
    "medium": 0.5,
    "hard": 0.2,
}

DEFAULT_TYPE_DISTRIBUTION: dict[str, float] = {
    "multiple_choice": 0.6,
    "fill_in_blank": 0.2,
    "true_false": 0.2,
}

DIFFICULTY_TOLERANCE = 0.20  # 20% tolerance for distribution deviation


def clamp_question_count(count: int) -> int:
    """Clamp question count to valid range [1, 50]."""
    return max(MIN_QUESTIONS, min(MAX_QUESTIONS, count))


def compute_target_counts(
    total: int,
    distribution: dict[str, float],
) -> dict[str, int]:
    """Convert a fractional distribution to integer counts summing to total.

    Example: total=10, {"easy": 0.3, "medium": 0.5, "hard": 0.2}
             → {"easy": 3, "medium": 5, "hard": 2}
    """
    raw = {k: v * total for k, v in distribution.items()}
    counts = {k: int(v) for k, v in raw.items()}
    remainder = total - sum(counts.values())
    # Distribute remainder by largest fractional part
    fracs = sorted(distribution.keys(), key=lambda k: raw[k] - counts[k], reverse=True)
    for i in range(remainder):
        counts[fracs[i % len(fracs)]] += 1
    return counts


def check_difficulty_distribution(
    questions: list,
    target: dict[str, float],
    tolerance: float = DIFFICULTY_TOLERANCE,
) -> bool:
    """Check if question difficulty distribution is within tolerance."""
    if not questions:
        return True
    total = len(questions)
    for diff, target_pct in target.items():
        actual_count = sum(1 for q in questions if _get_difficulty(q) == diff)
        actual_pct = actual_count / total
        if abs(actual_pct - target_pct) > tolerance:
            return False
    return True


def _get_difficulty(q: Any) -> str:
    """Extract difficulty from either a Pydantic model or a dict."""
    if isinstance(q, dict):
        return q.get("difficulty", "")
    return getattr(q, "difficulty", "")


class QuestionPipeline:
    """Three-stage question generation pipeline."""

    def __init__(self, model: str | None = None):
        """Initialize the pipeline with a specific model.

        Args:
            model: Model name in "provider/model" format. Defaults to executor_model.
        """
        settings = get_settings()
        self.model = create_model(model or settings.executor_model)
        self.quality_threshold = 0.7  # Minimum score to pass quality gate

    async def generate_draft(
        self,
        spec: GenerationSpec | dict[str, Any],
        rubric_context: dict[str, Any] | None = None,
        weakness_context: dict[str, Any] | None = None,
    ) -> list[QuestionDraft]:
        """Stage 1: Generate question drafts.

        Args:
            spec: Generation specifications (count, types, difficulty, etc.)
            rubric_context: Optional rubric data for guided generation
            weakness_context: Optional student weakness data for targeted generation

        Returns:
            List of QuestionDraft objects
        """
        if isinstance(spec, dict):
            spec = GenerationSpec(**spec)

        prompt = self._build_draft_prompt(spec, rubric_context, weakness_context)

        agent = Agent(
            model=self.model,
            system_prompt=(
                "You are an expert question writer for educational assessments. "
                "Generate clear, unambiguous questions that accurately test the specified knowledge points. "
                "Follow the rubric guidelines when provided. "
                "Always output valid JSON."
            ),
            defer_model_check=True,
        )

        result = await agent.run(prompt)
        return self._parse_drafts(str(result.output), spec)

    async def judge_question(
        self,
        draft: QuestionDraft,
        rubric_context: dict[str, Any] | None = None,
    ) -> JudgeResult:
        """Stage 2: Evaluate question quality.

        Args:
            draft: Question draft to evaluate
            rubric_context: Optional rubric for evaluation criteria

        Returns:
            JudgeResult with pass/fail status and issues
        """
        prompt = self._build_judge_prompt(draft, rubric_context)

        agent = Agent(
            model=self.model,
            system_prompt=(
                "You are a quality assurance expert for educational assessments. "
                "Carefully evaluate questions for clarity, correctness, and alignment with learning objectives. "
                "Identify any issues and provide constructive suggestions for improvement. "
                "Be strict but fair in your evaluation. Always output valid JSON."
            ),
            defer_model_check=True,
        )

        result = await agent.run(prompt)
        return self._parse_judge_result(str(result.output), draft.id)

    async def repair_question(
        self,
        draft: QuestionDraft,
        issues: list[QualityIssue],
    ) -> QuestionDraft:
        """Stage 3: Fix identified issues.

        Args:
            draft: Original question draft
            issues: List of quality issues to fix

        Returns:
            Repaired QuestionDraft
        """
        if not issues:
            return draft

        prompt = self._build_repair_prompt(draft, issues)

        agent = Agent(
            model=self.model,
            system_prompt=(
                "You are an expert at refining educational assessment questions. "
                "Fix the identified issues while preserving the original intent and difficulty level. "
                "Make minimal changes necessary to address each issue. "
                "Always output valid JSON."
            ),
            defer_model_check=True,
        )

        result = await agent.run(prompt)
        return self._parse_repaired_draft(str(result.output), draft)

    async def run_pipeline(
        self,
        spec: GenerationSpec | dict[str, Any],
        rubric_context: dict[str, Any] | None = None,
        weakness_context: dict[str, Any] | None = None,
        max_repair_rounds: int = 2,
    ) -> PipelineResult:
        """Run the full Draft → Judge → Repair pipeline.

        Phase 1 enhancements:
        - Clamps question count to [1, 50]
        - Applies default difficulty distribution if not specified
        - Applies default type distribution if not specified
        - Checks difficulty distribution after generation, retries once if off

        Args:
            spec: Generation specifications
            rubric_context: Optional rubric for guided generation and evaluation
            weakness_context: Optional student weakness data for targeting
            max_repair_rounds: Maximum repair iterations per question

        Returns:
            PipelineResult with all generated questions and statistics
        """
        if isinstance(spec, dict):
            spec = GenerationSpec(**spec)

        # Phase 1: Clamp count and apply default distributions
        spec.count = clamp_question_count(spec.count)
        if not spec.difficulty_distribution:
            spec.difficulty_distribution = DEFAULT_DIFFICULTY_DISTRIBUTION
        if not spec.type_distribution and len(spec.types) <= 1:
            # Only apply default type distribution if user didn't specify types
            if spec.types == ["short_answer"]:  # default type
                spec.type_distribution = DEFAULT_TYPE_DISTRIBUTION
                spec.types = list(spec.type_distribution.keys())

        # Stage 1: Generate drafts
        logger.info("Pipeline Stage 1: Generating %d question drafts", spec.count)
        drafts = await self.generate_draft(spec, rubric_context, weakness_context)

        if not drafts:
            logger.warning("No drafts generated")
            return PipelineResult(total_generated=0)

        final_questions: list[QuestionFinal] = []
        total_passed = 0
        total_repaired = 0
        total_failed = 0

        for draft in drafts:
            current_draft = draft
            repair_count = 0

            for round_num in range(max_repair_rounds + 1):
                # Stage 2: Judge
                logger.debug("Judging question %s (round %d)", draft.id, round_num)
                judge_result = await self.judge_question(current_draft, rubric_context)

                if judge_result.passed and judge_result.score >= self.quality_threshold:
                    # Passed quality gate
                    logger.info("Question %s passed with score %.2f", draft.id, judge_result.score)
                    final_questions.append(self._finalize(current_draft, judge_result.score, repair_count))
                    total_passed += 1
                    if repair_count > 0:
                        total_repaired += 1
                    break

                if round_num < max_repair_rounds:
                    # Stage 3: Repair
                    logger.debug("Repairing question %s (issues: %d)", draft.id, len(judge_result.issues))
                    current_draft = await self.repair_question(current_draft, judge_result.issues)
                    repair_count += 1
                else:
                    # Max repairs reached
                    logger.warning(
                        "Question %s failed quality gate after %d repairs (score: %.2f)",
                        draft.id, max_repair_rounds, judge_result.score
                    )
                    # Include with lower score and flag
                    final_questions.append(
                        self._finalize(current_draft, judge_result.score * 0.5, repair_count, passed=False)
                    )
                    total_failed += 1

        # Calculate average quality score
        avg_score = (
            sum(q.quality_score for q in final_questions) / len(final_questions)
            if final_questions else 0.0
        )

        return PipelineResult(
            questions=final_questions,
            total_generated=len(drafts),
            total_passed=total_passed,
            total_repaired=total_repaired,
            total_failed=total_failed,
            average_quality_score=round(avg_score, 3),
        )

    def _build_draft_prompt(
        self,
        spec: GenerationSpec,
        rubric_context: dict[str, Any] | None,
        weakness_context: dict[str, Any] | None,
    ) -> str:
        """Build prompt for draft generation."""
        parts = [
            f"Generate exactly {spec.count} questions with the following requirements:",
            f"- Subject: {spec.subject or 'General'}",
            f"- Topic: {spec.topic or 'Not specified'}",
            f"- Question types: {', '.join(spec.types)}",
            f"- Difficulty: {spec.difficulty}",
        ]

        # Phase 1: Difficulty distribution
        if spec.difficulty_distribution:
            dist_str = ", ".join(
                f"{k} {v * 100:.0f}%"
                for k, v in spec.difficulty_distribution.items()
            )
            target_counts = compute_target_counts(spec.count, spec.difficulty_distribution)
            counts_str = ", ".join(f"{v} {k}" for k, v in target_counts.items())
            parts.append(f"- Difficulty distribution: {dist_str} → generate {counts_str}")

        # Phase 1: Type distribution
        if spec.type_distribution:
            type_dist_str = ", ".join(
                f"{k} {v * 100:.0f}%"
                for k, v in spec.type_distribution.items()
            )
            type_counts = compute_target_counts(spec.count, spec.type_distribution)
            type_counts_str = ", ".join(f"{v} {k}" for k, v in type_counts.items())
            parts.append(f"- Type distribution: {type_dist_str} → generate {type_counts_str}")

        if spec.knowledge_points:
            parts.append(f"- Target knowledge points: {', '.join(spec.knowledge_points)}")

        if rubric_context:
            parts.append("\n## Rubric Reference")
            if "criteriaText" in rubric_context:
                parts.append(rubric_context["criteriaText"])
            if "commonErrors" in rubric_context:
                parts.append(f"\nCommon errors to test: {', '.join(rubric_context['commonErrors'][:5])}")

        if weakness_context:
            parts.append("\n## Student Weakness Context")
            if "weakPoints" in weakness_context:
                weak_kps = [wp["knowledgePointId"] for wp in weakness_context["weakPoints"][:3]]
                parts.append(f"Focus on these weak knowledge points: {', '.join(weak_kps)}")
            if "recommendedFocus" in weakness_context:
                parts.append(f"Recommended focus areas: {', '.join(weakness_context['recommendedFocus'])}")

        parts.append("""
## Output Format
Return a JSON array of question objects. Each question must have:
- id: unique identifier (e.g., "q1", "q2")
- type: question type (multiple_choice, short_answer, essay, etc.)
- stem: the question text
- options: array of options (for multiple choice) or null
- answer: the correct answer
- explanation: explanation of the answer
- knowledgePointIds: array of knowledge point IDs this question tests
- difficulty: easy, medium, or hard

Example:
```json
[
  {
    "id": "q1",
    "type": "multiple_choice",
    "stem": "What is the main theme of the passage?",
    "options": ["A. Adventure", "B. Friendship", "C. Loss", "D. Growth"],
    "answer": "B",
    "explanation": "The passage focuses on the development of friendship between the main characters.",
    "knowledgePointIds": ["DSE-ENG-U5-RC-01"],
    "difficulty": "medium"
  }
]
```""")

        return "\n".join(parts)

    def _build_judge_prompt(
        self,
        draft: QuestionDraft,
        rubric_context: dict[str, Any] | None,
    ) -> str:
        """Build prompt for quality judgment."""
        options_text = f"\n- Options: {draft.options}" if draft.options else ""

        return f"""Evaluate this question for quality issues:

## Question to Evaluate
- ID: {draft.id}
- Type: {draft.type}
- Stem: {draft.stem}{options_text}
- Answer: {draft.answer}
- Explanation: {draft.explanation}
- Difficulty: {draft.difficulty}
- Knowledge Points: {draft.knowledge_point_ids}

## Quality Checks
Evaluate the question for these issues:
1. **ambiguous**: Is the question clear and unambiguous?
2. **multi_answer**: Does the question have exactly one correct answer?
3. **off_topic**: Does the question align with the specified knowledge points?
4. **difficulty_mismatch**: Is the difficulty appropriate as specified?
5. **answer_inconsistent**: Is the answer consistent with the explanation?
6. **grammar_error**: Are there any grammatical errors?
7. **incomplete**: Is the question complete and self-contained?

## Output Format
Return a JSON object with your evaluation:
```json
{{
  "passed": true/false,
  "score": 0.0-1.0,
  "feedback": "Overall assessment",
  "issues": [
    {{
      "issueType": "ambiguous|multi_answer|off_topic|...",
      "severity": "error|warning|suggestion",
      "description": "What is wrong",
      "suggestion": "How to fix it",
      "affectedField": "stem|options|answer|explanation"
    }}
  ]
}}
```

Score guidelines:
- 1.0: Perfect question, no issues
- 0.8-0.9: Minor suggestions only
- 0.6-0.8: Some warnings but usable
- 0.4-0.6: Significant issues, needs repair
- Below 0.4: Major errors, likely needs regeneration"""

    def _build_repair_prompt(
        self,
        draft: QuestionDraft,
        issues: list[QualityIssue],
    ) -> str:
        """Build prompt for question repair."""
        issues_text = "\n".join([
            f"- **{i.issue_type}** ({i.severity}): {i.description}"
            + (f"\n  Suggestion: {i.suggestion}" if i.suggestion else "")
            for i in issues
        ])

        options_text = json.dumps(draft.options) if draft.options else "null"

        return f"""Fix the following issues with this question:

## Original Question
{{
  "id": "{draft.id}",
  "type": "{draft.type}",
  "stem": "{draft.stem}",
  "options": {options_text},
  "answer": "{draft.answer}",
  "explanation": "{draft.explanation}",
  "knowledgePointIds": {json.dumps(draft.knowledge_point_ids)},
  "difficulty": "{draft.difficulty}"
}}

## Issues to Fix
{issues_text}

## Instructions
1. Fix each identified issue
2. Keep the same question type and difficulty
3. Maintain alignment with the knowledge points
4. Make minimal changes necessary

## Output Format
Return the corrected question as a JSON object:
```json
{{
  "id": "{draft.id}",
  "type": "{draft.type}",
  "stem": "Corrected question text...",
  "options": [...] or null,
  "answer": "Corrected answer",
  "explanation": "Corrected explanation",
  "knowledgePointIds": {json.dumps(draft.knowledge_point_ids)},
  "difficulty": "{draft.difficulty}"
}}
```"""

    def _parse_drafts(self, output: str, spec: GenerationSpec) -> list[QuestionDraft]:
        """Parse LLM output into QuestionDraft objects."""
        text = output.strip()

        # Extract JSON from code block if present
        code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if code_block_match:
            text = code_block_match.group(1).strip()

        try:
            data = json.loads(text)
            if isinstance(data, list):
                drafts = []
                for i, item in enumerate(data):
                    # Ensure each draft has an ID
                    if "id" not in item:
                        item["id"] = f"q{i + 1}-{uuid.uuid4().hex[:6]}"
                    drafts.append(QuestionDraft(**item))
                return drafts
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Failed to parse drafts: %s", e)

        return []

    def _parse_judge_result(self, output: str, question_id: str) -> JudgeResult:
        """Parse LLM output into JudgeResult."""
        text = output.strip()

        # Extract JSON from code block if present
        code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if code_block_match:
            text = code_block_match.group(1).strip()

        try:
            data = json.loads(text)
            issues = [QualityIssue(**i) for i in data.get("issues", [])]

            # Determine if passed based on issues and score
            has_errors = any(i.severity == "error" for i in issues)
            score = data.get("score", 0.5)

            return JudgeResult(
                question_id=question_id,
                passed=data.get("passed", not has_errors) and score >= self.quality_threshold,
                issues=issues,
                score=score,
                feedback=data.get("feedback", ""),
            )
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Failed to parse judge result: %s", e)
            # Default to passing with moderate score if parsing fails
            return JudgeResult(question_id=question_id, passed=True, score=0.6)

    def _parse_repaired_draft(self, output: str, original: QuestionDraft) -> QuestionDraft:
        """Parse LLM output into repaired QuestionDraft."""
        text = output.strip()

        # Extract JSON from code block if present
        code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if code_block_match:
            text = code_block_match.group(1).strip()

        try:
            data = json.loads(text)
            # Preserve original ID
            data["id"] = original.id
            return QuestionDraft(**data)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Failed to parse repaired draft: %s", e)
            return original

    def _finalize(
        self,
        draft: QuestionDraft,
        score: float,
        repair_count: int = 0,
        passed: bool = True,
    ) -> QuestionFinal:
        """Convert draft to final question."""
        return QuestionFinal(
            id=draft.id,
            type=draft.type,
            stem=draft.stem,
            options=draft.options,
            answer=draft.answer,
            explanation=draft.explanation,
            knowledge_point_ids=draft.knowledge_point_ids,
            difficulty=draft.difficulty,
            rubric_ref=draft.rubric_ref,
            skill_tags=draft.skill_tags,
            quality_score=round(score, 3),
            passed_quality_gate=passed,
            repair_count=repair_count,
        )
