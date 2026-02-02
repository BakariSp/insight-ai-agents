# 添加新技能

> 如何为 Agent 添加新的工具/技能。

---

## 方式一：FastMCP Tool（推荐）

使用 FastMCP 注册工具，自动生成 JSON Schema，代码量少。

### 步骤

1. 在 `tools/data_tools.py` 或 `tools/stats_tools.py` 中添加函数（或新建文件）
2. 在 `tools/__init__.py` 中导入并注册到 `mcp`

### 示例：添加数据工具

```python
# tools/data_tools.py

def get_student_attendance(teacher_id: str, student_id: str) -> dict:
    """Get attendance record for a student.

    Args:
        teacher_id: The teacher's unique identifier.
        student_id: The student's unique identifier.

    Returns:
        Dictionary with attendance data.
    """
    # Phase 1: mock 数据
    return {"student_id": student_id, "attendance_rate": 0.95, "absences": 3}
```

```python
# tools/__init__.py — 添加注册

from tools.data_tools import get_student_attendance
mcp.tool()(get_student_attendance)
```

### 示例：添加统计工具

```python
# tools/stats_tools.py

def calculate_trend(data_points: list[float], window: int = 3) -> dict:
    """Calculate trend from time-series data.

    Args:
        data_points: Ordered numeric values over time.
        window: Moving average window size.

    Returns:
        Dictionary with trend direction and moving averages.
    """
    # ... 实现
    return {"direction": "up", "moving_avg": [...]}
```

### 测试

```bash
# 单元测试 — 直接调用函数
pytest tests/test_tools.py -v

# FastMCP 交互式测试
fastmcp dev tools/__init__.py
```

---

## 方式二：BaseSkill（旧方式，ChatAgent 使用）

> 旧方式仅供 Phase 0 的 ChatAgent 使用。新工具应优先使用 FastMCP。

1. 在 `skills/` 下创建新文件
2. 继承 `BaseSkill`
3. 实现 `name`, `description`, `input_schema`, `execute()`
4. 在 `agents/chat_agent.py` 的 `_load_skills()` 中注册

```python
from skills.base import BaseSkill

class MySkill(BaseSkill):
    @property
    def name(self) -> str:
        return "my_skill"

    @property
    def description(self) -> str:
        return "Description shown to the LLM"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "..."}
            },
            "required": ["param1"]
        }

    def execute(self, **kwargs) -> str:
        return f"Result: {kwargs['param1']}"
```

---

## 对比

| | BaseSkill (旧) | FastMCP (新) |
|---|---|---|
| 代码量 | ~40 行/tool | ~10 行/tool |
| JSON Schema | 手写 | 自动生成 (type hints) |
| 参数验证 | 无 | 自动验证 |
| 测试 | 自己搭 | `fastmcp dev` 交互式 |
| 适用场景 | ChatAgent 旧技能 | 新数据/统计工具 |

---

## 当前已注册的工具

### 数据工具 (`tools/data_tools.py`)

| 工具 | 功能 | 参数 |
|------|------|------|
| `get_teacher_classes` | 获取教师班级列表 | `teacher_id` |
| `get_class_detail` | 获取班级详情（含学生和作业） | `teacher_id`, `class_id` |
| `get_assignment_submissions` | 获取作业提交数据 | `teacher_id`, `assignment_id` |
| `get_student_grades` | 获取学生成绩 | `teacher_id`, `student_id` |

### 统计工具 (`tools/stats_tools.py`)

| 工具 | 功能 | 参数 |
|------|------|------|
| `calculate_stats` | 描述性统计 (mean, median, stddev, distribution 等) | `data`, `metrics` |
| `compare_performance` | 两组数据对比 | `group_a`, `group_b`, `metrics` |
