# Python Agent Service Architecture

> FastMCP (tool registry) + PydanticAI (agent framework) + FastAPI (HTTP/SSE)。
> 核心概念：**Blueprint（可执行蓝图）** — AI 组装 UI，而非生成 UI 代码。
> API 契约详见 [frontend-python-integration.md](./frontend-python-integration.md)。

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│  Next.js Frontend (React UI, SSE consumer)       │
│  studio-agents.ts → /api/ai/* proxy routes       │
└──────────────┬───────────────────────────────────┘
               │ HTTP / SSE
               ▼
┌──────────────────────────────────────────────────┐
│  FastAPI Application (:8000)                      │
│                                                    │
│  POST /api/workflow/generate   → PlannerAgent     │
│       → output: Blueprint                         │
│  POST /api/report/generate     → ExecutorAgent    │
│       → execute Blueprint, SSE stream             │
│  POST /api/intent/classify     → RouterAgent      │
│  POST /api/report/chat         → ChatAgent        │
│  GET  /api/health                                  │
│                                                    │
│  ┌────────────────────────────────────────────┐   │
│  │  FastMCP (in-process tool registry)        │   │
│  │                                            │   │
│  │  Data:  get_teacher_classes()              │   │
│  │         get_class_detail()                 │   │
│  │         get_class_assignments()            │   │
│  │         get_assignment_submissions()       │   │
│  │         get_student_grades()               │   │
│  │                                            │   │
│  │  Stats: calculate_stats()                  │   │
│  │         compare_performance()              │   │
│  └────────────────────────────────────────────┘   │
│                                                    │
│  PydanticAI Agents (structured output, streaming) │
│       ↕ LiteLLM (multi-provider model access)     │
└──────────────┬───────────────────────────────────┘
               │ httpx
               ▼
┌──────────────────────────────────────────────────┐
│  Java Backend (:8080)                             │
│  /dify/teacher/{id}/classes/me                    │
│  /dify/teacher/{id}/classes/{classId}             │
│  /dify/teacher/{id}/classes/{classId}/assignments │
│  /dify/teacher/{id}/submissions/assignments/{id}  │
│  /dify/teacher/{id}/submissions/students/{id}     │
└──────────────────────────────────────────────────┘
```

### 三层框架分工

```
┌─────────────────────────────────────────────────────────────┐
│  FastMCP                                                     │
│  Tool 注册层：数据获取 + 统计计算                              │
│  @mcp.tool + Pydantic 参数验证                                │
├─────────────────────────────────────────────────────────────┤
│  PydanticAI                                                   │
│  Agent 编排层：Blueprint 生成 + 执行 + 结构化输出              │
│  agent.run(result_type=Blueprint) / agent.iter() streaming   │
├─────────────────────────────────────────────────────────────┤
│  LiteLLM                                                      │
│  Model Provider 层：100+ providers 统一接口                    │
│  dashscope/qwen-max, openai/gpt-4o, anthropic/claude-...    │
└─────────────────────────────────────────────────────────────┘
```

### Why FastMCP (purely internal)

FastMCP 不对外暴露，仅作为 **内部 tool 注册和调用框架**：

| vs 自定义 BaseSkill | FastMCP |
|---------------------|---------|
| class + ABC + 手写 JSON Schema | `@mcp.tool` + type hints，schema 自动生成 |
| 无参数验证 | Pydantic 自动验证 |
| ~40 行/tool | ~10 行/tool |
| 自己搭测试 | 内置 `fastmcp dev` 交互测试 |

PydanticAI Agent 通过 `@agent.tool` 桥接 FastMCP tools，in-process 调用，零网络开销。
前端完全不感知 MCP，只与 FastAPI HTTP/SSE 端点交互。

---

## LLM 框架选型

### 候选方案对比

| | LiteLLM | LangChain / LangGraph | PydanticAI |
|---|---|---|---|
| **定位** | LLM 网关 / 统一 API | 全套编排框架 | 类型安全 Agent 框架 |
| **多模型** | 100+ providers | 需逐个集成 | 原生支持 LiteLLM 作为 provider |
| **抽象层级** | 轻量（只管调模型） | 重（频繁 breaking changes） | 中等（Pydantic 原生） |
| **Tool Calling** | 基础，需自建 loop | 内置 | 内置 + Pydantic 参数验证 |
| **Streaming** | 支持 | 支持 | `run_stream()` + `iter()` 事件流 |
| **结构化输出** | 手动解析 | 有但松散 | 一等公民：`result_type` 直出 Pydantic model |
| **Agent 编排** | DIY | LangGraph DAG | 内置 multi-agent |
| **MCP 集成** | 无 | 需插件 | 原生支持 MCP / A2A |
| **维护风险** | 低 | 高 | 低（Pydantic 团队维护） |

### 推荐：PydanticAI + LiteLLM model

| 选择理由 | 说明 |
|----------|------|
| 技术栈契合 | 项目已用 Pydantic v2 + CamelModel，PydanticAI 天然集成 |
| 结构化输出 | Blueprint 需要 LLM 输出复杂嵌套 JSON，`result_type=Blueprint` 直接验证 |
| 多 Provider | PydanticAI 原生支持 LiteLLM 作为 model provider，保留 Qwen/GLM/GPT/Claude 切换 |
| Tool Calling | `@agent.tool` + Pydantic 参数验证，与 FastMCP `@mcp.tool` 理念一致 |
| Streaming | `agent.iter()` / `run_stream_events()` 直接产出 SSE 事件 |
| 未来扩展 | Level 3（AI 生成 Python function + 前端 UI）时，类型系统有助于约束和验证生成代码 |

---

## Tech Stack

```
fastapi + uvicorn          # HTTP/SSE server
fastmcp                    # 内部 tool registry（数据获取 + 统计计算）
pydantic-ai[litellm]       # Agent framework + multi-provider LLM
httpx                      # 调 Java backend
numpy                      # 统计计算
pydantic + pydantic-settings  # 数据模型 + 配置
sse-starlette              # SSE response
```

### `requirements.txt`

```
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
sse-starlette>=2.0.0
pydantic>=2.10.0
pydantic-settings>=2.6.0
pydantic-ai[litellm]>=1.40.0
fastmcp>=2.14.0
httpx>=0.28.0
numpy>=2.1.0
python-dotenv>=1.0.0
```

---

## Blueprint 数据模型

### 核心概念：可执行蓝图

Blueprint 取代了原来的 WorkflowTemplate。区别在于 Blueprint 不只是"报告大纲"，而是一个**三层可执行计划**：

```
Blueprint
├── metadata (id, name, version, capability_level, ...)
│
├── Layer A: DataContract           ← 数据契约：需要什么数据、怎么拿
│   ├── inputs: list[DataInputSpec]       用户选择项（班级、作业…）
│   └── bindings: list[DataBinding]       数据获取声明（tool 名 + 参数映射）
│
├── Layer B: ComputeGraph           ← 计算图：哪些确定性计算、哪些 AI 生成
│   └── nodes: list[ComputeNode]          tool 节点（可信）| ai 节点（生成性）
│
├── Layer C: UIComposition          ← 界面组合：注册组件 + 布局规范
│   ├── layout: "tabs" | "single_page"
│   └── tabs: list[TabSpec]
│       └── slots: list[ComponentSlot]    从组件注册表中选择
│
└── report_system_prompt: str       ← ExecutorAgent 上下文提示
```

### 三层职责

| Layer | 职责 | 信任级别 | 示例 |
|-------|------|----------|------|
| A. DataContract | 声明需要什么数据、如何获取 | 声明式，安全 | `get_class_detail(classId=$input.class)` |
| B. ComputeGraph | KPI/统计 = tool（确定性），叙事/建议 = AI（生成性） | tool 节点可信，AI 节点受控 | `calculate_stats(scores, ["mean","median"])` |
| C. UIComposition | 从注册组件中选择、排列、绑定数据 | AI 选组件/排序，不能写代码 | `[kpi_grid, chart(bar), table, markdown]` |

### Pydantic 模型定义

```python
from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """所有 API 输出模型的基类，输出 camelCase。"""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ── Layer A: Data Contract ──────────────────────────────────

class DataSourceType(str, Enum):
    TOOL = "tool"           # FastMCP tool 调用
    API = "api"             # 直接调 Java backend
    STATIC = "static"       # 内联数据 / 来自前端上下文


class DataInputSpec(CamelModel):
    """用户可见的数据选择项（班级、作业等）。"""
    id: str                                     # "class", "assignment"
    type: str                                   # "class" | "assignment" | "student" | "date_range"
    label: str
    required: bool = True
    depends_on: str | None = None               # 另一个 DataInputSpec 的 id


class DataBinding(CamelModel):
    """单个数据需求：获取什么、如何获取。"""
    id: str                                     # "class_detail", "submissions"
    source_type: DataSourceType = DataSourceType.TOOL
    tool_name: str | None = None                # "get_class_detail"
    api_path: str | None = None                 # "/dify/teacher/{teacherId}/classes/{classId}"
    param_mapping: dict[str, str] = {}          # {"teacher_id": "$context.teacherId"}
    description: str = ""
    required: bool = True
    depends_on: list[str] = []                  # 其他 DataBinding 的 id


class DataContract(CamelModel):
    """Layer A: 声明 Blueprint 需要的所有数据。"""
    inputs: list[DataInputSpec]
    bindings: list[DataBinding]


# ── Layer B: Compute Graph ──────────────────────────────────

class ComputeNodeType(str, Enum):
    TOOL = "tool"           # 确定性 tool 计算（可信）
    AI = "ai"               # AI 叙事 / 建议（生成性，不伪造指标）


class ComputeNode(CamelModel):
    """计算图中的一个节点。"""
    id: str                                     # "score_stats", "narrative_overview"
    type: ComputeNodeType
    # TOOL 节点：
    tool_name: str | None = None                # "calculate_stats"
    tool_args: dict | None = None               # 静态参数或引用 "$data.submissions.scores"
    # AI 节点：
    prompt_template: str | None = None          # AI 生成的提示模板
    # 通用：
    depends_on: list[str] = []                  # 其他 ComputeNode 或 DataBinding 的 id
    output_key: str = ""                        # 结果在执行上下文中的 key 名


class ComputeGraph(CamelModel):
    """Layer B: 定义计算步骤及执行顺序。"""
    nodes: list[ComputeNode]


# ── Layer C: UI Composition ─────────────────────────────────

class ComponentType(str, Enum):
    """注册组件类型，AI 只能从中选择。"""
    KPI_GRID = "kpi_grid"
    CHART = "chart"
    TABLE = "table"
    MARKDOWN = "markdown"
    SUGGESTION_LIST = "suggestion_list"
    QUESTION_GENERATOR = "question_generator"


class ComponentSlot(CamelModel):
    """布局中的一个组件位置。"""
    id: str
    component_type: ComponentType
    data_binding: str | None = None             # 引用 ComputeNode 的 output_key
    props: dict = {}                            # 静态属性（chart variant, title 等）
    ai_content_slot: bool = False               # Level 2: AI 填充组件内容


class TabSpec(CamelModel):
    id: str
    label: str
    slots: list[ComponentSlot]


class UIComposition(CamelModel):
    """Layer C: 声明如何从注册组件组合 UI。"""
    layout: str = "tabs"                        # "tabs" | "single_page"
    tabs: list[TabSpec]


# ── Blueprint (顶层) ───────────────────────────────────────

class CapabilityLevel(int, Enum):
    LEVEL_1 = 1     # 固定组件 + AI 排版
    LEVEL_2 = 2     # 组件插槽 + AI 填内容
    LEVEL_3 = 3     # 受限微应用（未来）


class Blueprint(CamelModel):
    """可执行蓝图 — 报告的完整执行计划。"""
    # 元数据
    id: str                                     # f"bp-{timestamp}"
    name: str
    description: str
    icon: str = "chart"
    category: str = "analytics"
    version: int = 1
    capability_level: CapabilityLevel = CapabilityLevel.LEVEL_1
    source_prompt: str = ""
    created_at: str = ""

    # 三层
    data_contract: DataContract
    compute_graph: ComputeGraph
    ui_composition: UIComposition

    # ExecutorAgent 上下文
    report_system_prompt: str = ""
```

---

## 组件注册表 (Component Registry)

AI 只能从注册表中选择组件类型，不能发明新类型。

```python
# config/component_registry.py

COMPONENT_REGISTRY = {
    "kpi_grid": {
        "description": "KPI 指标卡片网格，显示 label、value、status、subtext",
        "data_shape": {"items": [{"label": "str", "value": "str", "status": "str", "subtext": "str"}]},
        "props": {"max_columns": "int"},
    },
    "chart": {
        "description": "图表组件，支持多种 variant",
        "variants": ["bar", "line", "radar", "pie", "gauge", "distribution"],
        "data_shape": {"xAxis": "list[str]", "series": [{"name": "str", "data": "list[float]"}]},
        "props": {"variant": "str", "title": "str", "color": "str"},
    },
    "table": {
        "description": "数据表格，支持 headers、rows、highlightRules",
        "data_shape": {"headers": "list[str]", "rows": [{"cells": "list", "status": "str"}]},
        "props": {"title": "str", "highlightRules": "list"},
    },
    "markdown": {
        "description": "Markdown 内容块，用于叙事和洞察",
        "variants": ["default", "insight", "warning", "success"],
        "data_shape": {"content": "str"},
        "props": {"variant": "str"},
    },
    "suggestion_list": {
        "description": "可执行建议列表，含优先级和分类",
        "data_shape": {"items": [{"title": "str", "description": "str", "priority": "str", "category": "str"}]},
        "props": {"title": "str"},
    },
    "question_generator": {
        "description": "自动生成练习题，基于错误模式",
        "data_shape": {"questions": [{"id": "str", "type": "str", "question": "str", "answer": "str"}]},
        "props": {"knowledgePoint": "str", "difficulty": "str"},
    },
}
```

前端 ReportRenderer 已支持这 6 种组件。添加新组件时：
1. 前端实现新组件 + 注册到 ReportRenderer
2. 后端在 `COMPONENT_REGISTRY` 中注册
3. PlannerAgent system prompt 中添加描述

---

## 三级能力模型

```
┌─────────────────────────────────────────────────────────────┐
│  Level 1（当前）: 固定组件 + AI 排版                          │
│                                                               │
│  AI 输出 JSON LayoutSpec：                                    │
│  - 从注册表选组件：kpi_grid, chart, table, markdown, ...     │
│  - 排列和分组（tabs, sections）                               │
│  - 数据绑定（哪个计算结果 → 哪个组件）                         │
│  - 组件属性（chart variant, title 等）                        │
│                                                               │
│  ✅ 安全：AI 不能生成任意 UI 代码                              │
│  ✅ 可扩展：注册表新增组件即扩展能力                            │
│  ✅ 可控：前端零改动                                           │
├─────────────────────────────────────────────────────────────┤
│  Level 2（增强）: 组件插槽 + AI 填内容                        │
│                                                               │
│  AI 填充组件内部的"内容插槽"：                                 │
│  - markdown blocks: AI 撰写叙事文本                           │
│  - suggestion_list: AI 生成建议条目                           │
│  - table cells: AI 填写分析文本                               │
│                                                               │
│  ⚡ 自由度提升，但仍在组件边界内                               │
│  💡 ComponentSlot.ai_content_slot = true 标记                 │
├─────────────────────────────────────────────────────────────┤
│  Level 3（未来）: 受限微应用 Micro-UI                         │
│                                                               │
│  AI 生成 Python function + 前端 UI：                          │
│  - Python: 沙箱执行（RestrictedPython / subprocess sandbox） │
│  - 前端: 受限 DSL 或 iframe 沙箱（严格 CSP）                  │
│  - 安全: 禁外联、禁文件系统、只允许白名单 API                  │
│                                                               │
│  ⚠️ 风险高，延期实现                                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 路径引用语法

ComputeGraph 和 DataBinding 中使用简单路径引用来关联数据：

| 前缀 | 含义 | 示例 |
|------|------|------|
| `$context.` | 运行时上下文（如 teacherId） | `$context.teacherId` |
| `$input.` | 用户选择的 DataInputSpec 值 | `$input.class`, `$input.assignment` |
| `$data.` | DataBinding 获取到的数据 | `$data.submissions`, `$data.class_detail.students` |
| `$compute.` | ComputeNode 的输出结果 | `$compute.scoreStats`, `$compute.narrativeOverview` |

规则：
- 仅支持点号路径，不支持表达式（如 `.map()`, `.filter()`）
- 路径解析由 ExecutorAgent 在运行时执行
- 如果路径不存在，返回 `null`，不抛异常

---

## Project Structure

```
insight-ai-agent/
├── main.py                         # FastAPI entry point
├── requirements.txt
├── .env
│
├── config/
│   ├── settings.py                 # Pydantic Settings
│   ├── component_registry.py       # 组件注册表定义
│   └── prompts/
│       ├── planner.py              # PlannerAgent system prompt (→ Blueprint)
│       ├── executor.py             # ExecutorAgent system prompt (执行 Blueprint)
│       ├── router.py               # Intent classification prompt
│       └── chat.py                 # Chat agent prompt
│
├── models/
│   ├── base.py                     # CamelModel 基类
│   ├── blueprint.py                # Blueprint, DataContract, ComputeGraph, UIComposition
│   ├── components.py               # ComponentType, ComponentSlot, TabSpec
│   ├── report.py                   # ReportMeta, ReportTab, blocks (输出模型)
│   └── request.py                  # API request/response models
│
├── tools/                          # FastMCP tools
│   ├── __init__.py                 # mcp = FastMCP(...) + imports
│   ├── data_tools.py              # Java backend → data
│   └── stats_tools.py             # numpy → stats
│
├── agents/
│   ├── provider.py                 # PydanticAI + LiteLLM provider + FastMCP bridge
│   ├── planner.py                  # PlannerAgent: user prompt → Blueprint
│   ├── executor.py                 # ExecutorAgent: Blueprint → Report (SSE)
│   ├── router.py                   # RouterAgent: intent classification
│   └── chat.py                     # ChatAgent: report follow-up
│
├── services/
│   └── mock_data.py               # Mock data (dev)
│
└── api/
    ├── workflow.py                 # POST /api/workflow/generate
    ├── report.py                   # POST /api/report/generate + chat
    ├── intent.py                   # POST /api/intent/classify
    └── health.py                   # GET /api/health
```

---

## Core Implementation

### 1. FastMCP Tool Registry (`tools/__init__.py`)

```python
from fastmcp import FastMCP

mcp = FastMCP(name="insight-ai-tools")

from tools.data_tools import *    # noqa
from tools.stats_tools import *   # noqa
```

### 2. Data Tools (`tools/data_tools.py`)

每个 `@mcp.tool` 映射一个 Java API endpoint。

```python
import httpx
from typing import Annotated
from pydantic import Field
from tools import mcp
from config.settings import get_settings


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
        resp = await client.get(f"/dify/teacher/{teacher_id}/classes/me", timeout=settings.tool_timeout)
        resp.raise_for_status()
        return resp.json()


@mcp.tool
async def get_class_detail(
    teacher_id: Annotated[str, Field(description="教师 ID")],
    class_id: Annotated[str, Field(description="班级 ID")],
) -> dict:
    """获取班级详情，包括学生列表、班级元信息。"""
    settings = get_settings()
    if settings.use_mock_data:
        from services.mock_data import mock_class_detail
        return mock_class_detail(teacher_id, class_id)

    async with httpx.AsyncClient(base_url=settings.java_backend_url) as client:
        resp = await client.get(f"/dify/teacher/{teacher_id}/classes/{class_id}", timeout=settings.tool_timeout)
        resp.raise_for_status()
        return resp.json()


@mcp.tool
async def get_assignment_submissions(
    teacher_id: Annotated[str, Field(description="教师 ID")],
    assignment_id: Annotated[str, Field(description="作业 ID")],
) -> dict:
    """获取某个作业的全部学生提交记录和分数。"""
    settings = get_settings()
    if settings.use_mock_data:
        from services.mock_data import mock_assignment_submissions
        return mock_assignment_submissions(teacher_id, assignment_id)

    async with httpx.AsyncClient(base_url=settings.java_backend_url) as client:
        resp = await client.get(f"/dify/teacher/{teacher_id}/submissions/assignments/{assignment_id}", timeout=settings.tool_timeout)
        resp.raise_for_status()
        return resp.json()


@mcp.tool
async def get_student_grades(
    teacher_id: Annotated[str, Field(description="教师 ID")],
    student_id: Annotated[str, Field(description="学生 ID")],
) -> dict:
    """获取某个学生的成绩详情。"""
    settings = get_settings()
    if settings.use_mock_data:
        from services.mock_data import mock_student_grades
        return mock_student_grades(teacher_id, student_id)

    async with httpx.AsyncClient(base_url=settings.java_backend_url) as client:
        resp = await client.get(f"/dify/teacher/{teacher_id}/submissions/students/{student_id}", timeout=settings.tool_timeout)
        resp.raise_for_status()
        return resp.json()

# 同理: get_class_assignments, get_student_classes, get_class_overview ...
```

### 3. Stats Tools (`tools/stats_tools.py`)

确定性计算，不依赖 LLM。在 ComputeGraph 中作为 `type: "tool"` 节点使用。

```python
import numpy as np
from typing import Annotated
from pydantic import Field
from tools import mcp


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
        elif m == "stddev":  result["stddev"] = round(float(np.std(arr)), 2)
        elif m == "min":     result["min"] = round(float(np.min(arr)), 2)
        elif m == "max":     result["max"] = round(float(np.max(arr)), 2)
        elif m == "percentiles":
            result["percentiles"] = {f"p{p}": round(float(np.percentile(arr, p)), 2) for p in [25, 50, 75, 90]}
        elif m == "distribution":
            result["distribution"] = {
                "0-59": int(np.sum(arr < 60)), "60-69": int(np.sum((arr >= 60) & (arr < 70))),
                "70-79": int(np.sum((arr >= 70) & (arr < 80))), "80-89": int(np.sum((arr >= 80) & (arr < 90))),
                "90-100": int(np.sum(arr >= 90)),
            }
    return result


@mcp.tool
async def compare_performance(
    current_scores: Annotated[list[float], Field(description="本次分数")],
    previous_scores: Annotated[list[float], Field(description="上次分数")],
) -> dict:
    """对比两次成绩。"""
    curr, prev = np.array(current_scores), np.array(previous_scores)
    return {
        "current_mean": round(float(np.mean(curr)), 2),
        "previous_mean": round(float(np.mean(prev)), 2),
        "change": round(float(np.mean(curr) - np.mean(prev)), 2),
        "improved_count": int(np.sum(curr > prev)) if len(curr) == len(prev) else None,
        "declined_count": int(np.sum(curr < prev)) if len(curr) == len(prev) else None,
    }
```

### 4. Agent Provider (`agents/provider.py`)

核心：PydanticAI Agent + LiteLLM model + FastMCP tool 桥接。

```python
from pydantic_ai import Agent
from pydantic_ai.models.litellm import LiteLLMModel
from fastmcp import Client
from tools import mcp
from config.settings import get_settings


def create_model(model_name: str | None = None) -> LiteLLMModel:
    """创建 LiteLLM model 实例。"""
    settings = get_settings()
    return LiteLLMModel(model_name or settings.executor_model)


async def execute_mcp_tool(name: str, arguments: dict) -> str:
    """In-process 调用 FastMCP tool。"""
    async with Client(mcp) as client:
        result = await client.call_tool(name, arguments)
        return "\n".join(
            item.text if hasattr(item, "text") else str(item)
            for item in result
        )


def get_mcp_tool_names() -> list[str]:
    """获取所有注册的 FastMCP tool 名称。"""
    return [tool.name for tool in mcp._tool_manager.list_tools()]
```

### 5. PlannerAgent (`agents/planner.py`)

输入 user prompt → 输出 `Blueprint`。PydanticAI 的 `result_type` 确保输出结构合法。

```python
from pydantic_ai import Agent
from models.blueprint import Blueprint
from agents.provider import create_model
from config.prompts.planner import PLANNER_SYSTEM_PROMPT
from config.component_registry import COMPONENT_REGISTRY


planner_agent = Agent(
    model=create_model(),
    result_type=Blueprint,
    system_prompt=PLANNER_SYSTEM_PROMPT,
)


@planner_agent.system_prompt
async def add_component_registry(ctx):
    """动态注入组件注册表到 system prompt。"""
    registry_desc = "\n".join(
        f"- {name}: {info['description']}"
        for name, info in COMPONENT_REGISTRY.items()
    )
    return f"\n## Available UI Components\n{registry_desc}\n"


async def generate_blueprint(user_prompt: str, language: str = "en") -> Blueprint:
    """用户输入 → Blueprint。"""
    result = await planner_agent.run(
        f"User request: {user_prompt}\nLanguage: {language}"
    )
    return result.data
```

### 6. ExecutorAgent (`agents/executor.py`)

执行 Blueprint 三阶段，输出 SSE stream → 前端 `handleSSEStream()` 直接消费。

```python
import json
from typing import AsyncGenerator
from pydantic_ai import Agent
from agents.provider import create_model, execute_mcp_tool
from config.settings import get_settings
from models.blueprint import Blueprint, ComputeNodeType


class ExecutorAgent:

    def __init__(self):
        settings = get_settings()
        self.model = create_model(settings.executor_model)

    async def execute_blueprint_stream(
        self, blueprint: Blueprint, context: dict,
    ) -> AsyncGenerator[dict, None]:
        """三阶段执行 Blueprint，流式输出 SSE 事件。"""

        # ── Phase 1: Resolve Data Contract ──
        yield {"type": "PHASE", "phase": "data", "message": "Fetching data..."}
        data_context = await self._resolve_data_contract(blueprint, context)

        # ── Phase 2: Execute Compute Graph ──
        yield {"type": "PHASE", "phase": "compute", "message": "Computing analytics..."}
        compute_results = {}

        # 按依赖排序（Level 1 简化为线性：先 TOOL 节点，后 AI 节点）
        tool_nodes = [n for n in blueprint.compute_graph.nodes if n.type == ComputeNodeType.TOOL]
        ai_nodes = [n for n in blueprint.compute_graph.nodes if n.type == ComputeNodeType.AI]

        for node in tool_nodes:
            if node.tool_name:
                resolved_args = self._resolve_refs(node.tool_args or {}, data_context, compute_results)
                yield {"type": "TOOL_CALL", "tool": node.tool_name, "args": resolved_args}
                result = await execute_mcp_tool(node.tool_name, resolved_args)
                yield {"type": "TOOL_RESULT", "tool": node.tool_name, "result": result}
                compute_results[node.output_key] = json.loads(result) if self._is_json(result) else result

        # ── Phase 3: AI Compose ──
        yield {"type": "PHASE", "phase": "compose", "message": "Composing report..."}

        # 构建 AI 上下文：数据 + 计算结果 + Blueprint UI 规范
        compose_prompt = self._build_compose_prompt(blueprint, data_context, compute_results)

        agent = Agent(model=self.model, system_prompt=blueprint.report_system_prompt or "")

        # 注册 FastMCP tools 供 AI 节点按需调用
        @agent.tool_plain
        async def call_tool(tool_name: str, arguments: str) -> str:
            """调用数据/统计工具获取额外数据。"""
            args = json.loads(arguments)
            return await execute_mcp_tool(tool_name, args)

        accumulated = ""
        async with agent.iter(compose_prompt) as run:
            async for node in run:
                if hasattr(node, 'data') and isinstance(node.data, str):
                    accumulated += node.data
                    yield {"type": "MESSAGE", "content": node.data}

        yield {
            "type": "COMPLETE", "message": "completed", "progress": 100,
            "result": {"response": accumulated},
        }

    async def _resolve_data_contract(self, blueprint: Blueprint, context: dict) -> dict:
        """解析 DataContract，获取所有绑定数据。"""
        data = {}
        for binding in blueprint.data_contract.bindings:
            if binding.tool_name:
                resolved_args = {}
                for param, ref in binding.param_mapping.items():
                    resolved_args[param] = self._resolve_ref(ref, context, {}, data)
                result = await execute_mcp_tool(binding.tool_name, resolved_args)
                data[binding.id] = json.loads(result) if self._is_json(result) else result
        return data

    def _resolve_ref(self, ref: str, context: dict, compute: dict, data: dict) -> str:
        """解析单个路径引用 $context.x, $input.x, $data.x, $compute.x。"""
        if not ref.startswith("$"):
            return ref
        parts = ref[1:].split(".", 1)
        prefix, path = parts[0], parts[1] if len(parts) > 1 else ""
        source = {"context": context, "input": context.get("inputs", {}),
                  "data": data, "compute": compute}.get(prefix, {})
        for key in path.split("."):
            if key and isinstance(source, dict):
                source = source.get(key)
        return source if source is not None else ""

    def _resolve_refs(self, args: dict, data: dict, compute: dict) -> dict:
        """批量解析参数中的路径引用。"""
        resolved = {}
        for k, v in args.items():
            if isinstance(v, str) and v.startswith("$"):
                resolved[k] = self._resolve_ref(v, {}, compute, data)
            else:
                resolved[k] = v
        return resolved

    def _build_compose_prompt(self, blueprint: Blueprint, data: dict, compute: dict) -> str:
        """构建 AI compose 阶段的用户消息。"""
        return f"""## Data Context
```json
{json.dumps(data, indent=2, ensure_ascii=False, default=str)}
```

## Compute Results
```json
{json.dumps(compute, indent=2, ensure_ascii=False, default=str)}
```

## UI Composition Spec
{json.dumps(blueprint.ui_composition.model_dump(by_alias=True), indent=2)}

## Component Registry
Available component types: kpi_grid, chart, table, markdown, suggestion_list, question_generator.

Generate the report following the UI Composition spec above.
Map compute results to components. Use tools if additional data is needed.
Output ONLY a valid JSON report object with meta, layout, and tabs."""

    @staticmethod
    def _is_json(s: str) -> bool:
        try:
            json.loads(s)
            return True
        except (json.JSONDecodeError, TypeError):
            return False
```

### 7. FastAPI App (`main.py`)

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config.settings import get_settings

from api.workflow import router as workflow_router
from api.report import router as report_router
from api.intent import router as intent_router
from api.health import router as health_router

settings = get_settings()

app = FastAPI(title="Insight AI Agent Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

app.include_router(workflow_router)
app.include_router(report_router)
app.include_router(intent_router)
app.include_router(health_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port)
```

### 8. SSE Endpoint (`api/report.py`)

```python
import json
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from agents.executor import ExecutorAgent
from agents.provider import create_model
from models.request import ReportGenerateRequest, ReportChatRequest
from pydantic_ai import Agent

router = APIRouter()

@router.post("/api/report/generate")
async def generate_report(request: ReportGenerateRequest):
    agent = ExecutorAgent()

    async def event_stream():
        async for event in agent.execute_blueprint_stream(
            blueprint=request.blueprint,
            context=request.context or {},
        ):
            yield {"data": json.dumps(event, ensure_ascii=False)}

    return EventSourceResponse(event_stream())


@router.post("/api/report/chat")
async def report_chat(request: ReportChatRequest):
    model = create_model()
    agent = Agent(
        model=model,
        system_prompt=f"你是报告分析助手。报告摘要：{request.report_context}",
    )
    result = await agent.run(request.user_message)
    return {"success": True, "chat_response": result.data}
```

### 9. Config (`config/settings.py`)

```python
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM (LiteLLM model names with provider prefix)
    planner_model: str = "openai/gpt-4o-mini"
    executor_model: str = "openai/gpt-4o"
    router_model: str = "openai/gpt-4o-mini"

    # Provider API Keys (LiteLLM 自动从环境变量读取)
    # OPENAI_API_KEY, ANTHROPIC_API_KEY, DASHSCOPE_API_KEY 等

    # Java Backend
    java_backend_url: str = "http://localhost:8080"
    use_mock_data: bool = True
    tool_timeout: float = 10.0

    # Service
    service_port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = {"env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

---

## SSE 输出契约

Python 服务必须输出与 `frontend-python-integration.md §1.2` 一致的 SSE 格式：

```
data: {"type":"PHASE","phase":"data","message":"Fetching data..."}
data: {"type":"TOOL_CALL","tool":"get_class_detail","args":{...}}
data: {"type":"TOOL_RESULT","tool":"get_class_detail","result":{...}}
data: {"type":"PHASE","phase":"compute","message":"Computing analytics..."}
data: {"type":"TOOL_CALL","tool":"calculate_stats","args":{...}}
data: {"type":"TOOL_RESULT","tool":"calculate_stats","result":{...}}
data: {"type":"PHASE","phase":"compose","message":"Composing report..."}
data: {"type":"MESSAGE","content":"Based on my analysis..."}
data: {"type":"MESSAGE","content":"**Key Findings:**\n- Class average: 72.5%"}
data: {"type":"COMPLETE","message":"completed","progress":100,"result":{"response":"...","chatResponse":"...","report":{"meta":{...},"layout":"tabs","tabs":[...]}}}
```

**关键约束：**
- `COMPLETE.result.report` 输出 **camelCase** keys（用 Pydantic `alias_generator=to_camel`）
- 前端 `handleSSEStream()` 只消费 `MESSAGE` 和 `COMPLETE`，忽略其他类型
- `PHASE` 事件是可选的，前端忽略未知类型，向后兼容

---

## CamelCase 输出

所有 API response model 继承 `CamelModel`：

```python
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
```

Python 内部用 `snake_case`，序列化输出 `camelCase`。
Next.js proxy 直接透传，不做转换。

---

## Blueprint 完整示例

"Analyze Form 1A English performance" → PlannerAgent 输出的 Blueprint JSON：

```json
{
  "id": "bp-1706900000",
  "name": "Class Performance Analysis",
  "description": "Comprehensive analysis of class performance with KPIs, score distribution, and recommendations",
  "icon": "chart",
  "category": "analytics",
  "version": 1,
  "capabilityLevel": 1,
  "sourcePrompt": "Analyze Form 1A English performance",
  "createdAt": "2026-02-02T10:00:00Z",

  "dataContract": {
    "inputs": [
      {"id": "class", "type": "class", "label": "Select Class", "required": true},
      {"id": "assignment", "type": "assignment", "label": "Select Assignment", "required": true, "dependsOn": "class"}
    ],
    "bindings": [
      {
        "id": "class_detail",
        "sourceType": "tool",
        "toolName": "get_class_detail",
        "paramMapping": {"teacher_id": "$context.teacherId", "class_id": "$input.class"},
        "required": true,
        "dependsOn": []
      },
      {
        "id": "submissions",
        "sourceType": "tool",
        "toolName": "get_assignment_submissions",
        "paramMapping": {"teacher_id": "$context.teacherId", "assignment_id": "$input.assignment"},
        "required": true,
        "dependsOn": []
      }
    ]
  },

  "computeGraph": {
    "nodes": [
      {
        "id": "score_stats",
        "type": "tool",
        "toolName": "calculate_stats",
        "toolArgs": {"data": "$data.submissions.scores", "metrics": ["mean", "median", "stddev", "min", "max", "percentiles", "distribution"]},
        "dependsOn": ["submissions"],
        "outputKey": "scoreStats"
      },
      {
        "id": "narrative_overview",
        "type": "ai",
        "promptTemplate": "Based on the class data and statistics, write a concise overview of class performance. Include key findings and trends.",
        "dependsOn": ["score_stats", "class_detail"],
        "outputKey": "narrativeOverview"
      },
      {
        "id": "teaching_suggestions",
        "type": "ai",
        "promptTemplate": "Based on the performance data and error patterns, generate 3-5 actionable teaching recommendations with priority levels.",
        "dependsOn": ["score_stats"],
        "outputKey": "teachingSuggestions"
      }
    ]
  },

  "uiComposition": {
    "layout": "tabs",
    "tabs": [
      {
        "id": "overview",
        "label": "Overview",
        "slots": [
          {
            "id": "kpi",
            "componentType": "kpi_grid",
            "dataBinding": "$compute.scoreStats",
            "props": {}
          },
          {
            "id": "dist_chart",
            "componentType": "chart",
            "dataBinding": "$compute.scoreStats.distribution",
            "props": {"variant": "bar", "title": "Score Distribution"}
          },
          {
            "id": "overview_text",
            "componentType": "markdown",
            "dataBinding": "$compute.narrativeOverview",
            "props": {"variant": "insight"},
            "aiContentSlot": true
          }
        ]
      },
      {
        "id": "details",
        "label": "Details",
        "slots": [
          {
            "id": "student_table",
            "componentType": "table",
            "dataBinding": "$data.submissions",
            "props": {"title": "Student Results"}
          },
          {
            "id": "suggestions",
            "componentType": "suggestion_list",
            "dataBinding": "$compute.teachingSuggestions",
            "props": {"title": "Teaching Recommendations"},
            "aiContentSlot": true
          }
        ]
      }
    ]
  },

  "reportSystemPrompt": "You are an educational data analyst. Generate precise, data-driven analysis. Use tools for all numeric calculations. Never fabricate statistics."
}
```

**关键特征：**
- 换班级/换作业只需改 `$input.class` 和 `$input.assignment`，Blueprint 结构不变
- 统计指标（mean, distribution）由 `calculate_stats` tool 计算，结果可信
- 叙事概述和建议由 AI 生成，但基于 tool 计算结果，不会伪造数字
- UI 只使用注册表中的 6 种组件，无法注入任意代码

---

## Implementation Phases

### Phase 1: Foundation + Blueprint 模型
- [ ] FastAPI + uvicorn + health endpoint
- [ ] `models/blueprint.py`: Blueprint, DataContract, ComputeGraph, UIComposition
- [ ] `models/base.py`: CamelModel
- [ ] `config/component_registry.py`: 6 种组件注册
- [ ] FastMCP tools: data (mock) + stats
- [ ] 验证: `fastmcp dev tools/__init__.py` 测试 tools
- [ ] 验证: Blueprint Pydantic model 可正确序列化为 camelCase JSON

### Phase 2: PlannerAgent (Blueprint 生成)
- [ ] `agents/provider.py`: PydanticAI + LiteLLM 集成
- [ ] `agents/planner.py`: user prompt → Blueprint (result_type=Blueprint)
- [ ] `config/prompts/planner.py`: system prompt（包含组件注册表、三层结构指导）
- [ ] `api/workflow.py`: POST `/api/workflow/generate`
- [ ] 验证: curl 测试，检查返回的 Blueprint JSON 三层结构完整

### Phase 3: ExecutorAgent (Blueprint 执行, Level 1)
- [ ] `agents/executor.py`: 三阶段执行（data → compute → compose）
- [ ] DataContract resolver: 按依赖顺序调用 tools
- [ ] ComputeGraph executor: TOOL 节点确定性执行，AI 节点生成
- [ ] UI composer: 映射计算结果到 ComponentSlots
- [ ] SSE endpoint `/api/report/generate`
- [ ] 验证: curl SSE 输出 → COMPLETE.result.report 匹配 block 格式

### Phase 4: Router + Chat
- [ ] `agents/router.py`: RouterAgent + `/api/intent/classify`
- [ ] `agents/chat.py`: ChatAgent + `/api/report/chat`

### Phase 5: Java Backend
- [ ] mock → httpx 调 Java API
- [ ] Error handling + retry

### Phase 6: Frontend Integration + Level 2
- [ ] Next.js proxy routes (见 frontend-python-integration.md §5)
- [ ] Level 2: 组件 ai_content_slot 支持
- [ ] E2E 测试

---

## Development

```bash
# Python service
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Test tools interactively
fastmcp dev tools/__init__.py

# Verify Blueprint generation
curl -X POST http://localhost:8000/api/workflow/generate \
  -H "Content-Type: application/json" \
  -d '{"user_prompt":"Analyze Form 1A English performance"}'

# Verify SSE
curl -N -X POST http://localhost:8000/api/report/generate \
  -H "Content-Type: application/json" \
  -d '{"blueprint":{...},"context":{"teacherId":"t-001"}}'
```

`.env`:
```
# LLM Models (LiteLLM provider/model format)
PLANNER_MODEL=openai/gpt-4o-mini
EXECUTOR_MODEL=openai/gpt-4o
ROUTER_MODEL=openai/gpt-4o-mini

# Provider API Keys (LiteLLM reads these automatically)
OPENAI_API_KEY=sk-xxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxx
DASHSCOPE_API_KEY=sk-xxxxx

# Java Backend
JAVA_BACKEND_URL=http://localhost:8080
USE_MOCK_DATA=true

# Service
SERVICE_PORT=8000
CORS_ORIGINS=["http://localhost:3000"]
```
