"""Internal data models — the canonical representation used by tools, Planner, and Executor.

These models decouple the AI system from the Java backend's response format.
Adapters in ``adapters/`` convert Java DTOs → these internal models.
Tools return dicts derived from these models so existing Planner/Executor code
continues to work without changes.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


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
    number: int = 0
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
    """A single student's submission for an assignment."""
    student_id: str
    name: str
    score: float | None = None
    submitted: bool = True
    status: str = ""
    feedback: str = ""


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
