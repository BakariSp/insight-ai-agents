"""Internal data models — the canonical representation used by tools, Planner, and Executor.

These models decouple the AI system from the Java backend's response format.
Adapters in ``adapters/`` convert Java DTOs → these internal models.
Tools return dicts derived from these models so existing Planner/Executor code
continues to work without changes.

Phase 7 additions:
- QuestionItem: 单道题目的作答记录
- QuestionSpec: 题库中的题目定义
- KnowledgePoint: 知识点定义
- ErrorPattern: 学生错误模式分析
- StudentMastery: 学生知识点掌握度
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Phase 7: Assessment & Knowledge Point Models
# ---------------------------------------------------------------------------

class QuestionItem(BaseModel):
    """单道题目的作答记录"""
    question_id: str
    score: float = 0
    max_score: float = 1
    correct: bool = False
    error_tags: list[str] = Field(default_factory=list)  # ["grammar", "inference", "vocabulary"]
    knowledge_point_ids: list[str] = Field(default_factory=list)  # ["DSE-ENG-U5-RC-01"]


class QuestionSpec(BaseModel):
    """题库中的题目定义"""
    question_id: str
    type: str = ""  # "multiple_choice", "short_answer", "essay"
    skill_tags: list[str] = Field(default_factory=list)
    knowledge_point_ids: list[str] = Field(default_factory=list)
    difficulty: str = "medium"  # "easy", "medium", "hard"
    max_score: float = 1


class KnowledgePoint(BaseModel):
    """知识点定义"""
    id: str  # "DSE-ENG-U5-RC-01"
    name: str  # "Reading Comprehension - Main Idea"
    subject: str = ""
    unit: str = ""
    level: str = "DSE"
    description: str = ""
    skill_tags: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    difficulty: str = "medium"


class ErrorPattern(BaseModel):
    """学生错误模式分析"""
    student_id: str
    knowledge_point_id: str
    error_count: int = 0
    total_attempts: int = 0
    error_rate: float = 0.0
    common_error_tags: list[str] = Field(default_factory=list)


class StudentMastery(BaseModel):
    """学生知识点掌握度"""
    student_id: str
    knowledge_point_id: str
    mastery_rate: float = 0.0  # 0.0 ~ 1.0
    last_assessed: str | None = None


# ---------------------------------------------------------------------------
# Class / Classroom
# ---------------------------------------------------------------------------

class ClassInfo(BaseModel):
    """Summary of a classroom (used in class lists)."""
    class_id: str
    name: str
    grade: str = ""
    subject: str = ""
    student_count: int = 0
    assignment_count: int = 0
    description: str = ""
    semester_label: str = ""


class StudentInfo(BaseModel):
    """A student within a class."""
    student_id: str
    name: str
    number: str = ""
    email: str = ""


class AssignmentInfo(BaseModel):
    """Summary of an assignment."""
    assignment_id: str
    title: str
    type: str = ""
    max_score: float = 100
    status: str = ""
    due_date: str | None = None
    submission_count: int = 0
    guest_submission_count: int = 0
    total_students: int = 0
    average_score: float | None = None


class ClassDetail(BaseModel):
    """Full class detail including roster and assignments."""
    class_id: str
    name: str
    grade: str = ""
    subject: str = ""
    student_count: int = 0
    students: list[StudentInfo] = Field(default_factory=list)
    assignments: list[AssignmentInfo] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------

class SubmissionRecord(BaseModel):
    """A single student or guest submission for an assignment."""
    student_id: str
    name: str
    score: float | None = None
    submitted: bool = True
    status: str = ""
    feedback: str = ""
    submission_type: str = "student"  # "student" | "guest"
    identity_type: str = "registered_account"  # "registered_account" | "guest_name"
    # Phase 7: 题目级明细
    items: list[QuestionItem] = Field(default_factory=list)


class SubmissionData(BaseModel):
    """All submissions for a specific assignment."""
    assignment_id: str
    title: str = ""
    class_id: str = ""
    max_score: float = 100
    submissions: list[SubmissionRecord] = Field(default_factory=list)
    scores: list[float] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Grades
# ---------------------------------------------------------------------------

class GradeRecord(BaseModel):
    """A single grade entry for a student."""
    assignment_id: str
    title: str = ""
    score: float = 0
    max_score: float = 100
    percentage: float | None = None


class GradeData(BaseModel):
    """All grades for a specific student."""
    student_id: str
    name: str = ""
    class_id: str = ""
    average_score: float | None = None
    highest_score: float | None = None
    total_graded: int = 0
    grades: list[GradeRecord] = Field(default_factory=list)
