# Frontend ↔ Python Service Integration Specification

> 前端和 Python 服务的对接方案。定义了 API 契约、SSE 协议、字段映射、前端改造点。
> 核心概念：**Blueprint（可执行蓝图）** — 详见 [python-service.md](./python-service.md)。

---

## Architecture: Three Layers

```
┌──────────────────────────────────────────────────────────────────┐
│  Layer 1: React Pages & Components (不改)                        │
│                                                                    │
│  build/[id]/page.tsx     apps/[id]/page.tsx                       │
│       │                        │                                   │
│       ▼                        ▼                                   │
│  ┌──────────────────────────────────────────────┐                 │
│  │  studio-agents.ts (客户端调用层)               │                 │
│  │  generateWorkflow()   → fetch /api/ai/...    │                 │
│  │  generateReport()     → fetch /api/ai/...    │                 │
│  │  chatWithReport()     → fetch /api/ai/...    │                 │
│  │  handleSSEStream()    → parse SSE events     │                 │
│  └──────────────┬───────────────────────────────┘                 │
│                 │                                                  │
│                 │  fetch('/api/ai/xxx')                            │
│                 ▼                                                  │
│  ┌──────────────────────────────────────────────┐                 │
│  │  Layer 2: Next.js API Routes (改为 Proxy)     │ ← 唯一改动层    │
│  │  /api/ai/workflow-generate  → proxy           │                 │
│  │  /api/ai/report-generate    → proxy + SSE     │                 │
│  │  /api/ai/report-chat        → proxy           │                 │
│  │  /api/ai/classify-intent    → proxy (新增)    │                 │
│  └──────────────┬───────────────────────────────┘                 │
└─────────────────┼────────────────────────────────────────────────┘
                  │  HTTP / SSE
                  ▼
┌──────────────────────────────────────────────────────────────────┐
│  Layer 3: Python Service (FastAPI + PydanticAI)                   │
│                                                                    │
│  POST /api/workflow/generate     ← PlannerAgent → Blueprint      │
│  POST /api/report/generate       ← ExecutorAgent (执行 Blueprint) │
│  POST /api/report/chat           ← ChatAgent                     │
│  POST /api/intent/classify       ← RouterAgent                   │
│  GET  /api/health                                                 │
└──────────────────────────────────────────────────────────────────┘
```

**核心原则：前端 React 层零改动。** 所有变化封装在 Next.js API Routes 这一层。

---

## 1. API Contract: 四个端点

### 1.1 Workflow Generate (PlannerAgent → Blueprint)

生成 Blueprint（可执行蓝图）。Blocking 模式，不需要 streaming。

```
Frontend                    Next.js Proxy                 Python Service
────────                    ─────────────                 ──────────────

POST /api/ai/               POST /api/workflow/
workflow-generate            generate

{                  ──►      {                    ──►     PlannerAgent
  userPrompt:                 user_prompt:                (result_type=Blueprint)
  "Analyze..."                "Analyze...",
}                             language: "en"
                              }

                  ◄──       {                    ◄──     Blueprint JSON
{                             success: true,
  success: true,              chat_response: "...",
  chatResponse: "...",        blueprint: {
  blueprint: {                  id: "bp-...",
    id: "bp-...",               name: "...",
    name: "...",                data_contract: {...},
    dataContract: {             compute_graph: {...},
      inputs: [...],            ui_composition: {...},
      bindings: [...]           report_system_prompt: "..."
    },                        }
    computeGraph: {...},      }
    uiComposition: {...},
    reportSystemPrompt: "..."
  }
}
```

**Python Request Schema:**

```python
class WorkflowGenerateRequest(BaseModel):
    user_prompt: str          # 用户原始输入
    language: str = "en"      # 输出语言
```

**Python Response Schema:**

```python
class WorkflowGenerateResponse(CamelModel):
    success: bool
    chat_response: str
    blueprint: BlueprintOutput


class BlueprintOutput(CamelModel):
    """Blueprint as returned by PlannerAgent."""
    # 元数据
    id: str                                      # f"bp-{timestamp}"
    name: str
    description: str
    icon: str = "chart"
    category: str = "analytics"
    version: int = 1
    capability_level: int = 1
    created_at: str                              # ISO timestamp
    source_prompt: str                           # 原始用户输入

    # 三层
    data_contract: DataContractOutput            # Layer A
    compute_graph: ComputeGraphOutput            # Layer B
    ui_composition: UICompositionOutput          # Layer C

    # ExecutorAgent 上下文
    report_system_prompt: str
```

**前端消费 `blueprint.dataContract.inputs`** 来渲染数据选择 UI（班级、作业等），
替代原来的 `workflow.dataInputs`。`DataInputSpec` 格式不变。

**Proxy 逻辑 (Next.js):**

```typescript
// src/app/api/ai/workflow-generate/route.ts
export async function POST(request: NextRequest) {
  const { userPrompt } = await request.json();

  const upstream = await fetch(`${PYTHON_SERVICE_URL}/api/workflow/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_prompt: userPrompt }),
  });

  // Python 服务已输出 camelCase，直接透传
  const result = await upstream.json();
  return NextResponse.json(result);
}
```

---

### 1.2 Report Generate (ExecutorAgent — Blueprint 执行, SSE Streaming)

最关键的端点。Python 服务**执行 Blueprint**（三阶段），输出 SSE stream，Next.js 透传。

```
Frontend                  Next.js Proxy              Python Service
────────                  ─────────────              ──────────────

POST /api/ai/             POST /api/report/
report-generate           generate

{                  ──►    {                   ──►    ExecutorAgent
  blueprint: {...},         blueprint: {...},          (execute Blueprint)
  data: {...},              data: {...},
  context: {                context: {
    teacherId: "t-001"       teacher_id: "t-001"
  }                         }
}                           }

                  ◄──     SSE stream            ◄──  SSE stream
SSE stream
```

**Blueprint 执行流程：**

```
Phase 1: Data    → 解析 DataContract，调用 tools 获取数据
Phase 2: Compute → 执行 ComputeGraph（先 TOOL 节点，后 AI 节点）
Phase 3: Compose → 映射计算结果到 UIComposition，生成 report JSON
```

**SSE 事件协议（核心契约）：**

Python 服务必须输出以下格式的 SSE 事件，这是前端 `handleSSEStream()` 解析的格式：

```
# (可选) 阶段事件 - 前端当前忽略
data: {"type":"PHASE","phase":"data","message":"Fetching data..."}

# (可选) 工具调用事件 - 前端当前忽略，可用于未来 UI 展示
data: {"type":"TOOL_CALL","tool":"get_class_detail","args":{"class_id":"class-hk-f1a"}}
data: {"type":"TOOL_RESULT","tool":"get_class_detail","status":"success"}

data: {"type":"PHASE","phase":"compute","message":"Computing analytics..."}
data: {"type":"TOOL_CALL","tool":"calculate_stats","args":{...}}
data: {"type":"TOOL_RESULT","tool":"calculate_stats","result":{...}}

data: {"type":"PHASE","phase":"compose","message":"Composing report..."}

# 文本流事件 (多次)
data: {"type":"MESSAGE","content":"Based on my "}
data: {"type":"MESSAGE","content":"analysis of "}
data: {"type":"MESSAGE","content":"Form 1A's performance..."}

# 完成事件 (必须, 且只发一次)
data: {"type":"COMPLETE","message":"completed","progress":100,"result":{"response":"...full text...","chatResponse":"Based on my analysis...","report":{"meta":{...},"layout":"tabs","tabs":[...]}}}
```

**前端解析逻辑 (不改动):**

```typescript
// studio-agents.ts handleSSEStream() 解析规则:
// 1. 逐行读取 SSE: "data: {...}\n\n"
// 2. 解析 JSON
// 3. type === 'MESSAGE' → accumulated += content; callbacks.onMessage(content)
// 4. type === 'COMPLETE' → finalResult = { chatResponse, report }; callbacks.onComplete(finalResult)
// 5. 忽略其他 type (PHASE, TOOL_CALL, TOOL_RESULT 等)
```

**COMPLETE 事件 `result` 字段结构：**

```typescript
{
  result: {
    response: string,        // 完整的原始 LLM 输出文本
    chatResponse: string,    // 提取出的对话回复 (Markdown)
    report: {                // 提取出的报告结构 (JSON)
      meta: {
        reportTitle: string,       // 必须! 前端渲染依赖
        frameworkUsed?: string,
        summary?: string,
        generatedAt: string,
        dataSource?: string,
      },
      layout: "tabs" | "single_page",
      tabs: [
        {
          id: string,
          label: string,
          blocks: [
            // Block 类型见下文 §3
          ]
        }
      ]
    }
  }
}
```

**Python Request Schema:**

```python
class ReportGenerateRequest(CamelModel):
    blueprint: dict                              # 完整 Blueprint JSON
    data: dict                                   # 用户选择的数据（班级/作业/学生）
    context: dict | None = None                  # 运行时上下文（teacherId 等）
```

**Proxy 逻辑 (Next.js) - SSE 透传:**

```typescript
// src/app/api/ai/report-generate/route.ts
export async function POST(request: NextRequest) {
  const body = await request.json();

  const upstream = await fetch(`${PYTHON_SERVICE_URL}/api/report/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      blueprint: body.blueprint,
      data: body.data,
      context: body.context,
    }),
  });

  // SSE 直接透传 - Python 服务输出与前端期望的格式完全一致
  return new NextResponse(upstream.body, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}
```

**重要**: SSE stream 里的 `COMPLETE` 事件中 `result.report` 必须是 **camelCase**（不是 snake_case），因为前端 ReportRenderer 直接消费这个 JSON。Python 服务用 Pydantic `alias_generator` 输出 camelCase。

---

### 1.3 Report Chat (Follow-up Questions)

非流式端点，用于追问已有报告。**无变更。**

```
Frontend                  Next.js Proxy              Python Service
────────                  ─────────────              ──────────────

POST /api/ai/             POST /api/report/
report-chat               chat

{                  ──►    {                   ──►    Chat Agent
  userMessage:              user_message:
  "哪些学生...",            "哪些学生...",
  reportContext: {          report_context: {
    meta: {...},              meta: {...},
    dataSummary: "..."        data_summary: "..."
  },                        },
  data: {...}               data: {...}
}                           }

{                  ◄──    {                   ◄──    Text response
  success: true,            success: true,
  chatResponse: "..."       chat_response: "..."
}                           }
```

**Python Request:**

```python
class ReportChatRequest(BaseModel):
    user_message: str
    report_context: dict | None = None    # { meta, data_summary }
    data: dict | None = None              # 原始数据 (可选)
```

**Python Response:**

```python
class ReportChatResponse(BaseModel):
    success: bool
    chat_response: str                    # Markdown 格式
```

---

### 1.4 Classify Intent (Follow-up Router) - 新增

替换当前的关键词路由。前端调用此端点判断用户追问走哪个路径。**无变更。**

```
Frontend                  Next.js Proxy              Python Service
────────                  ─────────────              ──────────────

POST /api/ai/             POST /api/intent/
classify-intent           classify

{                  ──►    {                   ──►    Router Agent
  userMessage:              user_message:             (fast classification)
  "增加语法...",            "增加语法...",
  workflowName:             workflow_name:
  "Performance...",         "Performance...",
  reportSummary:            report_summary:
  "Overall good..."        "Overall good..."
}                           }

{                  ◄──    {                   ◄──    Classification
  intent:                   intent:
  "workflow_rebuild",       "workflow_rebuild",
  confidence: 0.92          confidence: 0.92
}                           }
```

**Intent 值和前端处理逻辑:**

| Intent | 前端动作 | 调用的函数 |
|--------|---------|-----------|
| `workflow_rebuild` | 重新生成 Blueprint + report | `generateWorkflow()` → `generateReport()` |
| `report_refine` | 仅重新生成 report | `generateReport()` (带修改指令) |
| `data_chat` | 追问对话 | `chatWithReport()` |

---

## 1.5 Blueprint 概念（面向前端开发者）

### 什么是 Blueprint（可执行蓝图）

Blueprint 取代了原来的 WorkflowTemplate。它不只是"报告大纲"，而是一个三层可执行计划：

```
Blueprint
├── dataContract           ← 需要什么数据、怎么拿
│   ├── inputs                前端渲染的数据选择 UI（班级/作业/学生）
│   └── bindings              Python 端执行的数据获取声明
│
├── computeGraph           ← 哪些确定性计算（可信）、哪些 AI 生成
│   └── nodes                 tool 节点 = 精确统计，ai 节点 = 叙事/建议
│
├── uiComposition          ← 用什么组件、怎么排列
│   └── tabs → slots          从组件注册表中选择（kpi_grid, chart, ...）
│
└── reportSystemPrompt     ← AI 的上下文提示
```

### 前端只关心什么

**前端只读 Blueprint 的两个部分：**

1. **`blueprint.dataContract.inputs`** — 渲染数据选择 UI。格式与原来的 `dataInputs` 完全一致。
2. **`blueprint` 整体** — 回传给 `/api/report/generate` 执行。前端不需要理解 `computeGraph` 或 `uiComposition` 的细节。

**报告输出格式完全不变。** `COMPLETE.result.report` 仍然是 `{ meta, layout, tabs: [{ id, label, blocks }] }`。

### 三级能力模型

```
┌─────────────────────────────────────────────────────────────┐
│  Level 1（当前）: 固定组件 + AI 排版                          │
│                                                               │
│  AI 从注册表选组件、决定排列和数据绑定。                        │
│  前端零改动：报告 JSON 格式完全不变。                          │
├─────────────────────────────────────────────────────────────┤
│  Level 2（增强）: 组件插槽 + AI 填内容                        │
│                                                               │
│  AI 在组件内部填充 markdown 叙事、建议条目等。                  │
│  前端可能需要小改：组件接受动态内容插槽。                       │
├─────────────────────────────────────────────────────────────┤
│  Level 3（未来）: 受限微应用                                   │
│                                                               │
│  AI 生成 Python function + 前端 UI（沙箱执行）。              │
│  前端需要新增 iframe 沙箱渲染器。延期实现。                    │
└─────────────────────────────────────────────────────────────┘
```

**Level 1 的前端影响 = 零。** 所有 React 组件、ReportRenderer、studio-agents.ts 均不改动。

---

## 2. Field Name Mapping (camelCase ↔ snake_case)

### 原则

- **Python ↔ Next.js Proxy**: Python 端用 Pydantic `alias_generator` 直接输出 camelCase
- **Next.js Proxy ↔ Frontend**: camelCase（TypeScript 标准）
- **SSE stream 内的 report JSON**: camelCase（直接给 ReportRenderer 消费）

### 方案: Python 用 Pydantic alias 输出 camelCase

**推荐 Python 端处理**，而不是 Next.js Proxy 转换。原因：
1. SSE stream 是透传的，Proxy 不方便逐 chunk 转换
2. Report JSON 结构深层嵌套，递归转换容易出错
3. Pydantic v2 原生支持 alias_generator

```python
# models/base.py
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

class CamelModel(BaseModel):
    """所有 API 响应模型的基类，输出 camelCase"""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,     # 内部仍用 snake_case
    )
```

### 完整字段映射表

**原有字段（不变）：**

| Python (内部) | JSON Output (camelCase) | 前端 TypeScript |
|---------------|------------------------|-----------------|
| `chat_response` | `chatResponse` | `chatResponse` |
| `report_system_prompt` | `reportSystemPrompt` | `reportSystemPrompt` |
| `depends_on` | `dependsOn` | `dependsOn` |
| `source_prompt` | `sourcePrompt` | `sourcePrompt` |
| `created_at` | `createdAt` | `createdAt` |
| `report_title` | `reportTitle` | `reportTitle` |
| `framework_used` | `frameworkUsed` | `frameworkUsed` |
| `generated_at` | `generatedAt` | `generatedAt` |
| `data_source` | `dataSource` | `dataSource` |
| `x_axis` | `xAxis` | `xAxis` |
| `highlight_rules` | `highlightRules` | `highlightRules` |
| `knowledge_point` | `knowledgePoint` | `knowledgePoint` |
| `error_patterns` | `errorPatterns` | `errorPatterns` |

**Blueprint 新增字段：**

| Python (内部) | JSON Output (camelCase) | 前端 TypeScript |
|---------------|------------------------|-----------------|
| `data_contract` | `dataContract` | `dataContract` |
| `compute_graph` | `computeGraph` | `computeGraph` |
| `ui_composition` | `uiComposition` | `uiComposition` |
| `capability_level` | `capabilityLevel` | `capabilityLevel` |
| `source_type` | `sourceType` | `sourceType` |
| `tool_name` | `toolName` | `toolName` |
| `param_mapping` | `paramMapping` | `paramMapping` |
| `output_key` | `outputKey` | `outputKey` |
| `prompt_template` | `promptTemplate` | `promptTemplate` |
| `component_type` | `componentType` | `componentType` |
| `data_binding` | `dataBinding` | `dataBinding` |
| `ai_content_slot` | `aiContentSlot` | `aiContentSlot` |
| `tool_args` | `toolArgs` | `toolArgs` |

### Proxy 不需要转换

Python 端已统一输出 camelCase。Proxy 直接透传 JSON，不需要 `snakeToCamel` / `camelToSnake` 转换函数。

---

## 3. Report JSON Block 格式 (前端消费的完整契约)

Python 服务输出的 `report` JSON 必须严格匹配以下格式，否则 ReportRenderer 无法渲染。

> **组件注册表约束：** Blueprint 的 UIComposition 层使用这些已注册的组件类型。AI 只能从注册表中选择，不能发明新的组件类型。详见 [python-service.md §组件注册表](./python-service.md)。

### 3.1 KPI Grid

```json
{
  "type": "kpi_grid",
  "data": [
    {
      "label": "Class Average",
      "value": "72.5",
      "status": "up",
      "subtext": "+5% from last test"
    }
  ]
}
```

`status`: `"up"` | `"down"` | `"neutral"`

### 3.2 Chart

```json
{
  "type": "chart",
  "variant": "bar",
  "title": "Score Distribution",
  "xAxis": ["Multiple Choice", "Fill-in-Blank", "Short Answer"],
  "series": [
    {
      "name": "Average Score",
      "data": [82, 75, 68],
      "color": "#4F46E5"
    }
  ]
}
```

`variant`: `"bar"` | `"line"` | `"radar"` | `"pie"` | `"gauge"` | `"distribution"`

**注意**: 前端有 `normalizeChartBlock()` 能处理多种格式，但最好直接输出上述标准格式。

### 3.3 Markdown

```json
{
  "type": "markdown",
  "content": "### Key Findings\n\n1. **Strong performance** in multiple choice\n2. Application questions need improvement",
  "variant": "insight"
}
```

`variant`: `"default"` | `"insight"` | `"warning"` | `"success"`

### 3.4 Table

```json
{
  "type": "table",
  "title": "Students Needing Attention",
  "headers": ["Student", "Score", "Issue", "Recommendation"],
  "rows": [
    { "cells": ["Wong Ka Ho", 58, "Weak grammar", "Targeted practice"], "status": "warning" },
    { "cells": ["Li Mei", 85, "Strong overall", "Extension tasks"], "status": "success" }
  ],
  "highlightRules": [
    { "column": 1, "condition": "below", "value": 60, "style": "warning" }
  ]
}
```

`rows[].status`: `"normal"` | `"warning"` | `"success"` | `"error"` (可选)

### 3.5 Suggestion List

```json
{
  "type": "suggestion_list",
  "title": "Teaching Recommendations",
  "items": [
    {
      "title": "Grammar Focused Training",
      "description": "Design exercises targeting subject-verb agreement",
      "priority": "high",
      "category": "Teaching Strategy"
    }
  ]
}
```

**关键**: `items` 必须是对象数组，不能是字符串数组。前端有 `normalizeSuggestionListBlock()` 兼容字符串，但最好直接输出对象。

`priority`: `"high"` | `"medium"` | `"low"`

### 3.6 Question Generator

```json
{
  "type": "question_generator",
  "title": "Grammar Practice",
  "description": "Based on common errors in Unit 5",
  "knowledgePoint": "Present Simple Tense",
  "questions": [
    {
      "id": "q1",
      "order": 1,
      "type": "multiple_choice",
      "question": "She ___ to school every day.",
      "options": ["go", "goes", "going", "went"],
      "answer": "goes",
      "explanation": "Third person singular requires 'goes'",
      "difficulty": "easy"
    }
  ],
  "context": {
    "errorPatterns": ["Subject-verb agreement"],
    "difficulty": "medium"
  }
}
```

`questions[].type`: `"multiple_choice"` | `"fill_in_blank"` | `"short_answer"` | `"true_false"`

---

## 4. 前端改动清单 (最小化)

### 4.1 必须改的文件 (4 个 API routes)

| 文件 | 改动内容 | 行数 |
|------|---------|------|
| `src/app/api/ai/workflow-generate/route.ts` | Dify → Python proxy，response 用 `blueprint` | ~30 行 |
| `src/app/api/ai/report-generate/route.ts` | Dify SSE → Python SSE 透传，request 含 `blueprint` | ~25 行 |
| `src/app/api/ai/report-chat/route.ts` | Dify → Python proxy | ~20 行 |
| `src/lib/env.ts` | 添加 `PYTHON_SERVICE_URL` | ~3 行 |

### 4.2 新增的文件 (1 个)

| 文件 | 内容 |
|------|------|
| `src/app/api/ai/classify-intent/route.ts` | 意图分类 proxy (新端点) |

### 4.3 需要小改的文件 (1-2 个，可选)

| 文件 | 改动内容 |
|------|---------|
| `src/lib/studio-agents.ts` | `generateWorkflow()` 返回值从 `result.workflow` 改为 `result.blueprint`，读取 `blueprint.dataContract.inputs` 代替 `workflow.dataInputs` |
| `src/lib/studio-router.ts` | `getRouteType()` 改为 async，调用 `/api/ai/classify-intent` |

**注意**: 如果暂时不做 LLM 路由，可以保留关键词路由不改。

### 4.4 完全不改的文件

| 文件 | 原因 |
|------|------|
| `src/lib/studio-agents.ts` (handleSSEStream) | SSE 解析逻辑不变，PHASE 等未知 type 自动忽略 |
| `src/types/studio-workflow.ts` | 需更新类型定义（Blueprint 替代 Workflow），但渲染逻辑不变 |
| `src/config/studio-agent-prompts.ts` | Prompt 迁移到 Python，此文件保留作为 fallback |
| `src/lib/studio-storage.ts` | 存储逻辑不涉及 AI |
| `src/lib/studio-data-router.ts` | Mock 数据路由保留 |
| `src/components/studio/*` | 所有 UI 组件不改 |
| `src/components/studio/report-renderer/*` | 报告渲染组件不改，输出 block 格式不变 |
| `src/app/teacher/studio/**` | 所有页面不改 |

---

## 5. Proxy Route 完整代码

### 5.1 `workflow-generate/route.ts` (重写)

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerConfig } from '@/lib/env';
import { getDefaultWorkflowTemplate } from '@/config/studio-agent-prompts';

export const runtime = 'nodejs';
export const maxDuration = 30;

export async function POST(request: NextRequest) {
  try {
    const { userPrompt } = await request.json();

    if (!userPrompt || typeof userPrompt !== 'string') {
      return NextResponse.json(
        { success: false, error: 'userPrompt is required' },
        { status: 400 }
      );
    }

    const { PYTHON_SERVICE_URL } = getServerConfig();

    if (!PYTHON_SERVICE_URL) {
      // Fallback: 使用本地默认模板（转为 blueprint 格式）
      const fallback = getDefaultWorkflowTemplate(userPrompt);
      return NextResponse.json({
        success: true,
        chatResponse: `Creating "${fallback.name}" blueprint.`,
        blueprint: {
          ...fallback,
          id: `bp-${Date.now()}`,
          version: 1,
          capabilityLevel: 1,
          createdAt: new Date().toISOString(),
          sourcePrompt: userPrompt,
          dataContract: { inputs: fallback.dataInputs || [], bindings: [] },
          computeGraph: { nodes: [] },
          uiComposition: { layout: 'tabs', tabs: [] },
        },
      });
    }

    const upstream = await fetch(`${PYTHON_SERVICE_URL}/api/workflow/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_prompt: userPrompt }),
    });

    if (!upstream.ok) {
      console.error('Python service error:', upstream.status);
      // Fallback
      const fallback = getDefaultWorkflowTemplate(userPrompt);
      return NextResponse.json({
        success: true,
        chatResponse: `Creating "${fallback.name}" blueprint.`,
        blueprint: {
          ...fallback,
          id: `bp-${Date.now()}`,
          version: 1,
          capabilityLevel: 1,
          createdAt: new Date().toISOString(),
          sourcePrompt: userPrompt,
          dataContract: { inputs: fallback.dataInputs || [], bindings: [] },
          computeGraph: { nodes: [] },
          uiComposition: { layout: 'tabs', tabs: [] },
        },
      });
    }

    // Python 服务已输出 camelCase，直接透传
    const result = await upstream.json();
    return NextResponse.json(result);
  } catch (error) {
    console.error('Workflow generate route error:', error);
    return NextResponse.json(
      { success: false, error: 'Internal server error' },
      { status: 500 }
    );
  }
}
```

### 5.2 `report-generate/route.ts` (重写)

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerConfig } from '@/lib/env';

export const runtime = 'nodejs';
export const maxDuration = 120;

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    if (!body.blueprint || typeof body.blueprint !== 'object') {
      return NextResponse.json(
        { success: false, error: 'blueprint is required' },
        { status: 400 }
      );
    }

    const { PYTHON_SERVICE_URL } = getServerConfig();

    if (!PYTHON_SERVICE_URL) {
      return createMockStreamResponse(body.data);
    }

    const upstream = await fetch(`${PYTHON_SERVICE_URL}/api/report/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        blueprint: body.blueprint,
        data: body.data,
        context: body.context,
      }),
    });

    if (!upstream.ok) {
      console.error('Python service error:', upstream.status);
      return createMockStreamResponse(body.data);
    }

    // SSE 直接透传 - Python 服务输出与前端期望的格式完全一致
    return new NextResponse(upstream.body, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    });
  } catch (error) {
    console.error('Report generate route error:', error);
    return NextResponse.json(
      { success: false, error: 'Internal server error' },
      { status: 500 }
    );
  }
}

// 保留现有的 createMockStreamResponse 作为 fallback
function createMockStreamResponse(data: Record<string, unknown>) {
  // ... 与当前代码相同 ...
}
```

### 5.3 `report-chat/route.ts` (重写)

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerConfig } from '@/lib/env';

export const runtime = 'nodejs';
export const maxDuration = 30;

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { userMessage, reportContext, data } = body;

    if (!userMessage || typeof userMessage !== 'string') {
      return NextResponse.json(
        { success: false, error: 'userMessage is required' },
        { status: 400 }
      );
    }

    const { PYTHON_SERVICE_URL } = getServerConfig();

    if (!PYTHON_SERVICE_URL) {
      return NextResponse.json({
        success: true,
        chatResponse: getMockChatResponse(userMessage),
      });
    }

    const upstream = await fetch(`${PYTHON_SERVICE_URL}/api/report/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_message: userMessage,
        report_context: reportContext,
        data,
      }),
    });

    if (!upstream.ok) {
      return NextResponse.json({
        success: true,
        chatResponse: getMockChatResponse(userMessage),
      });
    }

    const result = await upstream.json();
    return NextResponse.json({
      success: result.success,
      chatResponse: result.chatResponse,
    });
  } catch (error) {
    console.error('Report chat route error:', error);
    return NextResponse.json(
      { success: false, error: 'Internal server error' },
      { status: 500 }
    );
  }
}

// 保留 mock 回复
function getMockChatResponse(userMessage: string): string {
  // ... 与当前代码相同 ...
}
```

### 5.4 `classify-intent/route.ts` (新增)

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerConfig } from '@/lib/env';

export const runtime = 'nodejs';
export const maxDuration = 10;

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { userMessage, workflowName, reportSummary } = body;

    const { PYTHON_SERVICE_URL } = getServerConfig();

    if (!PYTHON_SERVICE_URL) {
      // Fallback: 使用本地关键词路由
      const { shouldRegenerateWorkflow } = await import('@/lib/studio-router');
      return NextResponse.json({
        intent: shouldRegenerateWorkflow(userMessage) ? 'workflow_rebuild' : 'data_chat',
        confidence: 0.5,
      });
    }

    const upstream = await fetch(`${PYTHON_SERVICE_URL}/api/intent/classify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_message: userMessage,
        workflow_name: workflowName,
        report_summary: reportSummary,
      }),
    });

    if (!upstream.ok) {
      // Fallback to keyword router
      const { shouldRegenerateWorkflow } = await import('@/lib/studio-router');
      return NextResponse.json({
        intent: shouldRegenerateWorkflow(userMessage) ? 'workflow_rebuild' : 'data_chat',
        confidence: 0.5,
      });
    }

    return NextResponse.json(await upstream.json());
  } catch (error) {
    console.error('Classify intent error:', error);
    return NextResponse.json({
      intent: 'data_chat',
      confidence: 0,
    });
  }
}
```

### 5.5 `env.ts` 添加 PYTHON_SERVICE_URL

```typescript
// 在 ServerEnvKey 类型中添加:
type ServerEnvKey =
  | ... // 现有的
  | 'PYTHON_SERVICE_URL';

// 在 getServerConfig() 中添加:
PYTHON_SERVICE_URL: getServerEnv('PYTHON_SERVICE_URL', ''),
```

---

## 6. Mock 数据策略

### 当前状态

Mock 数据在前端 (`src/data/mock-studio-*.ts`)，通过 `getMockDataForWorkflow()` 在**前端**组装后传给 ExecutorAgent。

### 迁移策略

**Phase 1 (保持现状)**: Mock 数据仍在前端，前端组装好后通过 `data` 字段传给 Python。Python 服务直接使用收到的数据，不需要自己的数据源。

```
前端选择 class + assignment → getMockDataForWorkflow() → data JSON → Python ExecutorAgent
```

**Phase 2 (数据迁移到 Python)**: Mock 数据移到 Python 服务的 `services/mock_data.py`。前端只传 ID，ExecutorAgent 通过 Blueprint 的 DataContract 获取数据。

```
前端选择 class + assignment → { context: { teacherId, classId, assignmentId } } → ExecutorAgent → DataContract → tools
```

**Phase 1 不需要改前端任何代码。** `getMockDataForWorkflow()` 继续工作，数据继续通过 `data` 字段传递。

---

## 7. 错误处理协议

### Python 服务 HTTP 错误

| Status | 含义 | Proxy 处理 |
|--------|------|-----------|
| 200 | 成功 | 透传 |
| 400 | 请求参数错误 | 透传错误信息 |
| 422 | Pydantic 验证错误 | 透传或 fallback |
| 500 | 服务内部错误 | Fallback to mock |
| 503 | 服务不可用 | Fallback to mock |
| Timeout | 超时 | Fallback to mock |
| ECONNREFUSED | Python 服务未启动 | Fallback to mock |

### SSE 流错误

Python 服务在 SSE 流中遇到错误时，发送错误 COMPLETE 事件:

```
data: {"type":"COMPLETE","message":"error","progress":100,"result":{"response":"","chatResponse":"Report generation failed. Please try again.","report":null}}
```

前端 `handleSSEStream()` 已经处理了 `report: null` 的情况。

### Fallback 策略

每个 Proxy route 都保留现有的 fallback:
- `workflow-generate`: `getDefaultWorkflowTemplate()` → 转为 Blueprint 格式
- `report-generate`: `createMockStreamResponse()`
- `report-chat`: `getMockChatResponse()`

---

## 8. 环境配置

### `.env.local` (开发环境)

```env
# Python Agent Service
PYTHON_SERVICE_URL=http://localhost:8000

# Legacy Dify (移除或留空)
# DIFY_AI_BASE=
# STUDIO_API_KEY=
# STUDIO_WORKFLOW_API_KEY=
```

### `.env.production` (生产环境)

```env
# Python Agent Service (Docker 网络内)
PYTHON_SERVICE_URL=http://agent-service:8000
```

### Python `.env`

```env
# LLM Models (LiteLLM provider/model format)
PLANNER_MODEL=openai/gpt-4o-mini
EXECUTOR_MODEL=openai/gpt-4o
ROUTER_MODEL=openai/gpt-4o-mini

# Provider API Keys (LiteLLM reads automatically)
OPENAI_API_KEY=sk-...
DASHSCOPE_API_KEY=sk-...

# Service
SERVICE_PORT=8000
CORS_ORIGINS=["http://localhost:3000"]
USE_MOCK_DATA=true

# Backend (Phase 2)
JAVA_BACKEND_URL=http://localhost:8080
```

---

## 9. 开发流程

### Step 1: Python 服务启动

```bash
cd insight-ai-agent
pip install -r requirements.txt
cp .env.example .env        # 填入 API Keys
uvicorn main:app --reload --port 8000
```

验证:
```bash
curl http://localhost:8000/api/health
# → {"status": "healthy", "version": "1.0.0"}
```

### Step 2: 前端配置

```bash
cd insight_ai_frontend
echo "PYTHON_SERVICE_URL=http://localhost:8000" >> .env.local
npm run dev
```

### Step 3: 端对端测试

1. 打开 http://localhost:3000/teacher/studio
2. 输入 "Analyze Form 1A English performance"
3. 验证: PlannerAgent 返回 Blueprint (看 Network tab，检查 `dataContract`, `computeGraph`, `uiComposition` 三层)
4. 选择 Class + Assignment
5. 验证: ExecutorAgent 流式执行 Blueprint (看 EventStream tab，检查 PHASE → TOOL_CALL → MESSAGE → COMPLETE)
6. 验证: 报告正确渲染（6 种 block type）

### Step 4: 逐步切换

可以一个端点一个端点地切换：

```env
# 先只切 workflow-generate
PYTHON_SERVICE_URL=http://localhost:8000

# report-generate 暂时还走 Dify (在 route.ts 中加条件)
```

---

## 10. 测试检查清单

| 测试项 | 验证方法 |
|--------|---------|
| Python 服务健康 | `GET /api/health` 返回 200 |
| Blueprint 生成 | 5 个场景各生成一次，检查三层结构完整 |
| Blueprint 三层验证 | 检查 `dataContract.inputs`、`computeGraph.nodes`、`uiComposition.tabs` 非空 |
| ComputeGraph 确定性 | TOOL 节点产出精确统计，AI 节点产出叙事（非伪造指标） |
| SSE 流格式 | `curl -N` 检查 PHASE → TOOL_CALL → MESSAGE → COMPLETE |
| Report 渲染 | 6 种 block type 全部渲染正确 |
| camelCase | 检查 report JSON 的 key 全是 camelCase |
| 追问路由 | 测试 "增加一个维度" vs "平均分多少" |
| Fallback | 停掉 Python 服务，验证 mock 正常工作 |
| 流中断恢复 | 网络断开后，前端不崩溃 |
| 大数据量 | 35 学生完整数据，token 不超限 |

```bash
# Blueprint 生成验证
curl -X POST http://localhost:8000/api/workflow/generate \
  -H "Content-Type: application/json" \
  -d '{"user_prompt":"Analyze Form 1A English performance"}'

# 期望: {"success":true,"chatResponse":"...","blueprint":{"id":"bp-...","dataContract":{...},"computeGraph":{...},"uiComposition":{...}}}

# SSE 流格式验证
curl -N -X POST http://localhost:8000/api/report/generate \
  -H "Content-Type: application/json" \
  -d '{"blueprint":{...},"data":{},"context":{"teacherId":"t-001"}}'

# 期望输出:
# data: {"type":"PHASE","phase":"data","message":"Fetching data..."}
# data: {"type":"TOOL_CALL","tool":"get_class_detail","args":{...}}
# data: {"type":"TOOL_RESULT","tool":"get_class_detail","result":{...}}
# data: {"type":"PHASE","phase":"compose","message":"Composing report..."}
# data: {"type":"MESSAGE","content":"Based on..."}
# data: {"type":"COMPLETE","message":"completed","progress":100,"result":{...}}
```
