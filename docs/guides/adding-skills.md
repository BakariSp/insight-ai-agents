# 添加新技能

> 如何为 Agent 添加新的工具/技能。

---

## 方式一：BaseSkill（当前 Phase 0）

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

## 方式二：FastMCP Tool（目标 Phase 1+）

使用 `@mcp.tool` 装饰器，自动生成 JSON Schema，代码量大幅减少。

1. 在 `tools/` 下的文件中添加函数
2. 使用 `@mcp.tool` 装饰器
3. 用 type hints + `Annotated[..., Field()]` 描述参数

```python
from typing import Annotated
from pydantic import Field
from tools import mcp


@mcp.tool
async def my_tool(
    param1: Annotated[str, Field(description="参数说明")],
    param2: Annotated[int, Field(description="另一个参数")] = 10,
) -> dict:
    """工具描述，会展示给 LLM。"""
    return {"result": f"{param1}: {param2}"}
```

### 对比

| | BaseSkill | FastMCP |
|---|---|---|
| 代码量 | ~40 行/tool | ~10 行/tool |
| JSON Schema | 手写 | 自动生成 |
| 参数验证 | 无 | Pydantic 自动验证 |
| 测试 | 自己搭 | `fastmcp dev tools/__init__.py` |

### 测试 FastMCP 工具

```bash
# 交互式测试
fastmcp dev tools/__init__.py
```

---

## 添加数据工具

数据工具放在 `tools/data_tools.py`，每个工具对应一个 Java API endpoint：

```python
@mcp.tool
async def get_teacher_classes(
    teacher_id: Annotated[str, Field(description="教师 ID")],
) -> dict:
    """获取教师的班级列表。"""
    settings = get_settings()
    if settings.use_mock_data:
        from services.mock_data import mock_teacher_classes
        return mock_teacher_classes(teacher_id)

    async with httpx.AsyncClient(base_url=settings.java_backend_url) as client:
        resp = await client.get(f"/dify/teacher/{teacher_id}/classes/me")
        resp.raise_for_status()
        return resp.json()
```

## 添加统计工具

统计工具放在 `tools/stats_tools.py`，确定性计算，不依赖 LLM：

```python
@mcp.tool
async def calculate_stats(
    data: Annotated[list[float], Field(description="数值数组")],
    metrics: Annotated[list[str], Field(description="mean, median, stddev, min, max, percentiles, distribution")],
) -> dict:
    """统计计算。返回精确结果。"""
    arr = np.array(data)
    result = {"count": len(data)}
    for m in metrics:
        if m == "mean":      result["mean"] = round(float(np.mean(arr)), 2)
        elif m == "median":  result["median"] = round(float(np.median(arr)), 2)
        # ...
    return result
```
