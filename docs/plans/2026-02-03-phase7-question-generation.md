# Plan: Phase 7 — 智能题目生成与学情分析优化

**Goal:** 将题目生成从"纯 LLM 猜测"升级为"标准库检索 + 学情驱动 + 结构化输出"，实现可用、可控、可持续迭代的出题能力。

**Date:** 2026-02-03

**Background:** 基于 E2E 测试暴露的系统性问题（kpi_grid 空数据、SLOT_DELTA JSON 字符串、题目级数据缺失）和 HK DSE 体系的需求，制定分优先级的实施方案。

---

## 1. 现状分析与问题诊断

### 1.1 E2E 测试暴露的问题

| 问题 | 现象 | 根因 | 文件位置 |
|------|------|------|----------|
| **kpi_grid 空数据** | `"data": []` 在 sample-page.json | Blueprint 绑定 `$compute.scoreStats.summary`，但 `calculate_stats` 没有 `summary` 字段 | `tools/stats_tools.py:29-56` |
| **SLOT_DELTA JSON 字符串** | suggestion_list items 是字符串化 JSON | SSE 传输把结构化数据序列化为字符串 | `agents/executor.py` SLOT_DELTA 事件 |
| **题目级数据缺失** | 只能分析"分数→统计"，无法"题目→知识点→薄弱点→出题" | `SubmissionRecord` 只有 score，没有 questionId/items/errorTags | `models/data.py:66-73` |

### 1.2 数据模型缺口

**当前 SubmissionRecord:**
```python
class SubmissionRecord(BaseModel):
    student_id: str
    name: str
    score: float | None = None
    submitted: bool = True
    status: str = ""
    feedback: str = ""
    # 缺少: items[], errorTags[], knowledgePointIds[]
```

**缺失的数据结构:**
- 题目级数据 (`QuestionItem`)
- 知识点定义 (`KnowledgePoint`)
- 评分标准 (`Rubric`)
- 学生错误模式 (`ErrorPattern`)

### 1.3 当前能力 vs 目标能力

| 能力 | 当前 | 目标 |
|------|------|------|
| 学情分析 | 分数统计（mean/median/distribution） | 知识点掌握度 + 错题模式 + 薄弱点识别 |
| 题目生成 | LLM 纯生成（靠猜） | Rubric 驱动 + 学情适配 + 质量闸门 |
| 数据流 | submission → scores → stats | submission → items → questions → knowledge_points → mastery |

---

## 2. 优先级分层

### P0（必须先做，本周）
> 不做则出题/教案质量上不去

- **P0-1:** 题目级数据模型 + 错题数据接入
- **P0-2:** Blueprint→Page 结构一致性修复
- **P0-3:** Rubric-as-Assets（人工整理的最小标准库）
- **P0-4:** 题目生成流水线 Draft→Judge→Repair

### P1（重要优化，两周内）
> 形成"标准库驱动"的题目生产线

- **P1-1:** RAG 基础设施（分库 + 版本化 + 评测集）
- **P1-2:** 知识点字典（先字典后图谱）

### P2（护城河，中长期）
> 让系统"可改进"

- **P2-1:** Teacher-in-the-loop 数据闭环
- **P2-2:** 混合生成策略（题库检索优先 + LLM 变体）

---

## 3. P0 任务分解

### Step P0-1: 题目级数据模型 (Assessment Data Model)

**目标:** 补齐"学情→知识点"的数据基础，支持薄弱点分析和针对性出题。

#### Task P0-1.1: 扩展 models/data.py

**新增数据模型:**

```python
# models/data.py 新增

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
```

#### Task P0-1.2: 扩展 SubmissionRecord

**修改 models/data.py:**

```python
class SubmissionRecord(BaseModel):
    """A single student's submission for an assignment."""
    student_id: str
    name: str
    score: float | None = None
    submitted: bool = True
    status: str = ""
    feedback: str = ""
    # Phase 7 新增
    items: list[QuestionItem] = Field(default_factory=list)  # 题目级明细
```

#### Task P0-1.3: 新增工具 — 知识点掌握度分析

**新建 tools/assessment_tools.py:**

```python
@mcp.tool()
async def analyze_student_weakness(
    teacher_id: str,
    class_id: str,
    subject: str = "",
) -> dict:
    """
    分析班级学生的薄弱知识点

    Returns:
        {
            "classId": "...",
            "weakPoints": [
                {"knowledgePointId": "...", "errorRate": 0.45, "affectedStudents": 12}
            ],
            "recommendedFocus": ["knowledge_point_id_1", "knowledge_point_id_2"]
        }
    """
    # 实现: 聚合 items 的 error_tags → 关联 knowledge_point_ids → 计算错误率
    ...


@mcp.tool()
async def get_student_error_patterns(
    teacher_id: str,
    student_id: str,
    class_id: str = "",
) -> dict:
    """
    获取单个学生的错误模式

    Returns:
        {
            "studentId": "...",
            "errorPatterns": [
                {"knowledgePointId": "...", "errorCount": 3, "errorTags": ["grammar"]}
            ]
        }
    """
    ...
```

**验证:**
```bash
pytest tests/test_assessment_tools.py -v
```

---

### Step P0-2: Blueprint→Page 结构一致性修复

**目标:** 修复 kpi_grid 空数据和 SLOT_DELTA JSON 字符串问题，为 question_generator 的复杂 JSON 做铺垫。

#### Task P0-2.1: 修复 calculate_stats 输出

**修改 tools/stats_tools.py:**

```python
def calculate_stats(data: list[float | int], metrics: list[str] | None = None) -> dict:
    # ... 现有代码 ...

    # 新增: summary 字段，适配 kpi_grid 组件
    if "summary" in all_metrics or "mean" in all_metrics:
        result["summary"] = [
            {"label": "平均分", "value": result.get("mean", 0), "unit": "分"},
            {"label": "最高分", "value": result.get("max", 0), "unit": "分"},
            {"label": "最低分", "value": result.get("min", 0), "unit": "分"},
            {"label": "标准差", "value": result.get("stddev", 0), "unit": ""},
            {"label": "样本数", "value": result.get("count", 0), "unit": "人"},
        ]

    return result
```

#### Task P0-2.2: 修复 SLOT_DELTA 结构化传输

**修改 agents/executor.py 的 `_stream_ai_content()`:**

选项 A（推荐）: SLOT_COMPLETE 事件传结构化数据
```python
# 在 BLOCK_COMPLETE 之前添加 SLOT_COMPLETE
yield {
    "type": "SLOT_COMPLETE",
    "blockId": block_id,
    "slotKey": slot_key,
    "data": ai_content,  # 结构化数据，而非字符串
}
```

选项 B: 保持 SLOT_DELTA 但标记 format
```python
yield {
    "type": "SLOT_DELTA",
    "blockId": block_id,
    "slotKey": slot_key,
    "deltaText": delta_text,
    "format": "json" if isinstance(ai_content, (list, dict)) else "text",
}
```

#### Task P0-2.3: 更新 Planner Prompt 约束

**修改 config/prompts/planner.py:**

```python
# 新增规则
"""
## Rule 11: kpi_grid dataBinding 必须指向有 summary 字段的数据
- 正确: $compute.scoreStats.summary
- 工具 calculate_stats 已保证返回 summary 字段

## Rule 12: 确保 dataBinding 路径存在
- 在指定 dataBinding 前，确认目标工具的输出结构
- calculate_stats 返回: count, mean, median, stddev, min, max, percentiles, distribution, summary
"""
```

**验证:**
```bash
pytest tests/test_stats_tools.py -v
pytest tests/test_executor.py -v -k "slot"
```

---

### Step P0-3: Rubric-as-Assets（最小标准库）

**目标:** 建立人工整理的高频题型评分标准，作为 LLM 生成的约束参照。

#### Task P0-3.1: 创建 Rubric 数据结构

**新建 models/rubric.py:**

```python
"""Rubric models — marking schemes and assessment criteria."""

from __future__ import annotations
from pydantic import Field
from models.base import CamelModel


class RubricCriterion(CamelModel):
    """单个评分维度"""
    dimension: str  # "organization", "grammar", "vocabulary", "content"
    max_marks: int
    levels: list[RubricLevel] = Field(default_factory=list)


class RubricLevel(CamelModel):
    """评分等级描述"""
    level: int  # 1-5 或百分比区间
    marks_range: tuple[int, int]  # (min, max)
    descriptor: str  # "Excellent command of vocabulary..."
    examples: list[str] = Field(default_factory=list)


class Rubric(CamelModel):
    """完整评分标准"""
    id: str  # "DSE-ENG-Writing-Argumentative"
    name: str
    subject: str
    task_type: str  # "essay", "reading_comprehension", "short_answer"
    level: str = "DSE"
    version: str = "2024"
    total_marks: int
    criteria: list[RubricCriterion] = Field(default_factory=list)
    sample_answers: list[dict] = Field(default_factory=list)
```

#### Task P0-3.2: 创建 DSE 英语写作 Rubric 示例

**新建 data/rubrics/dse-eng-writing-argumentative.json:**

```json
{
  "id": "DSE-ENG-Writing-Argumentative",
  "name": "DSE English Writing - Argumentative Essay",
  "subject": "English",
  "taskType": "essay",
  "level": "DSE",
  "version": "2024",
  "totalMarks": 21,
  "criteria": [
    {
      "dimension": "content",
      "maxMarks": 7,
      "levels": [
        {"level": 5, "marksRange": [6, 7], "descriptor": "Fully addresses the task with well-developed, relevant ideas", "examples": []},
        {"level": 4, "marksRange": [5, 5], "descriptor": "Addresses the task with mostly relevant ideas", "examples": []},
        {"level": 3, "marksRange": [3, 4], "descriptor": "Partially addresses the task with some relevant ideas", "examples": []},
        {"level": 2, "marksRange": [2, 2], "descriptor": "Limited response to the task", "examples": []},
        {"level": 1, "marksRange": [0, 1], "descriptor": "Fails to address the task", "examples": []}
      ]
    },
    {
      "dimension": "organization",
      "maxMarks": 7,
      "levels": [
        {"level": 5, "marksRange": [6, 7], "descriptor": "Coherent and well-organized with clear paragraphing", "examples": []},
        {"level": 4, "marksRange": [5, 5], "descriptor": "Generally organized with adequate paragraphing", "examples": []},
        {"level": 3, "marksRange": [3, 4], "descriptor": "Some organization evident", "examples": []},
        {"level": 2, "marksRange": [2, 2], "descriptor": "Limited organization", "examples": []},
        {"level": 1, "marksRange": [0, 1], "descriptor": "No clear organization", "examples": []}
      ]
    },
    {
      "dimension": "language",
      "maxMarks": 7,
      "levels": [
        {"level": 5, "marksRange": [6, 7], "descriptor": "Wide range of vocabulary and grammatical structures with minimal errors", "examples": []},
        {"level": 4, "marksRange": [5, 5], "descriptor": "Good range of vocabulary and structures with occasional errors", "examples": []},
        {"level": 3, "marksRange": [3, 4], "descriptor": "Adequate vocabulary and structures with noticeable errors", "examples": []},
        {"level": 2, "marksRange": [2, 2], "descriptor": "Limited vocabulary and structures with frequent errors", "examples": []},
        {"level": 1, "marksRange": [0, 1], "descriptor": "Very limited language that impedes communication", "examples": []}
      ]
    }
  ]
}
```

#### Task P0-3.3: Rubric 加载服务

**新建 services/rubric_service.py:**

```python
"""Rubric loading and retrieval service."""

import json
from pathlib import Path
from functools import lru_cache
from models.rubric import Rubric

RUBRIC_DIR = Path(__file__).parent.parent / "data" / "rubrics"


@lru_cache(maxsize=32)
def load_rubric(rubric_id: str) -> Rubric | None:
    """Load a rubric by ID from the data/rubrics directory."""
    file_path = RUBRIC_DIR / f"{rubric_id.lower()}.json"
    if not file_path.exists():
        return None

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Rubric(**data)


def list_rubrics(subject: str = "", task_type: str = "") -> list[dict]:
    """List available rubrics, optionally filtered by subject/task_type."""
    rubrics = []
    for file_path in RUBRIC_DIR.glob("*.json"):
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if subject and data.get("subject", "").lower() != subject.lower():
            continue
        if task_type and data.get("taskType", "").lower() != task_type.lower():
            continue
        rubrics.append({
            "id": data["id"],
            "name": data["name"],
            "subject": data.get("subject", ""),
            "taskType": data.get("taskType", ""),
        })
    return rubrics
```

#### Task P0-3.4: 新增工具 — 获取 Rubric

**在 tools/__init__.py 注册:**

```python
@mcp.tool()
async def get_rubric(
    subject: str,
    task_type: str,
    level: str = "DSE",
) -> dict:
    """
    获取指定科目和题型的评分标准

    Args:
        subject: 科目 (e.g., "English", "Chinese", "Math")
        task_type: 题型 (e.g., "essay", "reading_comprehension", "short_answer")
        level: 考试级别 (默认 "DSE")

    Returns:
        评分标准结构，包含 criteria, levels, sample_answers
    """
    from services.rubric_service import load_rubric, list_rubrics

    # 查找匹配的 rubric
    candidates = list_rubrics(subject=subject, task_type=task_type)
    if not candidates:
        return {"error": f"No rubric found for {subject} {task_type}"}

    rubric = load_rubric(candidates[0]["id"])
    if not rubric:
        return {"error": "Failed to load rubric"}

    return rubric.model_dump(by_alias=True)
```

**验证:**
```bash
pytest tests/test_rubric_service.py -v
```

---

### Step P0-4: 题目生成流水线 Draft→Judge→Repair

**目标:** 设计可用率提升的关键环节——自动评审与返工。

#### Task P0-4.1: 定义流水线数据模型

**新建 models/question_pipeline.py:**

```python
"""Question generation pipeline models."""

from __future__ import annotations
from enum import Enum
from pydantic import Field
from models.base import CamelModel


class QuestionDraft(CamelModel):
    """LLM 生成的题目草稿"""
    id: str
    type: str  # "multiple_choice", "short_answer", "essay"
    stem: str  # 题干
    options: list[str] | None = None  # 选择题选项
    answer: str
    explanation: str = ""
    knowledge_point_ids: list[str] = Field(default_factory=list)
    difficulty: str = "medium"
    rubric_ref: str | None = None  # 引用的 rubric ID


class QualityIssue(CamelModel):
    """题目质量问题"""
    issue_type: str  # "ambiguous", "multi_answer", "off_topic", "difficulty_mismatch", "answer_inconsistent"
    severity: str  # "error", "warning", "suggestion"
    description: str
    suggestion: str = ""


class JudgeResult(CamelModel):
    """质量评审结果"""
    question_id: str
    passed: bool
    issues: list[QualityIssue] = Field(default_factory=list)
    score: float = 0.0  # 0.0 ~ 1.0 质量分


class QuestionFinal(CamelModel):
    """最终通过的题目"""
    id: str
    type: str
    stem: str
    options: list[str] | None = None
    answer: str
    explanation: str
    knowledge_point_ids: list[str] = Field(default_factory=list)
    difficulty: str
    rubric_ref: str | None = None
    quality_score: float = 0.0
    version: int = 1
```

#### Task P0-4.2: 创建 QuestionPipeline Agent

**新建 agents/question_pipeline.py:**

```python
"""Question generation pipeline — Draft → Judge → Repair."""

from __future__ import annotations
import logging
from typing import Any

from pydantic_ai import Agent

from agents.provider import create_model
from config.settings import get_settings
from models.question_pipeline import QuestionDraft, JudgeResult, QualityIssue, QuestionFinal
from services.rubric_service import load_rubric

logger = logging.getLogger(__name__)


class QuestionPipeline:
    """Three-stage question generation pipeline."""

    def __init__(self, model: str | None = None):
        settings = get_settings()
        self.model = create_model(model or settings.executor_model)

    async def generate_draft(
        self,
        spec: dict[str, Any],
        rubric_context: dict | None = None,
        weakness_context: dict | None = None,
    ) -> list[QuestionDraft]:
        """Stage 1: Generate question drafts."""
        prompt = self._build_draft_prompt(spec, rubric_context, weakness_context)

        agent = Agent(
            model=self.model,
            system_prompt="You are an expert question writer for educational assessments.",
            defer_model_check=True,
        )

        result = await agent.run(prompt)
        return self._parse_drafts(result.output, spec)

    async def judge_question(
        self,
        draft: QuestionDraft,
        rubric_context: dict | None = None,
    ) -> JudgeResult:
        """Stage 2: Evaluate question quality."""
        prompt = self._build_judge_prompt(draft, rubric_context)

        agent = Agent(
            model=self.model,
            system_prompt="You are a quality assurance expert for educational assessments. Identify issues with questions.",
            defer_model_check=True,
        )

        result = await agent.run(prompt)
        return self._parse_judge_result(result.output, draft.id)

    async def repair_question(
        self,
        draft: QuestionDraft,
        issues: list[QualityIssue],
    ) -> QuestionDraft:
        """Stage 3: Fix identified issues."""
        if not issues:
            return draft

        prompt = self._build_repair_prompt(draft, issues)

        agent = Agent(
            model=self.model,
            system_prompt="You are an expert at refining educational assessment questions.",
            defer_model_check=True,
        )

        result = await agent.run(prompt)
        return self._parse_repaired_draft(result.output, draft)

    async def run_pipeline(
        self,
        spec: dict[str, Any],
        rubric_context: dict | None = None,
        weakness_context: dict | None = None,
        max_repair_rounds: int = 2,
    ) -> list[QuestionFinal]:
        """Run the full Draft → Judge → Repair pipeline."""
        # Stage 1: Generate drafts
        drafts = await self.generate_draft(spec, rubric_context, weakness_context)

        final_questions: list[QuestionFinal] = []

        for draft in drafts:
            current_draft = draft

            for round_num in range(max_repair_rounds + 1):
                # Stage 2: Judge
                judge_result = await self.judge_question(current_draft, rubric_context)

                if judge_result.passed:
                    # Passed quality gate
                    final_questions.append(self._finalize(current_draft, judge_result.score))
                    break

                if round_num < max_repair_rounds:
                    # Stage 3: Repair
                    current_draft = await self.repair_question(current_draft, judge_result.issues)
                else:
                    # Max repairs reached, include with warning
                    logger.warning("Question %s failed quality gate after %d repairs", draft.id, max_repair_rounds)
                    final_questions.append(self._finalize(current_draft, judge_result.score, passed=False))

        return final_questions

    def _build_draft_prompt(self, spec: dict, rubric_context: dict | None, weakness_context: dict | None) -> str:
        """Build prompt for draft generation."""
        parts = [
            f"Generate {spec.get('count', 3)} questions with the following requirements:",
            f"- Subject: {spec.get('subject', 'General')}",
            f"- Topic: {spec.get('topic', '')}",
            f"- Type: {spec.get('types', ['short_answer'])}",
            f"- Difficulty: {spec.get('difficulty', 'medium')}",
            f"- Target knowledge points: {spec.get('knowledge_points', [])}",
        ]

        if rubric_context:
            parts.append(f"\n## Rubric Reference\n{rubric_context}")

        if weakness_context:
            parts.append(f"\n## Student Weakness Context\nFocus on these weak areas: {weakness_context}")

        parts.append("""
## Output Format
Return a JSON array of question objects:
```json
[
  {
    "id": "q1",
    "type": "multiple_choice",
    "stem": "Question text...",
    "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
    "answer": "B",
    "explanation": "Because...",
    "knowledgePointIds": ["..."],
    "difficulty": "medium"
  }
]
```
""")
        return "\n".join(parts)

    def _build_judge_prompt(self, draft: QuestionDraft, rubric_context: dict | None) -> str:
        """Build prompt for quality judgment."""
        return f"""
Evaluate this question for quality issues:

## Question
- ID: {draft.id}
- Type: {draft.type}
- Stem: {draft.stem}
- Options: {draft.options}
- Answer: {draft.answer}
- Explanation: {draft.explanation}

## Check for these issues:
1. **ambiguous**: Is the question clear and unambiguous?
2. **multi_answer**: Does the question have exactly one correct answer?
3. **off_topic**: Does the question align with the specified knowledge points?
4. **difficulty_mismatch**: Is the difficulty appropriate ({draft.difficulty})?
5. **answer_inconsistent**: Is the answer consistent with the explanation?

## Output Format
Return a JSON object:
```json
{{
  "passed": true/false,
  "issues": [
    {{"issueType": "...", "severity": "error/warning/suggestion", "description": "...", "suggestion": "..."}}
  ],
  "score": 0.0-1.0
}}
```
"""

    def _build_repair_prompt(self, draft: QuestionDraft, issues: list[QualityIssue]) -> str:
        """Build prompt for question repair."""
        issue_text = "\n".join([f"- {i.issue_type}: {i.description} (Suggestion: {i.suggestion})" for i in issues])

        return f"""
Fix the following issues with this question:

## Original Question
- Stem: {draft.stem}
- Options: {draft.options}
- Answer: {draft.answer}
- Explanation: {draft.explanation}

## Issues to Fix
{issue_text}

## Output Format
Return the corrected question as JSON:
```json
{{
  "id": "{draft.id}",
  "type": "{draft.type}",
  "stem": "...",
  "options": [...],
  "answer": "...",
  "explanation": "...",
  "knowledgePointIds": {draft.knowledge_point_ids},
  "difficulty": "{draft.difficulty}"
}}
```
"""

    def _parse_drafts(self, output: str, spec: dict) -> list[QuestionDraft]:
        """Parse LLM output into QuestionDraft objects."""
        import json
        import re

        text = str(output).strip()
        code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if code_block_match:
            text = code_block_match.group(1).strip()

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [QuestionDraft(**item) for item in data]
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Failed to parse drafts: %s", e)

        return []

    def _parse_judge_result(self, output: str, question_id: str) -> JudgeResult:
        """Parse LLM output into JudgeResult."""
        import json
        import re

        text = str(output).strip()
        code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if code_block_match:
            text = code_block_match.group(1).strip()

        try:
            data = json.loads(text)
            return JudgeResult(
                question_id=question_id,
                passed=data.get("passed", False),
                issues=[QualityIssue(**i) for i in data.get("issues", [])],
                score=data.get("score", 0.5),
            )
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Failed to parse judge result: %s", e)
            return JudgeResult(question_id=question_id, passed=True, score=0.5)

    def _parse_repaired_draft(self, output: str, original: QuestionDraft) -> QuestionDraft:
        """Parse LLM output into repaired QuestionDraft."""
        import json
        import re

        text = str(output).strip()
        code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if code_block_match:
            text = code_block_match.group(1).strip()

        try:
            data = json.loads(text)
            return QuestionDraft(**data)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Failed to parse repaired draft: %s", e)
            return original

    def _finalize(self, draft: QuestionDraft, score: float, passed: bool = True) -> QuestionFinal:
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
            quality_score=score if passed else score * 0.5,
        )
```

#### Task P0-4.3: 集成到 Executor block_compose

**修改 config/prompts/block_compose.py 的 `_build_question_prompt()`:**

```python
def _build_question_prompt(
    slot: ComponentSlot,
    blueprint: Blueprint,
    data_summary: str,
) -> str:
    """Build prompt for question_generator JSON content — using pipeline."""
    slot_props = slot.props or {}

    # 检查是否使用 pipeline 模式
    use_pipeline = slot_props.get("usePipeline", True)

    if use_pipeline:
        # 返回 pipeline 配置，由 Executor 调用 QuestionPipeline
        return json.dumps({
            "_pipeline": True,
            "spec": {
                "count": slot_props.get("count", 5),
                "types": slot_props.get("types", ["multiple_choice", "short_answer"]),
                "difficulty": slot_props.get("difficulty", "medium"),
                "subject": slot_props.get("subject", ""),
                "topic": slot_props.get("knowledgePoint", ""),
                "knowledge_points": slot_props.get("knowledgePoints", []),
            },
            "rubricRef": slot_props.get("rubricRef"),
            "weaknessRef": slot_props.get("studentWeakness"),
        }), "pipeline"

    # Fallback to direct LLM generation (original behavior)
    # ... 原有代码 ...
```

**修改 agents/executor.py 的 `_generate_block_content()`:**

```python
async def _generate_block_content(self, slot, blueprint, data_context, compute_results):
    prompt, output_format = build_block_prompt(slot, blueprint, data_context, compute_results)

    # 检查是否是 pipeline 模式
    if output_format == "pipeline":
        config = json.loads(prompt)
        if config.get("_pipeline"):
            from agents.question_pipeline import QuestionPipeline

            pipeline = QuestionPipeline()

            # 获取 rubric 和 weakness 上下文
            rubric_context = None
            if config.get("rubricRef"):
                rubric_data = data_context.get(config["rubricRef"].replace("$data.", ""))
                if rubric_data:
                    rubric_context = rubric_data

            weakness_context = None
            if config.get("weaknessRef"):
                weakness_data = data_context.get(config["weaknessRef"].replace("$data.", ""))
                if weakness_data:
                    weakness_context = weakness_data

            questions = await pipeline.run_pipeline(
                spec=config["spec"],
                rubric_context=rubric_context,
                weakness_context=weakness_context,
            )

            return [q.model_dump(by_alias=True) for q in questions]

    # 原有逻辑...
```

**验证:**
```bash
pytest tests/test_question_pipeline.py -v
```

---

## 4. P1 任务分解

### Step P1-1: RAG 基础设施

**目标:** 建立分库、版本化、可评测的 RAG 系统。

#### Task P1-1.1: 选择 RAG 技术栈

**推荐方案:**
- **向量库:** Chroma（轻量、嵌入式、开箱即用）
- **Embedding:** OpenAI text-embedding-3-small 或 local sentence-transformers
- **框架:** LlamaIndex（一站式 RAG 框架）

**新增依赖 (requirements.txt):**
```
chromadb>=0.4.0
llama-index>=0.10.0
sentence-transformers>=2.2.0  # 可选，本地 embedding
```

#### Task P1-1.2: 创建 RAG 分库结构

**新建 services/rag_service.py:**

```python
"""RAG service for curriculum and rubric retrieval."""

from pathlib import Path
from functools import lru_cache
import chromadb
from chromadb.config import Settings

# 分库设计
COLLECTIONS = {
    "official_corpus": "官方课纲、考纲、评分标准",
    "school_assets": "校本教案、题库、老师自建 rubric",
    "question_bank": "题目库（按知识点索引）",
}


class CurriculumRAG:
    """DSE 课纲 RAG 服务"""

    def __init__(self, persist_dir: str = "data/rag"):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )

        # 初始化分库
        self.collections = {}
        for name, desc in COLLECTIONS.items():
            self.collections[name] = self.client.get_or_create_collection(
                name=name,
                metadata={"description": desc},
            )

    def add_document(
        self,
        collection: str,
        doc_id: str,
        content: str,
        metadata: dict | None = None,
        version: str = "v1",
    ):
        """添加文档到指定分库"""
        if collection not in self.collections:
            raise ValueError(f"Unknown collection: {collection}")

        meta = metadata or {}
        meta["version"] = version

        self.collections[collection].add(
            documents=[content],
            ids=[doc_id],
            metadatas=[meta],
        )

    def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        """查询相关文档"""
        if collection not in self.collections:
            raise ValueError(f"Unknown collection: {collection}")

        results = self.collections[collection].query(
            query_texts=[query_text],
            n_results=n_results,
            where=where,
        )

        return [
            {
                "id": results["ids"][0][i],
                "content": results["documents"][0][i],
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else 0,
            }
            for i in range(len(results["ids"][0]))
        ]

    async def get_rubric_context(self, subject: str, task_type: str) -> str:
        """获取评分标准上下文"""
        query = f"{subject} {task_type} marking scheme criteria"
        results = self.query("official_corpus", query, n_results=3)

        if not results:
            return ""

        return "\n\n".join([r["content"] for r in results])

    async def get_curriculum_context(self, subject: str, unit: str) -> str:
        """获取课纲知识点上下文"""
        query = f"{subject} {unit} learning objectives key concepts"
        results = self.query("official_corpus", query, n_results=3)

        if not results:
            return ""

        return "\n\n".join([r["content"] for r in results])


@lru_cache(maxsize=1)
def get_rag_service() -> CurriculumRAG:
    """获取 RAG 服务单例"""
    return CurriculumRAG()
```

#### Task P1-1.3: 版本化设计

**版本追踪模型:**

```python
class CorpusVersion(CamelModel):
    """语料版本记录"""
    collection: str
    version: str
    created_at: str
    doc_count: int
    description: str = ""
```

**在 QuestionFinal 中记录版本:**

```python
class QuestionFinal(CamelModel):
    # ... 现有字段 ...
    rubric_version: str | None = None  # 生成时引用的 rubric 版本
    corpus_version: str | None = None  # 生成时的语料版本
```

#### Task P1-1.4: RAG 评测集

**新建 tests/test_rag_evaluation.py:**

```python
"""RAG retrieval quality evaluation tests."""

import pytest
from services.rag_service import get_rag_service

# 评测查询集 (20-50 个)
EVAL_QUERIES = [
    {
        "query": "DSE Writing Level 4 organization criteria",
        "collection": "official_corpus",
        "expected_keywords": ["organization", "coherent", "paragraphing"],
    },
    {
        "query": "DSE Reading Comprehension inference skills",
        "collection": "official_corpus",
        "expected_keywords": ["inference", "implied", "reading"],
    },
    # ... 更多评测查询 ...
]


@pytest.mark.skipif(not Path("data/rag").exists(), reason="RAG not initialized")
class TestRAGEvaluation:

    def test_retrieval_relevance(self):
        """Test retrieval relevance for evaluation queries."""
        rag = get_rag_service()

        total = 0
        hits = 0

        for item in EVAL_QUERIES:
            results = rag.query(item["collection"], item["query"], n_results=3)

            if results:
                content = " ".join([r["content"] for r in results]).lower()
                matched = sum(1 for kw in item["expected_keywords"] if kw.lower() in content)

                total += len(item["expected_keywords"])
                hits += matched

        relevance = hits / total if total > 0 else 0
        assert relevance >= 0.6, f"Retrieval relevance {relevance:.2%} below threshold"
```

---

### Step P1-2: 知识点字典

**目标:** 先建立结构化的知识点字典，为后续知识图谱做准备。

#### Task P1-2.1: 知识点注册表

**新建 data/knowledge_points/dse-english.json:**

```json
{
  "subject": "English",
  "level": "DSE",
  "version": "2024",
  "units": [
    {
      "id": "DSE-ENG-U5",
      "name": "Unit 5",
      "knowledgePoints": [
        {
          "id": "DSE-ENG-U5-RC-01",
          "name": "Reading Comprehension - Main Idea",
          "description": "Identify the main idea of a passage",
          "skillTags": ["reading", "comprehension", "inference"],
          "prerequisites": [],
          "difficulty": "medium"
        },
        {
          "id": "DSE-ENG-U5-RC-02",
          "name": "Reading Comprehension - Supporting Details",
          "description": "Identify supporting details and examples",
          "skillTags": ["reading", "comprehension", "detail"],
          "prerequisites": ["DSE-ENG-U5-RC-01"],
          "difficulty": "easy"
        },
        {
          "id": "DSE-ENG-U5-GR-01",
          "name": "Grammar - Tenses",
          "description": "Correct use of verb tenses",
          "skillTags": ["grammar", "writing"],
          "prerequisites": [],
          "difficulty": "medium"
        }
      ]
    }
  ]
}
```

#### Task P1-2.2: 知识点服务

**新建 services/knowledge_service.py:**

```python
"""Knowledge point registry and lookup service."""

import json
from pathlib import Path
from functools import lru_cache
from models.data import KnowledgePoint

KNOWLEDGE_DIR = Path(__file__).parent.parent / "data" / "knowledge_points"


@lru_cache(maxsize=32)
def load_knowledge_registry(subject: str, level: str = "DSE") -> dict:
    """Load knowledge point registry for a subject."""
    file_path = KNOWLEDGE_DIR / f"{level.lower()}-{subject.lower()}.json"
    if not file_path.exists():
        return {}

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_knowledge_point(knowledge_point_id: str) -> KnowledgePoint | None:
    """Get a single knowledge point by ID."""
    # 解析 ID 获取 subject/level
    parts = knowledge_point_id.split("-")
    if len(parts) < 2:
        return None

    level, subject = parts[0], parts[1]
    registry = load_knowledge_registry(subject, level)

    for unit in registry.get("units", []):
        for kp in unit.get("knowledgePoints", []):
            if kp["id"] == knowledge_point_id:
                return KnowledgePoint(**kp)

    return None


def list_knowledge_points(
    subject: str,
    unit: str = "",
    skill_tags: list[str] | None = None,
    level: str = "DSE",
) -> list[KnowledgePoint]:
    """List knowledge points with optional filters."""
    registry = load_knowledge_registry(subject, level)
    results = []

    for u in registry.get("units", []):
        if unit and u["id"] != unit and u["name"] != unit:
            continue

        for kp in u.get("knowledgePoints", []):
            if skill_tags:
                if not any(tag in kp.get("skillTags", []) for tag in skill_tags):
                    continue
            results.append(KnowledgePoint(**kp))

    return results
```

#### Task P1-2.3: 知识点→题目映射

**扩展 services/knowledge_service.py:**

```python
def map_error_to_knowledge_points(error_tags: list[str], subject: str) -> list[str]:
    """Map error tags to knowledge point IDs."""
    # 映射规则表
    MAPPING = {
        "grammar": ["DSE-ENG-U5-GR-01"],
        "vocabulary": ["DSE-ENG-U5-VC-01"],
        "inference": ["DSE-ENG-U5-RC-01"],
        "main_idea": ["DSE-ENG-U5-RC-01"],
        "detail": ["DSE-ENG-U5-RC-02"],
        # ... 更多映射 ...
    }

    knowledge_points = set()
    for tag in error_tags:
        if tag.lower() in MAPPING:
            knowledge_points.update(MAPPING[tag.lower()])

    return list(knowledge_points)
```

---

## 5. P2 任务分解（中长期）

### Step P2-1: Teacher-in-the-loop 数据闭环

**目标:** 记录教师对题目的采用/编辑/退回，形成训练数据。

#### Task P2-1.1: 定义反馈模型

**新建 models/feedback.py:**

```python
"""Teacher feedback models for question quality improvement."""

from enum import Enum
from pydantic import Field
from models.base import CamelModel


class FeedbackAction(str, Enum):
    ADOPTED = "adopted"      # 直接采用
    EDITED = "edited"        # 编辑后采用
    DISCARDED = "discarded"  # 退回不用


class QuestionFeedback(CamelModel):
    """教师对单个题目的反馈"""
    question_id: str
    teacher_id: str
    action: FeedbackAction
    original_question: dict  # 原始题目
    edited_question: dict | None = None  # 编辑后的题目（如有）
    edit_diff: dict | None = None  # 编辑差异
    feedback_text: str = ""  # 文字反馈
    created_at: str = ""

    # 分类标签
    edit_categories: list[str] = Field(default_factory=list)
    # ["stem_rewrite", "options_modified", "answer_changed", "difficulty_adjusted"]


class StudentPerformanceFeedback(CamelModel):
    """学生作答后的统计反馈"""
    question_id: str
    attempt_count: int
    correct_rate: float
    avg_time_seconds: float
    predicted_difficulty: str  # 原始预测
    actual_difficulty: str  # 根据正确率推断
    difficulty_match: bool
```

#### Task P2-1.2: 反馈收集 API

**新建 api/feedback.py:**

```python
@router.post("/question-feedback")
async def submit_question_feedback(req: QuestionFeedbackRequest):
    """提交教师对题目的反馈"""
    # 存储到数据库/文件
    # 用于后续分析和模型改进
    ...
```

### Step P2-2: 混合生成策略

**目标:** 题库检索优先 + LLM 变体生成。

#### Task P2-2.1: 题库检索工具

**新增工具:**

```python
@mcp.tool()
async def search_question_bank(
    knowledge_point_ids: list[str],
    difficulty: str = "",
    question_type: str = "",
    limit: int = 10,
) -> dict:
    """
    从题库检索相似题目

    Returns:
        {
            "questions": [
                {"id": "...", "type": "...", "stem": "...", "similarity": 0.85}
            ]
        }
    """
    rag = get_rag_service()

    query = " ".join(knowledge_point_ids)
    if difficulty:
        query += f" {difficulty}"

    results = rag.query(
        "question_bank",
        query,
        n_results=limit,
        where={"type": question_type} if question_type else None,
    )

    return {"questions": results}
```

#### Task P2-2.2: 混合生成流程

```python
async def hybrid_generate(spec: dict, rubric_context: dict | None) -> list[QuestionFinal]:
    """混合生成: 检索 + 变体生成"""

    # 1. 先检索相似题目
    similar = await search_question_bank(
        knowledge_point_ids=spec.get("knowledge_points", []),
        difficulty=spec.get("difficulty", ""),
        limit=5,
    )

    if similar["questions"]:
        # 2. 基于检索结果生成变体
        return await generate_variants(similar["questions"], spec, rubric_context)
    else:
        # 3. 无检索结果，走纯生成
        pipeline = QuestionPipeline()
        return await pipeline.run_pipeline(spec, rubric_context)
```

---

## 6. 实施时间线

| 阶段 | 任务 | 预计周期 |
|------|------|----------|
| **P0-1** | 题目级数据模型 | 2 天 |
| **P0-2** | 结构一致性修复 | 1 天 |
| **P0-3** | Rubric-as-Assets | 2 天 |
| **P0-4** | 题目流水线 | 3 天 |
| **P1-1** | RAG 基础设施 | 4 天 |
| **P1-2** | 知识点字典 | 2 天 |
| **测试** | E2E + 回归测试 | 2 天 |

**总计:** 约 2-2.5 周

---

## 7. 关键文件清单

### P0 新建/修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `models/data.py` | 修改 | 新增 QuestionItem, ErrorPattern, StudentMastery |
| `models/rubric.py` | 新建 | Rubric, RubricCriterion, RubricLevel |
| `models/question_pipeline.py` | 新建 | QuestionDraft, JudgeResult, QuestionFinal |
| `data/rubrics/*.json` | 新建 | DSE 评分标准 JSON 文件 |
| `services/rubric_service.py` | 新建 | Rubric 加载服务 |
| `agents/question_pipeline.py` | 新建 | Draft→Judge→Repair 流水线 |
| `tools/stats_tools.py` | 修改 | 新增 summary 字段 |
| `tools/assessment_tools.py` | 新建 | analyze_student_weakness, get_student_error_patterns |
| `config/prompts/planner.py` | 修改 | 新增 Rule 11-12 约束 |
| `config/prompts/block_compose.py` | 修改 | 支持 pipeline 模式 |
| `agents/executor.py` | 修改 | 集成 QuestionPipeline |

### P1 新建/修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `services/rag_service.py` | 新建 | RAG 分库服务 |
| `services/knowledge_service.py` | 新建 | 知识点注册表服务 |
| `data/knowledge_points/*.json` | 新建 | 知识点定义文件 |
| `tests/test_rag_evaluation.py` | 新建 | RAG 评测集 |

### 测试文件

| 文件 | 说明 |
|------|------|
| `tests/test_assessment_tools.py` | 学情分析工具测试 |
| `tests/test_rubric_service.py` | Rubric 服务测试 |
| `tests/test_question_pipeline.py` | 题目流水线测试 |
| `tests/test_knowledge_service.py` | 知识点服务测试 |

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Java 后端缺少题目级数据接口 | P0-1 无法完成 | 先用 mock 数据，并行推进接口开发 |
| DSE 官方资料获取困难 | P0-3 Rubric 不完整 | 先用公开资料，逐步补充 |
| LLM 调用次数增加（流水线三阶段） | 延迟增加、成本上升 | 引入缓存、批量处理、质量阈值跳过 |
| RAG 检索质量不稳定 | 生成质量波动 | 评测集监控、人工审核高风险题目 |

---

## 9. 成功指标

| 指标 | 当前 | P0 目标 | P1 目标 |
|------|------|---------|---------|
| 题目可用率（教师采用率） | 未知 | ≥60% | ≥80% |
| 知识点覆盖准确率 | 0% | ≥70% | ≥90% |
| 难度匹配率 | 未知 | ≥60% | ≥80% |
| kpi_grid 渲染成功率 | 0% | 100% | 100% |

---

## 10. 执行建议

1. **P0 串行执行:** P0-1 → P0-2 → P0-3 → P0-4，有依赖关系
2. **P1 可并行:** P1-1 和 P1-2 可同时进行
3. **每个任务完成后:** 运行 `pytest tests/ -v` 确保无回归
4. **每个阶段完成后:** 更新 `docs/roadmap.md` 和 `docs/changelog.md`
