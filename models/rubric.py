"""Rubric models — marking schemes and assessment criteria.

Phase 7: These models represent structured rubrics (评分标准) that guide
both LLM-based question generation and scoring. Rubrics are loaded from
the data/rubrics/ directory and can be version-controlled.
"""

from __future__ import annotations

from pydantic import Field

from models.base import CamelModel


class RubricLevel(CamelModel):
    """评分等级描述"""
    level: int  # 1-5 等级
    marks_range: tuple[int, int]  # (min, max) 分数区间
    descriptor: str  # 等级描述 "Excellent command of vocabulary..."
    examples: list[str] = Field(default_factory=list)  # 示例答案片段


class RubricCriterion(CamelModel):
    """单个评分维度"""
    dimension: str  # "organization", "grammar", "vocabulary", "content"
    max_marks: int
    levels: list[RubricLevel] = Field(default_factory=list)
    weight: float = 1.0  # 权重，用于加权评分


class SampleAnswer(CamelModel):
    """样例答案"""
    level: int  # 对应的等级
    answer: str  # 答案内容
    comments: str = ""  # 评语
    marks_awarded: dict[str, int] = Field(default_factory=dict)  # {dimension: marks}


class Rubric(CamelModel):
    """完整评分标准"""
    id: str  # "DSE-ENG-Writing-Argumentative"
    name: str  # 评分标准名称
    subject: str  # 科目
    task_type: str  # "essay", "reading_comprehension", "short_answer", "multiple_choice"
    level: str = "DSE"  # 考试级别
    version: str = "2024"  # 版本号
    total_marks: int  # 总分
    criteria: list[RubricCriterion] = Field(default_factory=list)
    sample_answers: list[SampleAnswer] = Field(default_factory=list)
    instructions: str = ""  # 评分指南
    common_errors: list[str] = Field(default_factory=list)  # 常见错误
