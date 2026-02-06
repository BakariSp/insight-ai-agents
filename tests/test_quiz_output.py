"""Tests for QuizOutputV1 models — Phase 1 output schema validation."""

import pytest

from models.quiz_output import (
    QuestionTypeV1,
    QuizQuestionV1,
    QuizOutputV1,
    QuizMeta,
    PIPELINE_TO_V1_TYPE_MAP,
    map_pipeline_type_to_v1,
    convert_pipeline_to_v1,
    build_quiz_meta,
    validate_question_types,
)


# ── QuestionTypeV1 enum tests ────────────────────────────────


class TestQuestionTypeV1:
    """Tests for V1 question type enum."""

    def test_all_nine_types_exist(self):
        """Should have exactly 9 question types."""
        assert len(QuestionTypeV1) == 9

    def test_values_are_uppercase(self):
        """All values should be UPPERCASE to align with Java."""
        for t in QuestionTypeV1:
            assert t.value == t.value.upper()

    def test_specific_types(self):
        assert QuestionTypeV1.SINGLE_CHOICE.value == "SINGLE_CHOICE"
        assert QuestionTypeV1.COMPOSITE.value == "COMPOSITE"
        assert QuestionTypeV1.ORDERING.value == "ORDERING"


# ── Pipeline → V1 type mapping ───────────────────────────────


class TestTypeMapping:
    """Tests for pipeline to V1 type conversion."""

    def test_multiple_choice_maps_to_single_choice(self):
        """Pipeline 'multiple_choice' defaults to SINGLE_CHOICE."""
        assert map_pipeline_type_to_v1("multiple_choice") == "SINGLE_CHOICE"

    def test_essay_maps_to_long_answer(self):
        assert map_pipeline_type_to_v1("essay") == "LONG_ANSWER"

    def test_passthrough_uppercase(self):
        """Already-uppercase V1 types pass through unchanged."""
        assert map_pipeline_type_to_v1("SINGLE_CHOICE") == "SINGLE_CHOICE"
        assert map_pipeline_type_to_v1("COMPOSITE") == "COMPOSITE"

    def test_unknown_type_degrades(self):
        """Unknown types degrade to SHORT_ANSWER."""
        assert map_pipeline_type_to_v1("unknown_type") == "SHORT_ANSWER"

    def test_all_pipeline_types_mapped(self):
        """Every key in PIPELINE_TO_V1_TYPE_MAP maps to a valid V1 type."""
        for v1_val in PIPELINE_TO_V1_TYPE_MAP.values():
            assert v1_val in {t.value for t in QuestionTypeV1}


# ── QuizQuestionV1 validation ────────────────────────────────


class TestQuizQuestionV1:
    """Tests for per-question validation."""

    def test_valid_single_choice(self):
        q = QuizQuestionV1(
            id="q-001",
            order=1,
            question_type=QuestionTypeV1.SINGLE_CHOICE,
            question="What is 2+2?",
            options=["3", "4", "5", "6"],
            correct_answer="4",
            difficulty="easy",
            points=1.0,
        )
        assert q.question_type == QuestionTypeV1.SINGLE_CHOICE

    def test_choice_requires_options(self):
        """Choice questions must have >= 2 options."""
        with pytest.raises(ValueError, match="Choice question must have >= 2 options"):
            QuizQuestionV1(
                id="q-001",
                order=1,
                question_type=QuestionTypeV1.SINGLE_CHOICE,
                question="Test?",
                options=["A"],
                correct_answer="A",
                difficulty="easy",
            )

    def test_choice_requires_answer(self):
        """Choice questions must have correct_answer."""
        with pytest.raises(ValueError, match="Choice question must have correct_answer"):
            QuizQuestionV1(
                id="q-001",
                order=1,
                question_type=QuestionTypeV1.SINGLE_CHOICE,
                question="Test?",
                options=["A", "B"],
                correct_answer=None,
                difficulty="easy",
            )

    def test_composite_requires_sub_questions(self):
        """COMPOSITE must have sub_questions."""
        with pytest.raises(ValueError, match="COMPOSITE question must have sub_questions"):
            QuizQuestionV1(
                id="q-001",
                order=1,
                question_type=QuestionTypeV1.COMPOSITE,
                question="Read the passage.",
                difficulty="medium",
            )

    def test_composite_no_correct_answer(self):
        """COMPOSITE root should not have correct_answer."""
        sub = QuizQuestionV1(
            id="q-001-a",
            order=1,
            question_type=QuestionTypeV1.SHORT_ANSWER,
            question="Explain.",
            correct_answer="Because...",
            difficulty="easy",
        )
        with pytest.raises(ValueError, match="COMPOSITE root should not have correct_answer"):
            QuizQuestionV1(
                id="q-001",
                order=1,
                question_type=QuestionTypeV1.COMPOSITE,
                question="Read the passage.",
                correct_answer="should not be here",
                difficulty="medium",
                sub_questions=[sub],
            )

    def test_valid_composite(self):
        """Valid COMPOSITE with sub_questions."""
        sub_a = QuizQuestionV1(
            id="q-001-a",
            order=1,
            question_type=QuestionTypeV1.SINGLE_CHOICE,
            question="What is the main idea?",
            options=["A", "B", "C", "D"],
            correct_answer="B",
            difficulty="easy",
            points=2.0,
        )
        sub_b = QuizQuestionV1(
            id="q-001-b",
            order=2,
            question_type=QuestionTypeV1.SHORT_ANSWER,
            question="Explain why.",
            correct_answer="Because...",
            difficulty="medium",
            points=3.0,
        )
        composite = QuizQuestionV1(
            id="q-001",
            order=1,
            question_type=QuestionTypeV1.COMPOSITE,
            question="Read the passage and answer.",
            difficulty="medium",
            points=5.0,
            sub_questions=[sub_a, sub_b],
        )
        assert len(composite.sub_questions) == 2

    def test_true_false_requires_answer(self):
        with pytest.raises(ValueError, match="TRUE_FALSE question must have correct_answer"):
            QuizQuestionV1(
                id="q-001",
                order=1,
                question_type=QuestionTypeV1.TRUE_FALSE,
                question="The sky is blue.",
                correct_answer=None,
                difficulty="easy",
            )

    def test_short_answer_no_options_ok(self):
        """SHORT_ANSWER doesn't require options."""
        q = QuizQuestionV1(
            id="q-001",
            order=1,
            question_type=QuestionTypeV1.SHORT_ANSWER,
            question="What is photosynthesis?",
            correct_answer="Plants convert sunlight...",
            difficulty="medium",
        )
        assert q.options is None

    def test_multiple_choice_list_answer(self):
        """MULTIPLE_CHOICE can have list[str] correct_answer."""
        q = QuizQuestionV1(
            id="q-001",
            order=1,
            question_type=QuestionTypeV1.MULTIPLE_CHOICE,
            question="Select all that apply.",
            options=["A", "B", "C", "D"],
            correct_answer=["A", "C"],
            difficulty="medium",
        )
        assert q.correct_answer == ["A", "C"]

    def test_camel_case_serialization(self):
        """Output should use camelCase field names."""
        q = QuizQuestionV1(
            id="q-001",
            order=1,
            question_type=QuestionTypeV1.SINGLE_CHOICE,
            question="Test?",
            options=["A", "B"],
            correct_answer="A",
            difficulty="easy",
            knowledge_point="Grammar",
        )
        data = q.model_dump(by_alias=True)
        assert "questionType" in data
        assert "correctAnswer" in data
        assert "knowledgePoint" in data


# ── QuizOutputV1 tests ───────────────────────────────────────


class TestQuizOutputV1:
    """Tests for top-level quiz output."""

    def _make_question(self, **overrides) -> QuizQuestionV1:
        defaults = dict(
            id="q-001",
            order=1,
            question_type=QuestionTypeV1.SINGLE_CHOICE,
            question="Test?",
            options=["A", "B", "C", "D"],
            correct_answer="A",
            difficulty="easy",
            points=2.0,
        )
        defaults.update(overrides)
        return QuizQuestionV1(**defaults)

    def test_valid_quiz_output(self):
        q1 = self._make_question(id="q-001", order=1, points=2.0)
        q2 = self._make_question(id="q-002", order=2, points=3.0)
        output = QuizOutputV1(
            title="Unit 5 Grammar Quiz",
            questions=[q1, q2],
            total_points=5.0,
        )
        assert output.total_points == 5.0
        assert len(output.questions) == 2

    def test_total_points_auto_corrected(self):
        """total_points auto-corrects to match sum of question points."""
        q1 = self._make_question(points=2.0)
        output = QuizOutputV1(
            title="Test",
            questions=[q1],
            total_points=999.0,  # Intentionally wrong
        )
        assert output.total_points == 2.0

    def test_empty_questions_allowed(self):
        """Empty questions list is allowed (edge case)."""
        output = QuizOutputV1(
            title="Empty Quiz",
            questions=[],
            total_points=0.0,
        )
        assert len(output.questions) == 0

    def test_full_serialization(self):
        """Full quiz serializes to camelCase JSON."""
        q = self._make_question(knowledge_point="Grammar")
        output = QuizOutputV1(
            title="Test Quiz",
            description="A test",
            subject="English",
            grade="Form 1",
            questions=[q],
            total_points=2.0,
            estimated_duration=15,
        )
        data = output.model_dump(by_alias=True)
        assert data["title"] == "Test Quiz"
        assert data["estimatedDuration"] == 15
        assert data["questions"][0]["questionType"] == "SINGLE_CHOICE"


# ── QuizMeta tests ───────────────────────────────────────────


class TestQuizMeta:
    def test_quiz_meta_creation(self):
        meta = QuizMeta(
            title="Test",
            total_points=10.0,
            question_count=5,
        )
        assert meta.question_count == 5
        assert meta.total_points == 10.0

    def test_quiz_meta_camel_case(self):
        meta = QuizMeta(
            title="Test",
            total_points=10.0,
            question_count=5,
            estimated_duration=20,
        )
        data = meta.model_dump(by_alias=True)
        assert "totalPoints" in data
        assert "questionCount" in data
        assert "estimatedDuration" in data


# ── Conversion helper tests ──────────────────────────────────


class TestConvertPipelineToV1:
    """Tests for pipeline result → V1 conversion."""

    def test_basic_conversion(self):
        """Convert simple pipeline output to V1."""
        questions = [
            {
                "id": "q1",
                "type": "multiple_choice",
                "stem": "What is 2+2?",
                "options": ["3", "4", "5", "6"],
                "answer": "4",
                "explanation": "Basic math",
                "difficulty": "easy",
                "knowledge_point_ids": ["MATH-01"],
            }
        ]
        result = convert_pipeline_to_v1(
            questions,
            title="Math Quiz",
            subject="Math",
        )
        assert result.title == "Math Quiz"
        assert len(result.questions) == 1
        assert result.questions[0].question_type == QuestionTypeV1.SINGLE_CHOICE
        assert result.questions[0].question == "What is 2+2?"
        assert result.questions[0].correct_answer == "4"

    def test_composite_conversion(self):
        """Convert COMPOSITE question with sub_questions."""
        questions = [
            {
                "id": "q5",
                "type": "composite",
                "stem": "Read the passage.",
                "difficulty": "medium",
                "points": 5.0,
                "sub_questions": [
                    {
                        "id": "q5-a",
                        "type": "multiple_choice",
                        "stem": "Main idea?",
                        "options": ["A", "B", "C", "D"],
                        "answer": "B",
                        "explanation": "...",
                        "difficulty": "easy",
                        "points": 2.0,
                    },
                    {
                        "id": "q5-b",
                        "type": "short_answer",
                        "stem": "Explain.",
                        "answer": "Because...",
                        "explanation": "...",
                        "difficulty": "medium",
                        "points": 3.0,
                    },
                ],
            }
        ]
        result = convert_pipeline_to_v1(questions, title="Reading Quiz")
        assert result.questions[0].question_type == QuestionTypeV1.COMPOSITE
        assert result.questions[0].correct_answer is None
        assert len(result.questions[0].sub_questions) == 2
        assert result.questions[0].sub_questions[0].question_type == QuestionTypeV1.SINGLE_CHOICE

    def test_auto_assigns_order(self):
        questions = [
            {"type": "short_answer", "stem": "Q1", "answer": "A1", "difficulty": "easy"},
            {"type": "short_answer", "stem": "Q2", "answer": "A2", "difficulty": "medium"},
        ]
        result = convert_pipeline_to_v1(questions, title="Test")
        assert result.questions[0].order == 1
        assert result.questions[1].order == 2

    def test_auto_calculates_total_points(self):
        questions = [
            {"type": "short_answer", "stem": "Q1", "answer": "A1", "difficulty": "easy", "points": 2.0},
            {"type": "short_answer", "stem": "Q2", "answer": "A2", "difficulty": "medium", "points": 3.0},
        ]
        result = convert_pipeline_to_v1(questions, title="Test")
        assert result.total_points == 5.0


class TestBuildQuizMeta:
    def test_build_from_quiz_output(self):
        q = QuizQuestionV1(
            id="q-001",
            order=1,
            question_type=QuestionTypeV1.SHORT_ANSWER,
            question="Test?",
            correct_answer="Yes",
            difficulty="easy",
            points=2.0,
        )
        quiz = QuizOutputV1(
            title="Test Quiz",
            subject="English",
            questions=[q],
            total_points=2.0,
            estimated_duration=10,
        )
        meta = build_quiz_meta(quiz)
        assert meta.title == "Test Quiz"
        assert meta.subject == "English"
        assert meta.total_points == 2.0
        assert meta.question_count == 1
        assert meta.estimated_duration == 10


class TestValidateQuestionTypes:
    def test_valid_types_pass(self):
        q = QuizQuestionV1(
            id="q-001",
            order=1,
            question_type=QuestionTypeV1.SHORT_ANSWER,
            question="Test?",
            correct_answer="Yes",
            difficulty="easy",
        )
        result = validate_question_types([q])
        assert len(result) == 1

    def test_validates_sub_questions(self):
        sub = QuizQuestionV1(
            id="q-001-a",
            order=1,
            question_type=QuestionTypeV1.SHORT_ANSWER,
            question="Sub Q",
            correct_answer="Yes",
            difficulty="easy",
        )
        composite = QuizQuestionV1(
            id="q-001",
            order=1,
            question_type=QuestionTypeV1.COMPOSITE,
            question="Read.",
            difficulty="medium",
            sub_questions=[sub],
        )
        result = validate_question_types([composite])
        assert len(result) == 1
