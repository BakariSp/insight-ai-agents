# Blueprint 数据模型

> 可执行蓝图（Blueprint）是结构化页面构建的核心数据结构，取代了原来的 WorkflowTemplate。

---

## 核心概念

Blueprint 是一个**三层可执行计划**：

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
└── page_system_prompt: str         ← ExecutorAgent 上下文提示
```

### 三层职责

| Layer | 职责 | 信任级别 | 示例 |
|-------|------|----------|------|
| A. DataContract | 声明需要什么数据、如何获取 | 声明式，安全 | `get_class_detail(classId=$input.class)` |
| B. ComputeGraph | KPI/统计 = tool（确定性），叙事/建议 = AI（生成性） | tool 节点可信，AI 节点受控 | `calculate_stats(scores, ["mean","median"])` |
| C. UIComposition | 从注册组件中选择、排列、绑定数据 | AI 选组件/排序，不能写代码 | `[kpi_grid, chart(bar), table, markdown]` |

---

## Pydantic 模型定义

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
    """可执行蓝图 — 页面的完整执行计划。"""
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
    page_system_prompt: str = ""
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

添加新组件时：
1. 前端实现新组件 + 注册到 PageRenderer
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

## 完整示例

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
        "promptTemplate": "Based on the class data and statistics, write a concise overview of class performance.",
        "dependsOn": ["score_stats", "class_detail"],
        "outputKey": "narrativeOverview"
      },
      {
        "id": "teaching_suggestions",
        "type": "ai",
        "promptTemplate": "Based on the performance data, generate 3-5 actionable teaching recommendations with priority levels.",
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
          {"id": "kpi", "componentType": "kpi_grid", "dataBinding": "$compute.scoreStats", "props": {}},
          {"id": "dist_chart", "componentType": "chart", "dataBinding": "$compute.scoreStats.distribution", "props": {"variant": "bar", "title": "Score Distribution"}},
          {"id": "overview_text", "componentType": "markdown", "dataBinding": "$compute.narrativeOverview", "props": {"variant": "insight"}, "aiContentSlot": true}
        ]
      },
      {
        "id": "details",
        "label": "Details",
        "slots": [
          {"id": "student_table", "componentType": "table", "dataBinding": "$data.submissions", "props": {"title": "Student Results"}},
          {"id": "suggestions", "componentType": "suggestion_list", "dataBinding": "$compute.teachingSuggestions", "props": {"title": "Teaching Recommendations"}, "aiContentSlot": true}
        ]
      }
    ]
  },

  "pageSystemPrompt": "You are an educational data analyst. Generate precise, data-driven analysis. Use tools for all numeric calculations. Never fabricate statistics."
}
```

**关键特征：**
- 换班级/换作业只需改 `$input.class` 和 `$input.assignment`，Blueprint 结构不变
- 统计指标（mean, distribution）由 `calculate_stats` tool 计算，结果可信
- 叙事概述和建议由 AI 生成，但基于 tool 计算结果，不会伪造数字
- UI 只使用注册表中的 6 种组件，无法注入任意代码
