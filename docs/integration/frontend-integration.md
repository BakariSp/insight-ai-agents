# 前端集成规范

> Python 服务 API 契约：端点、请求/响应格式、SSE 协议、Blueprint 结构、Page 输出、错误码。

---

## 服务概览

Python 服务 (FastAPI) 通过 HTTP/SSE 为前端提供 AI 能力。

```
Frontend (Next.js)
    │  HTTP POST / SSE
    ▼
Python Service (:8000)
├── POST /api/workflow/generate     生成 Blueprint
├── POST /api/page/generate         执行 Blueprint，SSE 流式构建页面
├── POST /api/page/chat             页面追问对话
├── POST /api/intent/classify       用户意图分类
└── GET  /api/health                健康检查
```

**Base URL:** `http://localhost:8000` (开发环境)

**通用约定:**
- 所有请求 `Content-Type: application/json`
- 所有 JSON 响应字段使用 **camelCase** (如 `chatResponse`, `dataContract`, `computeGraph`)
- 非 SSE 端点返回标准 JSON；SSE 端点返回 `text/event-stream`

---

## API 端点

### 1. 生成 Blueprint — `POST /api/workflow/generate`

根据用户自然语言描述，生成结构化的分析计划 (Blueprint)。

**Request:**

```json
{
  "user_prompt": "Analyze Form 1A English performance"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_prompt` | string | 是 | 用户的自然语言需求描述 |

**Response (200):**

```json
{
  "success": true,
  "chatResponse": "I've created an English performance analysis blueprint for Form 1A.",
  "blueprint": {
    "id": "bp-1706900000",
    "name": "Class Performance Analysis",
    "description": "Comprehensive analysis of class performance",
    "icon": "chart",
    "category": "analytics",
    "version": 1,
    "capabilityLevel": 1,
    "sourcePrompt": "Analyze Form 1A English performance",
    "createdAt": "2026-02-02T10:00:00Z",
    "dataContract": { "inputs": [...], "bindings": [...] },
    "computeGraph": { "nodes": [...] },
    "uiComposition": { "layout": "tabs", "tabs": [...] },
    "pageSystemPrompt": "..."
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | boolean | 是否成功 |
| `chatResponse` | string | 面向用户的对话回复 (Markdown) |
| `blueprint` | object | 完整 Blueprint 结构，见下文 [Blueprint 结构](#blueprint-结构) |

---

### 2. 构建页面 — `POST /api/page/generate` (SSE)

执行 Blueprint，流式构建页面。响应为 SSE 事件流。

**Request:**

```json
{
  "blueprint": { ... },
  "data": {
    "classId": "class-hk-f1a",
    "assignmentId": "assign-001",
    "students": [...],
    "submissions": [...]
  },
  "context": {
    "teacherId": "t-001"
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `blueprint` | object | 是 | 从 `/api/workflow/generate` 获得的完整 Blueprint |
| `data` | object | 是 | 用户选择的班级/作业对应的数据 |
| `context` | object | 否 | 运行时上下文 (teacherId 等) |

**Response:** SSE 事件流，详见 [SSE 协议](#sse-协议)。

---

### 3. 页面追问 — `POST /api/page/chat`

对已生成的页面进行追问对话。

**Request:**

```json
{
  "user_message": "Which students improved the most?",
  "page_context": {
    "meta": { "pageTitle": "..." },
    "dataSummary": "..."
  },
  "data": { ... }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_message` | string | 是 | 用户追问内容 |
| `page_context` | object | 否 | 当前页面的元信息和摘要 |
| `data` | object | 否 | 当前页面使用的原始数据 |

**Response (200):**

```json
{
  "success": true,
  "chatResponse": "Based on the data, the students who improved the most are..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | boolean | 是否成功 |
| `chatResponse` | string | Markdown 格式的回复 |

---

### 4. 意图分类 — `POST /api/intent/classify`

对用户的追问消息进行意图分类，判断应该重建 Blueprint 还是直接对话。

**Request:**

```json
{
  "user_message": "Help me add a grammar breakdown section",
  "workflow_name": "Class Performance Analysis",
  "page_summary": "Analysis of Form 1A English with KPIs and charts"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_message` | string | 是 | 用户消息 |
| `workflow_name` | string | 是 | 当前 Blueprint 名称 |
| `page_summary` | string | 是 | 当前页面摘要 |

**Response (200):**

```json
{
  "intent": "workflow_rebuild",
  "confidence": 0.92
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `intent` | string | `"workflow_rebuild"` \| `"page_refine"` \| `"data_chat"` |
| `confidence` | float | 置信度 0.0 - 1.0 |

**Intent 含义:**

| Intent | 含义 | 前端处理建议 |
|--------|------|-------------|
| `workflow_rebuild` | 用户想修改分析维度/结构 | 重新调用 `/api/workflow/generate` |
| `page_refine` | 用户想微调页面内容 | 重新调用 `/api/page/generate` |
| `data_chat` | 用户在追问数据 | 调用 `/api/page/chat` |

---

### 5. 健康检查 — `GET /api/health`

**Response (200):**

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

## SSE 协议

`POST /api/page/generate` 返回 SSE 事件流。每个事件格式为:

```
data: {"type":"<EVENT_TYPE>", ...payload}
```

### 事件类型

| type | 含义 | 前端需要处理 |
|------|------|-------------|
| `PHASE` | 执行阶段通知 | 可选 (显示进度提示) |
| `TOOL_CALL` | 工具调用开始 | 可选 (显示"正在计算...") |
| `TOOL_RESULT` | 工具调用结果 | 可选 |
| `MESSAGE` | 流式文本片段 | **是** — 累积拼接为完整文本 |
| `COMPLETE` | 流结束，包含完整结果 | **是** — 解析 `result` 获取页面 |
| `ERROR` | 错误 | **是** — 显示错误信息 |

### 事件详情

**PHASE**

```json
{ "type": "PHASE", "phase": "data", "message": "Fetching data..." }
```

`phase` 取值: `"data"` → `"compute"` → `"compose"`

**TOOL_CALL / TOOL_RESULT**

```json
{ "type": "TOOL_CALL", "tool": "calculate_stats", "args": { "metrics": ["mean", "median"] } }
{ "type": "TOOL_RESULT", "tool": "calculate_stats", "status": "success" }
```

**MESSAGE** (流式文本)

```json
{ "type": "MESSAGE", "content": "Based on my " }
{ "type": "MESSAGE", "content": "analysis of " }
{ "type": "MESSAGE", "content": "Form 1A..." }
```

前端将 `content` 依次拼接，实现打字机效果。

**COMPLETE** (最终结果)

```json
{
  "type": "COMPLETE",
  "message": "completed",
  "progress": 100,
  "result": {
    "response": "...",
    "chatResponse": "Here is the analysis for Form 1A English...",
    "page": {
      "meta": {
        "pageTitle": "Form 1A English Performance Analysis",
        "frameworkUsed": "Descriptive Statistics + Bloom's Taxonomy",
        "summary": "Overall class average is 72.5%...",
        "generatedAt": "2026-02-02T10:05:00Z",
        "dataSource": "Form 1A - English - Unit 5 Test"
      },
      "layout": "tabs",
      "tabs": [
        {
          "id": "overview",
          "label": "Overview",
          "blocks": [ ... ]
        }
      ]
    }
  }
}
```

**ERROR**

```json
{ "type": "ERROR", "message": "Blueprint execution failed: invalid data binding", "code": "EXECUTION_ERROR" }
```

---

## Page 输出结构

`COMPLETE.result.page` 的完整结构:

```
page
├── meta
│   ├── pageTitle: string        页面标题
│   ├── frameworkUsed: string    分析框架
│   ├── summary: string          一句话摘要
│   ├── generatedAt: string      生成时间 (ISO 8601)
│   └── dataSource: string       数据来源描述
├── layout: "tabs" | "single_page"
└── tabs[]
    ├── id: string
    ├── label: string
    └── blocks[]                 见下文 6 种 Block 类型
```

### 6 种 Block 类型

#### 1. `kpi_grid` — 关键指标卡片

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

#### 2. `chart` — 图表

```json
{
  "type": "chart",
  "variant": "bar",
  "title": "Score Distribution",
  "xAxis": ["0-20", "21-40", "41-60", "61-80", "81-100"],
  "series": [
    {
      "name": "Students",
      "data": [1, 3, 8, 15, 8],
      "color": "#4F46E5"
    }
  ]
}
```

`variant`: `"bar"` | `"line"` | `"radar"` | `"pie"` | `"gauge"` | `"distribution"`

#### 3. `markdown` — 富文本

```json
{
  "type": "markdown",
  "content": "### Key Findings\n\n1. **Strong performance** in reading comprehension...",
  "variant": "insight"
}
```

`variant`: `"default"` | `"insight"` | `"warning"` | `"success"`

#### 4. `table` — 数据表格

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

#### 5. `suggestion_list` — 建议列表

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

`priority`: `"high"` | `"medium"` | `"low"`

#### 6. `question_generator` — 练习题生成

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

`type`: `"multiple_choice"` | `"fill_in_blank"` | `"short_answer"` | `"true_false"`
`difficulty`: `"easy"` | `"medium"` | `"hard"`

---

## Blueprint 结构

前端从 `/api/workflow/generate` 获得 Blueprint，整体回传给 `/api/page/generate`。

**前端只需关心 `blueprint.dataContract.inputs`** — 用于渲染数据选择 UI (选班级、选作业)。其余字段 (`computeGraph`, `uiComposition`) 由 Python 服务内部使用，前端原样回传即可。

### `dataContract.inputs` 结构

```json
{
  "dataContract": {
    "inputs": [
      {
        "id": "class",
        "type": "class",
        "label": "Select Class",
        "required": true,
        "dependsOn": null
      },
      {
        "id": "assignment",
        "type": "assignment",
        "label": "Select Assignment",
        "required": true,
        "dependsOn": "class"
      }
    ]
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 输入项标识 |
| `type` | string | `"class"` \| `"assignment"` \| `"student"` \| `"date_range"` |
| `label` | string | 显示标签 |
| `required` | boolean | 是否必填 |
| `dependsOn` | string \| null | 依赖的其他输入项 id |

> 完整 Blueprint 模型定义见 [Blueprint 数据模型](../architecture/blueprint-model.md)。

---

## 错误响应

### HTTP 状态码

| Status | 含义 | Response Body |
|--------|------|---------------|
| 200 | 成功 | 正常响应体 |
| 400 | 请求参数错误 | `{ "success": false, "error": "user_prompt is required" }` |
| 422 | 数据验证错误 | `{ "detail": [{ "loc": [...], "msg": "...", "type": "..." }] }` |
| 500 | 服务内部错误 | `{ "success": false, "error": "Internal server error" }` |
| 503 | 服务不可用 | `{ "detail": "Service temporarily unavailable" }` |

### SSE 流中的错误

当执行过程中发生错误时，服务会发送 `ERROR` 事件后关闭流:

```
data: {"type":"ERROR","message":"Failed to execute compute node: score_stats","code":"EXECUTION_ERROR"}
```

---

## 验证命令

```bash
# 健康检查
curl http://localhost:8000/api/health

# Blueprint 生成
curl -X POST http://localhost:8000/api/workflow/generate \
  -H "Content-Type: application/json" \
  -d '{"user_prompt":"Analyze Form 1A English performance"}'

# 页面构建 (SSE 流)
curl -N -X POST http://localhost:8000/api/page/generate \
  -H "Content-Type: application/json" \
  -d '{"blueprint":{...},"data":{},"context":{"teacherId":"t-001"}}'

# 页面追问
curl -X POST http://localhost:8000/api/page/chat \
  -H "Content-Type: application/json" \
  -d '{"user_message":"Which students need extra help?","page_context":{},"data":{}}'

# 意图分类
curl -X POST http://localhost:8000/api/intent/classify \
  -H "Content-Type: application/json" \
  -d '{"user_message":"Add a grammar analysis section","workflow_name":"Class Performance Analysis","page_summary":"..."}'
```
