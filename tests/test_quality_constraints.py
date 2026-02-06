"""Tests for Phase 1 quality constraints — difficulty/type distribution, count clamping."""

import pytest

from agents.question_pipeline import (
    MIN_QUESTIONS,
    MAX_QUESTIONS,
    DEFAULT_QUESTION_COUNT,
    DEFAULT_DIFFICULTY_DISTRIBUTION,
    DEFAULT_TYPE_DISTRIBUTION,
    DIFFICULTY_TOLERANCE,
    clamp_question_count,
    compute_target_counts,
    check_difficulty_distribution,
)
from models.question_pipeline import GenerationSpec, QuestionDraft


# ── clamp_question_count ─────────────────────────────────────


class TestClampQuestionCount:
    def test_within_range(self):
        assert clamp_question_count(10) == 10

    def test_below_min(self):
        assert clamp_question_count(0) == MIN_QUESTIONS
        assert clamp_question_count(-5) == MIN_QUESTIONS

    def test_above_max(self):
        assert clamp_question_count(100) == MAX_QUESTIONS
        assert clamp_question_count(51) == MAX_QUESTIONS

    def test_boundary(self):
        assert clamp_question_count(1) == 1
        assert clamp_question_count(50) == 50


# ── compute_target_counts ────────────────────────────────────


class TestComputeTargetCounts:
    def test_default_distribution_10(self):
        """Default difficulty distribution for 10 questions."""
        counts = compute_target_counts(10, DEFAULT_DIFFICULTY_DISTRIBUTION)
        assert counts["easy"] == 3
        assert counts["medium"] == 5
        assert counts["hard"] == 2
        assert sum(counts.values()) == 10

    def test_exact_split(self):
        counts = compute_target_counts(6, {"a": 0.5, "b": 0.5})
        assert counts == {"a": 3, "b": 3}

    def test_remainder_distributed(self):
        """Remainder goes to largest fractional part."""
        counts = compute_target_counts(7, {"a": 0.5, "b": 0.5})
        assert sum(counts.values()) == 7

    def test_single_category(self):
        counts = compute_target_counts(10, {"medium": 1.0})
        assert counts == {"medium": 10}

    def test_type_distribution_10(self):
        """Default type distribution for 10 questions."""
        counts = compute_target_counts(10, DEFAULT_TYPE_DISTRIBUTION)
        assert counts["multiple_choice"] == 6
        assert counts["fill_in_blank"] == 2
        assert counts["true_false"] == 2
        assert sum(counts.values()) == 10

    def test_small_count(self):
        """Small question count still distributes."""
        counts = compute_target_counts(3, DEFAULT_DIFFICULTY_DISTRIBUTION)
        assert sum(counts.values()) == 3

    def test_always_sums_to_total(self):
        """For any count 1-50, result should sum to total."""
        for n in range(1, 51):
            counts = compute_target_counts(n, DEFAULT_DIFFICULTY_DISTRIBUTION)
            assert sum(counts.values()) == n, f"Failed for n={n}"


# ── check_difficulty_distribution ────────────────────────────


class TestCheckDifficultyDistribution:
    def _make_drafts(self, difficulties: list[str]) -> list[QuestionDraft]:
        return [
            QuestionDraft(id=f"q{i}", stem=f"Q{i}", difficulty=d)
            for i, d in enumerate(difficulties)
        ]

    def test_perfect_distribution(self):
        """Exactly matching distribution passes."""
        drafts = self._make_drafts(
            ["easy"] * 3 + ["medium"] * 5 + ["hard"] * 2
        )
        assert check_difficulty_distribution(drafts, DEFAULT_DIFFICULTY_DISTRIBUTION)

    def test_within_tolerance(self):
        """Slightly off distribution still passes within tolerance."""
        # 4 easy (40%) vs target 30% → 10% off, within 20% tolerance
        drafts = self._make_drafts(
            ["easy"] * 4 + ["medium"] * 4 + ["hard"] * 2
        )
        assert check_difficulty_distribution(drafts, DEFAULT_DIFFICULTY_DISTRIBUTION)

    def test_exceeds_tolerance(self):
        """Distribution outside tolerance fails."""
        # 8 easy (80%) vs target 30% → 50% off, way beyond tolerance
        drafts = self._make_drafts(
            ["easy"] * 8 + ["medium"] * 1 + ["hard"] * 1
        )
        assert not check_difficulty_distribution(drafts, DEFAULT_DIFFICULTY_DISTRIBUTION)

    def test_empty_list_passes(self):
        assert check_difficulty_distribution([], DEFAULT_DIFFICULTY_DISTRIBUTION)

    def test_dict_input(self):
        """Works with dict-like questions (not just objects)."""
        questions = [
            {"difficulty": "easy"},
            {"difficulty": "easy"},
            {"difficulty": "easy"},
            {"difficulty": "medium"},
            {"difficulty": "medium"},
            {"difficulty": "medium"},
            {"difficulty": "medium"},
            {"difficulty": "medium"},
            {"difficulty": "hard"},
            {"difficulty": "hard"},
        ]
        assert check_difficulty_distribution(questions, DEFAULT_DIFFICULTY_DISTRIBUTION)


# ── GenerationSpec constraint defaults ───────────────────────


class TestGenerationSpecConstraints:
    def test_default_count(self):
        spec = GenerationSpec()
        assert spec.count == 3  # GenerationSpec default is 3

    def test_difficulty_distribution_default_none(self):
        spec = GenerationSpec()
        assert spec.difficulty_distribution is None

    def test_type_distribution_default_none(self):
        spec = GenerationSpec()
        assert spec.type_distribution is None

    def test_custom_difficulty_distribution(self):
        spec = GenerationSpec(
            difficulty_distribution={"easy": 0.6, "medium": 0.3, "hard": 0.1}
        )
        assert spec.difficulty_distribution["easy"] == 0.6

    def test_custom_type_distribution(self):
        spec = GenerationSpec(
            type_distribution={"multiple_choice": 1.0}
        )
        assert spec.type_distribution["multiple_choice"] == 1.0


# ── Draft prompt includes distribution ───────────────────────


class TestDraftPromptDistribution:
    def setup_method(self):
        from agents.question_pipeline import QuestionPipeline
        self.pipeline = QuestionPipeline.__new__(QuestionPipeline)
        self.pipeline.quality_threshold = 0.7

    def test_prompt_includes_difficulty_distribution(self):
        spec = GenerationSpec(
            count=10,
            difficulty_distribution={"easy": 0.3, "medium": 0.5, "hard": 0.2},
        )
        prompt = self.pipeline._build_draft_prompt(spec, None, None)
        assert "easy 30%" in prompt
        assert "medium 50%" in prompt
        assert "hard 20%" in prompt
        assert "3 easy" in prompt
        assert "5 medium" in prompt
        assert "2 hard" in prompt

    def test_prompt_includes_type_distribution(self):
        spec = GenerationSpec(
            count=10,
            types=["multiple_choice", "fill_in_blank"],
            type_distribution={"multiple_choice": 0.6, "fill_in_blank": 0.4},
        )
        prompt = self.pipeline._build_draft_prompt(spec, None, None)
        assert "multiple_choice 60%" in prompt
        assert "fill_in_blank 40%" in prompt

    def test_prompt_no_distribution_when_none(self):
        spec = GenerationSpec(count=5)
        prompt = self.pipeline._build_draft_prompt(spec, None, None)
        assert "distribution" not in prompt.lower() or "Difficulty distribution" not in prompt

    def test_prompt_says_exactly_count(self):
        spec = GenerationSpec(count=7)
        prompt = self.pipeline._build_draft_prompt(spec, None, None)
        assert "exactly 7 questions" in prompt
