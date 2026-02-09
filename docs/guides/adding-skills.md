# 添加新工具

> 如何为 NativeAgent 添加新的工具。

---

## 方式：Registry Tool（唯一方式）

使用 `tools/registry.py` 的 `@register_tool` 装饰器注册工具，自动生成 JSON Schema，代码量少。

> **注意**: 旧的 FastMCP 双注册和 BaseSkill 方式已废弃。所有工具统一使用 registry 注册。

### 步骤

1. 在 `tools/` 下的合适文件中添加函数（或新建文件）
2. 使用 `@register_tool(toolset="xxx")` 装饰器注册
3. 选择合适的 toolset 归属
4. 编写单元测试

### 示例：添加数据工具

```python
# tools/data_tools.py

from tools.registry import register_tool
from pydantic_ai import RunContext
from agents.native_agent import AgentContext

@register_tool(toolset="base_data")
async def get_student_attendance(
    ctx: RunContext[AgentContext],
    student_id: str,
) -> dict:
    """Get attendance record for a student.

    Args:
        student_id: The student's unique identifier.

    Returns:
        Dictionary with attendance data.
    """
    teacher_id = ctx.deps.teacher_id
    if not teacher_id:
        return {"status": "error", "reason": "teacher_id is required"}

    try:
        data = await data_api.get_attendance(teacher_id, student_id)
        return {"status": "ok", "attendance_rate": data.rate, "absences": data.absences}
    except Exception as e:
        if settings.debug:
            return _mock_attendance(student_id)  # 仅开发环境
        return {"status": "error", "reason": str(e)}
```

### 示例：添加生成工具

```python
# tools/generation_tools.py

from tools.registry import register_tool
from models.tool_result import ToolResult

@register_tool(toolset="generation")
async def generate_worksheet(
    ctx: RunContext[AgentContext],
    subject: str,
    grade: str,
    exercise_count: int = 10,
) -> ToolResult:
    """Generate a practice worksheet for a given subject and grade.

    Args:
        subject: The subject (e.g., "English", "Math").
        grade: The grade level (e.g., "Form 1", "Grade 5").
        exercise_count: Number of exercises to generate.

    Returns:
        ToolResult with the worksheet content.
    """
    worksheet = await _generate_worksheet_impl(subject, grade, exercise_count)
    return ToolResult(
        data=worksheet,
        artifact_type="worksheet",
        content_format="json",
        status="ok",
    )
```

### 测试

```bash
# 单元测试
pytest tests/test_registry.py -v

# 验证 schema 生成
pytest tests/test_registry.py::test_schema_generation -v
```

---

## 5 个 Toolset 归属指南

| Toolset | 适用场景 | 注入条件 |
|---------|---------|---------|
| `base_data` | 数据获取工具（班级、学生、成绩、实体解析） | 始终注入 |
| `analysis` | 统计分析、对比、薄弱点分析 | 消息涉及数据/成绩 |
| `generation` | 生成内容（Quiz、PPT、文稿、互动） | 消息涉及生成/创建 |
| `artifact_ops` | 已生成产物的查看/修改/重新生成 | 有 artifact 或涉及修改 |
| `platform` | 平台操作（保存、分享、RAG 检索、澄清、报告） | 始终注入 |

### 选择原则

- 如果工具获取外部数据 → `base_data`
- 如果工具做计算/分析 → `analysis`
- 如果工具生成新内容 → `generation`
- 如果工具操作已有 artifact → `artifact_ops`
- 如果工具做平台级操作或不确定 → `platform`

---

## 工具返回值契约

| Tool 类型 | 返回方式 | 示例 |
|----------|---------|------|
| **数据类 tool** | 直接返回 dict，含 `status` 字段 | `{"status": "ok", "classes": [...]}` |
| **分析类 tool** | 直接返回 dict，含 `status` 字段 | `{"status": "ok", "stats": {...}}` |
| **生成类 tool** | 必须返回 `ToolResult` envelope | `ToolResult(data=quiz, artifact_type="quiz", content_format="json")` |
| **RAG tool** | 必须返回带 `status` 的 dict | `{"status": "ok\|no_result\|error\|degraded", ...}` |
| **写操作 tool** | 必须返回 `ToolResult` envelope | `ToolResult(data=result, action="complete")` |
| **澄清 tool** | 必须返回结构化 `ClarifyEvent` | `ClarifyEvent(question=..., options=[...])` |

---

## 硬约束

| 约束 | 说明 |
|------|------|
| **teacher 隔离** | `ctx.deps.teacher_id` 必传，tool 内部过滤数据范围 |
| **禁止生产 mock** | `DEBUG=false` 时无 teacher_id → `{"status": "error"}`，不回退 mock |
| **禁止文本启发式** | 状态通过结构化字段传递，不扫描文本关键词推断 |
| **RAG 失败语义** | 区分 ok / no_result / error / degraded |
| **超时处理** | 30s per-tool 超时，由 NativeAgent 用 `asyncio.wait_for()` 包装 |

---

## 当前已注册的工具

### base_data (5 个)

| 工具 | 功能 |
|------|------|
| `get_teacher_classes` | 获取教师班级列表 |
| `get_class_detail` | 获取班级详情 |
| `get_assignment_submissions` | 获取作业提交数据 |
| `get_student_grades` | 获取学生成绩 |
| `resolve_entity` | 实体解析（班级/学生名 → ID） |

### analysis (5 个)

| 工具 | 功能 |
|------|------|
| `calculate_stats` | 描述性统计 |
| `compare_performance` | 两组数据对比 |
| `analyze_student_weakness` | 薄弱点分析 |
| `get_student_error_patterns` | 错题模式 |
| `calculate_class_mastery` | 班级掌握度 |

### generation (7 个)

| 工具 | 功能 |
|------|------|
| `generate_quiz_questions` | Quiz 题目生成 |
| `propose_pptx_outline` | PPT 大纲 |
| `generate_pptx` | PPT 生成 |
| `generate_docx` | 文稿生成 |
| `render_pdf` | PDF 渲染 |
| `generate_interactive_html` | 互动内容 |
| `request_interactive_content` | 互动请求 |

### artifact_ops (3 个)

| 工具 | 功能 |
|------|------|
| `get_artifact` | 获取 artifact 全文 |
| `patch_artifact` | 结构化 patch 操作 |
| `regenerate_from_previous` | 全文重新生成（降级路径） |

### platform (5 个)

| 工具 | 功能 |
|------|------|
| `save_as_assignment` | 保存为作业 |
| `create_share_link` | 创建分享链接 |
| `search_teacher_documents` | RAG 文档检索 |
| `ask_clarification` | 向用户提出澄清问题 |
| `build_report_page` | 数据分析报告 |
