"""Question generation pipeline models.

Phase 7: Models for the three-stage question generation pipeline:
Draft → Judge → Repair

These models track questions through the generation process, capturing
quality issues and repair attempts.
"""

from __future__ import annotations

from enum import Enum
from pydantic import Field

from models.base import CamelModel


class QuestionType(str, Enum):
    """Supported question types."""
    MULTIPLE_CHOICE = "multiple_choice"
    SHORT_ANSWER = "short_answer"
    ESSAY = "essay"
    FILL_IN_BLANK = "fill_in_blank"
    TRUE_FALSE = "true_false"
    MATCHING = "matching"
    ORDERING = "ordering"
    COMPOSITE = "composite"


class Difficulty(str, Enum):
    """Question difficulty levels."""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class IssueSeverity(str, Enum):
    """Quality issue severity levels."""
    ERROR = "error"      # Must fix before use
    WARNING = "warning"  # Should fix, but usable
    SUGGESTION = "suggestion"  # Optional improvement


class IssueType(str, Enum):
    """Types of quality issues in questions."""
    AMBIGUOUS = "ambiguous"  # 题意不明确
    MULTI_ANSWER = "multi_answer"  # 多个正确答案
    OFF_TOPIC = "off_topic"  # 偏离知识点
    DIFFICULTY_MISMATCH = "difficulty_mismatch"  # 难度不匹配
    ANSWER_INCONSISTENT = "answer_inconsistent"  # 答案与解释不一致
    GRAMMAR_ERROR = "grammar_error"  # 语法错误
    INCOMPLETE = "incomplete"  # 题目不完整
    TOO_EASY = "too_easy"  # 过于简单
    TOO_HARD = "too_hard"  # 过于困难


class QuestionDraft(CamelModel):
    """LLM 生成的题目草稿"""
    id: str
    type: str = QuestionType.SHORT_ANSWER.value
    stem: str  # 题干
    options: list[str] | None = None  # 选择题选项
    answer: str = ""  # COMPOSITE root may have no answer
    explanation: str = ""
    knowledge_point_ids: list[str] = Field(default_factory=list)
    difficulty: str = Difficulty.MEDIUM.value
    rubric_ref: str | None = None  # 引用的 rubric ID
    skill_tags: list[str] = Field(default_factory=list)
    sub_questions: list[QuestionDraft] | None = None  # COMPOSITE 子题


class QualityIssue(CamelModel):
    """题目质量问题"""
    issue_type: str  # IssueType value
    severity: str = IssueSeverity.WARNING.value
    description: str
    suggestion: str = ""
    affected_field: str = ""  # "stem", "options", "answer", "explanation"


class JudgeResult(CamelModel):
    """质量评审结果"""
    question_id: str
    passed: bool
    issues: list[QualityIssue] = Field(default_factory=list)
    score: float = 0.0  # 0.0 ~ 1.0 质量分
    feedback: str = ""


class QuestionFinal(CamelModel):
    """最终通过的题目"""
    id: str
    type: str
    stem: str
    options: list[str] | None = None
    answer: str = ""  # COMPOSITE root may have no answer
    explanation: str = ""
    knowledge_point_ids: list[str] = Field(default_factory=list)
    difficulty: str
    rubric_ref: str | None = None
    skill_tags: list[str] = Field(default_factory=list)
    quality_score: float = 0.0
    version: int = 1
    passed_quality_gate: bool = True
    repair_count: int = 0  # Number of repair iterations
    sub_questions: list[QuestionFinal] | None = None  # COMPOSITE 子题


class GenerationSpec(CamelModel):
    """题目生成规格"""
    count: int = 3  # 生成题目数量
    types: list[str] = Field(default_factory=lambda: [QuestionType.SHORT_ANSWER.value])
    difficulty: str = Difficulty.MEDIUM.value
    subject: str = ""
    topic: str = ""
    grade: str = ""
    knowledge_points: list[str] = Field(default_factory=list)
    rubric_ref: str | None = None
    target_students: list[str] = Field(default_factory=list)  # 针对的学生 ID
    avoid_similar_to: list[str] = Field(default_factory=list)  # 避免与这些题目相似
    # Phase 1 quality constraints
    difficulty_distribution: dict[str, float] | None = None  # e.g. {"easy": 0.3, "medium": 0.5, "hard": 0.2}
    type_distribution: dict[str, float] | None = None  # e.g. {"multiple_choice": 0.6, "fill_in_blank": 0.2, "true_false": 0.2}


class PipelineResult(CamelModel):
    """流水线执行结果"""
    questions: list[QuestionFinal] = Field(default_factory=list)
    total_generated: int = 0
    total_passed: int = 0
    total_repaired: int = 0
    total_failed: int = 0
    average_quality_score: float = 0.0
