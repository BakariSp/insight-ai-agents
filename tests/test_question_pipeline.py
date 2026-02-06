"""Tests for question generation pipeline models and parsing logic."""

import pytest
from models.question_pipeline import (
    QuestionDraft,
    QualityIssue,
    JudgeResult,
    QuestionFinal,
    GenerationSpec,
    PipelineResult,
    QuestionType,
    Difficulty,
    IssueSeverity,
    IssueType,
)
from agents.question_pipeline import QuestionPipeline


class TestQuestionPipelineModels:
    """Tests for pipeline data models."""

    def test_question_draft_creation(self):
        """Should create a valid QuestionDraft."""
        draft = QuestionDraft(
            id="q1",
            type="multiple_choice",
            stem="What is 2 + 2?",
            options=["A. 3", "B. 4", "C. 5", "D. 6"],
            answer="B",
            explanation="2 + 2 = 4",
            knowledge_point_ids=["MATH-BASIC-01"],
            difficulty="easy",
        )

        assert draft.id == "q1"
        assert draft.type == "multiple_choice"
        assert len(draft.options) == 4
        assert draft.difficulty == "easy"

    def test_quality_issue_creation(self):
        """Should create a valid QualityIssue."""
        issue = QualityIssue(
            issue_type=IssueType.AMBIGUOUS.value,
            severity=IssueSeverity.WARNING.value,
            description="Question stem is unclear",
            suggestion="Rephrase to clarify the main question",
            affected_field="stem",
        )

        assert issue.issue_type == "ambiguous"
        assert issue.severity == "warning"

    def test_judge_result_creation(self):
        """Should create a valid JudgeResult."""
        result = JudgeResult(
            question_id="q1",
            passed=False,
            issues=[
                QualityIssue(
                    issue_type="ambiguous",
                    severity="error",
                    description="Test issue",
                )
            ],
            score=0.5,
            feedback="Needs improvement",
        )

        assert not result.passed
        assert len(result.issues) == 1
        assert result.score == 0.5

    def test_question_final_creation(self):
        """Should create a valid QuestionFinal."""
        final = QuestionFinal(
            id="q1",
            type="short_answer",
            stem="Explain photosynthesis.",
            options=None,
            answer="Plants convert sunlight to energy...",
            explanation="This is the basic definition.",
            knowledge_point_ids=["BIO-U1-01"],
            difficulty="medium",
            quality_score=0.85,
            passed_quality_gate=True,
            repair_count=1,
        )

        assert final.passed_quality_gate
        assert final.repair_count == 1
        assert final.quality_score == 0.85

    def test_generation_spec_defaults(self):
        """Should have sensible defaults."""
        spec = GenerationSpec()

        assert spec.count == 3
        assert spec.difficulty == Difficulty.MEDIUM.value
        assert QuestionType.SHORT_ANSWER.value in spec.types

    def test_pipeline_result_creation(self):
        """Should create a valid PipelineResult."""
        result = PipelineResult(
            questions=[],
            total_generated=5,
            total_passed=3,
            total_repaired=1,
            total_failed=1,
            average_quality_score=0.75,
        )

        assert result.total_generated == 5
        assert result.total_passed == 3


class TestQuestionPipelineParsing:
    """Tests for pipeline parsing methods (without LLM calls)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.pipeline = QuestionPipeline.__new__(QuestionPipeline)
        self.pipeline.quality_threshold = 0.7

    def test_parse_drafts_valid_json(self):
        """Should parse valid JSON array of drafts."""
        output = """```json
[
  {
    "id": "q1",
    "type": "multiple_choice",
    "stem": "What is the capital of France?",
    "options": ["A. London", "B. Paris", "C. Berlin", "D. Madrid"],
    "answer": "B",
    "explanation": "Paris is the capital of France.",
    "knowledgePointIds": ["GEO-01"],
    "difficulty": "easy"
  }
]
```"""
        spec = GenerationSpec(count=1)
        drafts = self.pipeline._parse_drafts(output, spec)

        assert len(drafts) == 1
        assert drafts[0].id == "q1"
        assert drafts[0].stem == "What is the capital of France?"
        assert drafts[0].answer == "B"

    def test_parse_drafts_no_code_block(self):
        """Should parse JSON without code block markers."""
        output = """[
  {
    "id": "q1",
    "type": "short_answer",
    "stem": "Describe the water cycle.",
    "options": null,
    "answer": "Evaporation, condensation, precipitation...",
    "explanation": "The water cycle involves...",
    "knowledgePointIds": [],
    "difficulty": "medium"
  }
]"""
        spec = GenerationSpec(count=1)
        drafts = self.pipeline._parse_drafts(output, spec)

        assert len(drafts) == 1
        assert drafts[0].type == "short_answer"

    def test_parse_drafts_invalid_json(self):
        """Should return empty list for invalid JSON."""
        output = "This is not valid JSON"
        spec = GenerationSpec(count=1)
        drafts = self.pipeline._parse_drafts(output, spec)

        assert drafts == []

    def test_parse_drafts_generates_ids(self):
        """Should generate IDs for drafts without IDs."""
        output = """[{"type": "short_answer", "stem": "Test?", "answer": "Yes", "explanation": "Test"}]"""
        spec = GenerationSpec(count=1)
        drafts = self.pipeline._parse_drafts(output, spec)

        assert len(drafts) == 1
        assert drafts[0].id.startswith("q1-")

    def test_parse_judge_result_passed(self):
        """Should parse passing judge result."""
        output = """```json
{
  "passed": true,
  "score": 0.9,
  "feedback": "Well-constructed question",
  "issues": []
}
```"""
        result = self.pipeline._parse_judge_result(output, "q1")

        assert result.passed
        assert result.score == 0.9
        assert len(result.issues) == 0

    def test_parse_judge_result_with_issues(self):
        """Should parse judge result with issues."""
        output = """```json
{
  "passed": false,
  "score": 0.5,
  "feedback": "Needs improvement",
  "issues": [
    {
      "issueType": "ambiguous",
      "severity": "warning",
      "description": "Stem is unclear",
      "suggestion": "Rephrase",
      "affectedField": "stem"
    }
  ]
}
```"""
        result = self.pipeline._parse_judge_result(output, "q1")

        assert not result.passed
        assert result.score == 0.5
        assert len(result.issues) == 1
        assert result.issues[0].issue_type == "ambiguous"

    def test_parse_judge_result_invalid(self):
        """Should return default result for invalid JSON."""
        output = "Invalid JSON response"
        result = self.pipeline._parse_judge_result(output, "q1")

        # Should default to passing with moderate score
        assert result.question_id == "q1"
        assert result.passed
        assert result.score == 0.6

    def test_parse_repaired_draft(self):
        """Should parse repaired draft."""
        original = QuestionDraft(
            id="q1",
            type="short_answer",
            stem="Original stem",
            answer="Original answer",
            explanation="Original explanation",
        )

        output = """```json
{
  "id": "q1",
  "type": "short_answer",
  "stem": "Repaired stem",
  "answer": "Repaired answer",
  "explanation": "Repaired explanation",
  "knowledgePointIds": [],
  "difficulty": "medium"
}
```"""
        repaired = self.pipeline._parse_repaired_draft(output, original)

        assert repaired.id == "q1"  # ID preserved
        assert repaired.stem == "Repaired stem"
        assert repaired.answer == "Repaired answer"

    def test_parse_repaired_draft_invalid(self):
        """Should return original for invalid JSON."""
        original = QuestionDraft(
            id="q1",
            type="short_answer",
            stem="Original stem",
            answer="Original answer",
            explanation="Original explanation",
        )

        output = "Invalid JSON"
        repaired = self.pipeline._parse_repaired_draft(output, original)

        assert repaired.id == original.id
        assert repaired.stem == original.stem

    def test_finalize_passed(self):
        """Should finalize a passing question."""
        draft = QuestionDraft(
            id="q1",
            type="multiple_choice",
            stem="Test question",
            options=["A", "B", "C", "D"],
            answer="A",
            explanation="Test explanation",
            difficulty="easy",
        )

        final = self.pipeline._finalize(draft, score=0.85, repair_count=1, passed=True)

        assert final.id == "q1"
        assert final.quality_score == 0.85
        assert final.repair_count == 1
        assert final.passed_quality_gate

    def test_finalize_failed(self):
        """Should finalize a failing question with flag."""
        draft = QuestionDraft(
            id="q1",
            type="short_answer",
            stem="Test",
            answer="Answer",
            explanation="Explanation",
        )

        final = self.pipeline._finalize(draft, score=0.3, repair_count=2, passed=False)

        assert not final.passed_quality_gate
        assert final.quality_score == 0.3
        assert final.repair_count == 2


class TestPromptBuilding:
    """Tests for prompt building methods."""

    def setup_method(self):
        """Set up test fixtures."""
        self.pipeline = QuestionPipeline.__new__(QuestionPipeline)
        self.pipeline.quality_threshold = 0.7

    def test_build_draft_prompt_basic(self):
        """Should build basic draft prompt."""
        spec = GenerationSpec(
            count=3,
            types=["multiple_choice"],
            difficulty="medium",
            subject="English",
            topic="Grammar",
        )

        prompt = self.pipeline._build_draft_prompt(spec, None, None)

        assert "3 questions" in prompt
        assert "English" in prompt
        assert "Grammar" in prompt
        assert "multiple_choice" in prompt
        assert "medium" in prompt

    def test_build_draft_prompt_with_rubric(self):
        """Should include rubric context in prompt."""
        spec = GenerationSpec(count=1)
        rubric_context = {
            "criteriaText": "Content (7 marks): Well-developed ideas...",
            "commonErrors": ["Weak thesis", "Poor organization"],
        }

        prompt = self.pipeline._build_draft_prompt(spec, rubric_context, None)

        assert "Rubric Reference" in prompt
        assert "Content (7 marks)" in prompt
        assert "Weak thesis" in prompt

    def test_build_draft_prompt_with_weakness(self):
        """Should include weakness context in prompt."""
        spec = GenerationSpec(count=1)
        weakness_context = {
            "weakPoints": [
                {"knowledgePointId": "ENG-GR-01"},
                {"knowledgePointId": "ENG-GR-02"},
            ],
            "recommendedFocus": ["ENG-GR-01"],
        }

        prompt = self.pipeline._build_draft_prompt(spec, None, weakness_context)

        assert "Weakness Context" in prompt
        assert "ENG-GR-01" in prompt

    def test_build_judge_prompt(self):
        """Should build judge prompt with question details."""
        draft = QuestionDraft(
            id="q1",
            type="multiple_choice",
            stem="What is 2+2?",
            options=["A. 3", "B. 4", "C. 5"],
            answer="B",
            explanation="Basic arithmetic",
            difficulty="easy",
            knowledge_point_ids=["MATH-01"],
        )

        prompt = self.pipeline._build_judge_prompt(draft, None)

        assert "q1" in prompt
        assert "What is 2+2?" in prompt
        assert "B. 4" in prompt
        assert "easy" in prompt
        assert "ambiguous" in prompt
        assert "multi_answer" in prompt

    def test_build_repair_prompt(self):
        """Should build repair prompt with issues."""
        draft = QuestionDraft(
            id="q1",
            type="short_answer",
            stem="Unclear question",
            answer="Answer",
            explanation="Explanation",
        )

        issues = [
            QualityIssue(
                issue_type="ambiguous",
                severity="error",
                description="Stem is unclear",
                suggestion="Add more context",
            ),
        ]

        prompt = self.pipeline._build_repair_prompt(draft, issues)

        assert "Unclear question" in prompt
        assert "ambiguous" in prompt
        assert "Stem is unclear" in prompt
        assert "Add more context" in prompt
