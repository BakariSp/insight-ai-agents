# 前端集成规范

> Python 服务 API 契约：端点、请求/响应格式、SSE 协议、Blueprint 结构、Page 输出、TypeScript 类型。

---

## 快速参考

| 项目 | 值 |
|------|------|
| **Base URL** | `http://localhost:8000` (开发环境) |
| **Content-Type** | `application/json` |
| **响应字段命名** | 所有 JSON 响应字段使用 **camelCase** |
| **请求字段命名** | 同时接受 `camelCase` 和 `snake_case`（推荐 camelCase） |
| **SSE 端点** | 返回 `text/event-stream`，其余端点返回 JSON |
| **版本** | `0.5.0` (Phase 5 完成, Phase 6 进行中) |

---

## 端点总览

| 端点 | 方法 | 状态 | 用途 |
|------|------|------|------|
| `/api/conversation` | POST | ✅ Phase 4 | **统一会话入口** — 意图分类 + 路由（聊天/构建/反问/追问） |
| `/api/workflow/generate` | POST | ✅ 已实现 | 直调：用户提示词 → Blueprint（跳过意图分类） |
| `/api/page/generate` | POST | ✅ 已实现 | 执行 Blueprint → SSE 流式页面 |
| `/api/health` | GET | ✅ 已实现 | 健康检查 |
| `/models` | GET | ✅ 已实现 | 列出可用模型 |
| `/skills` | GET | ✅ 已实现 | 列出可用技能/工具 |
| `/chat` | POST | ⚠️ 遗留 | Phase 0 兼容路由，Phase 4 后废弃 |

---

## 集成流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        完整交互流程 (Phase 4+)                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. 用户输入自然语言                                                     │
│     ──────────────────────                                              │
│     任意消息: 闲聊、提问、或分析请求                                      │
│           │                                                             │
│           ▼                                                             │
│  2. POST /api/conversation                                              │
│     ──────────────────────────                                          │
│     RouterAgent 意图分类 → 返回 action 字段:                             │
│     │                                                                   │
│     ├── action: "chat_smalltalk"  → 显示闲聊回复 (结束)                  │
│     ├── action: "chat_qa"         → 显示问答回复 (结束)                  │
│     ├── action: "clarify"         → 渲染交互式选项 UI (→ 步骤 2a)       │
│     └── action: "build_workflow"  → 获得 Blueprint (→ 步骤 3)           │
│                                                                         │
│  2a. 用户选择 clarify 选项 (单选/多选/自定义输入)                         │
│      ─────────────────────────────────────                              │
│      将选择结果重新发送到 POST /api/conversation → 回到步骤 2             │
│           │                                                             │
│           ▼                                                             │
│  3. 前端根据 Blueprint.dataContract.inputs 渲染数据选择 UI               │
│     ──────────────────────────────────────────────────                  │
│     用户选择班级、作业等                                                 │
│           │                                                             │
│           ▼                                                             │
│  4. POST /api/page/generate                                             │
│     ──────────────────────────────────                                  │
│     将 Blueprint + 用户选择 → SSE 事件流                                │
│           │                                                             │
│           ▼                                                             │
│  5. 前端渲染页面 (6 种 Block 组件)                                      │
│           │                                                             │
│           ▼                                                             │
│  6. 用户追问 → POST /api/conversation (带 blueprint + pageContext)       │
│     后端内部路由，返回 action 字段:                                      │
│     ├── action: "chat"    → 显示文本回复                                │
│     ├── action: "refine"  → 自动用新 blueprint 回到步骤 4               │
│     └── action: "rebuild" → 展示说明，确认后回到步骤 4                   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 已实现端点

### 1. 生成 Blueprint — `POST /api/workflow/generate`

根据用户自然语言描述，生成结构化的分析计划 (Blueprint)。

**Request:**

```jsonc
// 推荐使用 camelCase
{
  "userPrompt": "Analyze Form 1A English performance",  // 必填
  "language": "en",           // 可选，默认 "en"，支持 "zh-CN"
  "teacherId": "",            // 可选，教师 ID
  "context": null             // 可选，附加上下文
}
```

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `userPrompt` | string | **是** | — | 用户的自然语言需求描述 |
| `language` | string | 否 | `"en"` | 输出语言 (`"en"`, `"zh-CN"`) |
| `teacherId` | string | 否 | `""` | 教师 ID，用于个性化 |
| `context` | object \| null | 否 | `null` | 附加上下文信息 |

**Response (200):**

```json
{
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
  },
  "model": ""
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `blueprint` | object | 完整 Blueprint 结构，见 [Blueprint 结构](#blueprint-结构) |
| `model` | string | 使用的模型标识（当前为空） |

**错误响应:**

| Status | 场景 | Body |
|--------|------|------|
| 422 | 缺少 `userPrompt` | `{ "detail": [{ "loc": [...], "msg": "...", "type": "..." }] }` |
| 502 | LLM 调用失败 | `{ "detail": "Blueprint generation failed: ..." }` |

---

### 2. 健康检查 — `GET /api/health`

**Response (200):**

```json
{
  "status": "healthy"
}
```

---

### 3. 列出模型 — `GET /models`

**Response (200):**

```json
{
  "default": "dashscope/qwen-max",
  "examples": [
    "dashscope/qwen-max",
    "dashscope/qwen-plus",
    "dashscope/qwen-turbo",
    "zai/glm-4.7",
    "openai/gpt-4o",
    "anthropic/claude-sonnet-4-20250514"
  ]
}
```

---

### 4. 列出技能 — `GET /skills`

**Response (200):**

```json
{
  "skills": [
    { "name": "get_teacher_classes", "description": "..." },
    { "name": "get_class_detail", "description": "..." },
    { "name": "get_assignment_submissions", "description": "..." },
    { "name": "get_student_grades", "description": "..." },
    { "name": "calculate_stats", "description": "..." },
    { "name": "compare_performance", "description": "..." }
  ]
}
```

---

### 5. 遗留聊天 — `POST /chat` ⚠️ Deprecated

Phase 0 兼容路由，已在 Phase 4 被 `/api/conversation` 统一入口替代。

**Request:**

```json
{
  "message": "Analyze my class performance",
  "conversation_id": null,
  "model": null
}
```

---

## 计划中端点 (Phase 3-4)

> ⚠️ 以下端点尚未实现。请求/响应模型已在代码中定义但端点未注册。
> 具体字段可能在实现时调整，请以实现后的文档为准。

### 6. 构建页面 — `POST /api/page/generate` (SSE) ✅ Phase 3

执行 Blueprint，流式构建页面。响应为 SSE 事件流。

**Request (当前模型定义):**

```json
{
  "blueprint": { "..." : "从 /api/workflow/generate 获得的完整 Blueprint" },
  "context": {
    "teacherId": "t-001"
  },
  "teacherId": "t-001"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `blueprint` | object | **是** | 从 `/api/workflow/generate` 获得的完整 Blueprint，原样传入 |
| `context` | object \| null | 否 | 运行时上下文 (teacherId 等) |
| `teacherId` | string | 否 | 教师 ID |

> **注意:** `data` 字段（用户选择的班级/作业数据）的传递方式尚未最终确定。
> Phase 3 实现时可能会在 `context` 中传递，或新增专用字段。

**Response:** SSE 事件流，详见 [SSE 协议](#sse-协议)。

---

### 7. 统一会话 — `POST /api/conversation` ✅ Phase 4

**统一入口**，处理所有用户交互：初始消息（闲聊/提问/构建请求/模糊请求）和追问消息（页面问答/微调/重建）。后端内部通过 RouterAgent 分类意图 + 置信度路由，前端只需根据 `action` 字段做渲染。

> **设计变更**: 原计划的 `/api/page/followup` 和 `/api/workflow/generate` 的入口职责合并为此端点。RouterAgent 作为内部组件，不对外暴露。`/api/workflow/generate` 保留为直调端点。

**Request:**

```jsonc
// 初始消息 — 不传 blueprint
{
  "message": "分析 1A 班英语成绩",
  "language": "en",
  "teacherId": "t-001",
  "context": null,
  "blueprint": null,
  "pageContext": null,
  "conversationId": null
}

// 追问消息 — 传入当前 blueprint + pageContext
{
  "message": "哪些学生需要关注？",
  "language": "en",
  "teacherId": "t-001",
  "context": null,
  "blueprint": { "...": "当前 Blueprint，原样传入" },
  "pageContext": {
    "meta": { "pageTitle": "Form 1A English Performance Analysis" },
    "dataSummary": "Class average 72.5%, 35 students..."
  },
  "conversationId": "conv-001"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | string | **是** | 用户消息 |
| `language` | string | 否 | 输出语言，默认 `"en"` |
| `teacherId` | string | 否 | 教师 ID |
| `context` | object \| null | 否 | 运行时上下文（如 clarify 选择结果） |
| `blueprint` | object \| null | 否 | 当前 Blueprint；**有值 = 追问模式** |
| `pageContext` | object \| null | 否 | 当前页面元信息和数据摘要 |
| `conversationId` | string \| null | 否 | 会话 ID，用于多轮对话 |

**Response (200) — 7 种 action:**

```jsonc
// action: "chat_smalltalk" — 闲聊回复
{
  "action": "chat_smalltalk",
  "chatResponse": "你好！我是教育数据分析助手，可以帮你分析班级成绩、生成练习题等。试试说「分析 1A 班英语成绩」？",
  "blueprint": null,
  "clarifyOptions": null,
  "conversationId": "conv-001"
}

// action: "chat_qa" — 知识问答回复
{
  "action": "chat_qa",
  "chatResponse": "KPI (Key Performance Indicator) 是关键绩效指标...",
  "blueprint": null,
  "clarifyOptions": null,
  "conversationId": "conv-001"
}

// action: "build_workflow" — 生成 Blueprint
{
  "action": "build_workflow",
  "chatResponse": "好的，我已为你规划了 1A 班英语成绩分析方案。",
  "blueprint": { "...": "完整的 Blueprint" },
  "clarifyOptions": null,
  "conversationId": "conv-001"
}

// action: "clarify" — 交互式反问
{
  "action": "clarify",
  "chatResponse": "你想分析哪个班级的英语表现？",
  "blueprint": null,
  "clarifyOptions": {
    "type": "single_select",
    "choices": [
      { "label": "1A 班", "value": "class-1a", "description": "35 名学生" },
      { "label": "1B 班", "value": "class-1b", "description": "32 名学生" },
      { "label": "所有班级", "value": "all", "description": "对比分析" }
    ],
    "allowCustomInput": true
  },
  "conversationId": "conv-001"
}

// action: "chat" — 追问模式：页面数据追问
{
  "action": "chat",
  "chatResponse": "根据数据，需要关注的 5 位同学是...",
  "blueprint": null,
  "clarifyOptions": null,
  "conversationId": "conv-001"
}

// action: "refine" — 追问模式：页面微调
{
  "action": "refine",
  "chatResponse": "好的，我已将图表颜色调整为蓝色系。",
  "blueprint": { "...": "修改后的 Blueprint" },
  "clarifyOptions": null,
  "conversationId": "conv-001"
}

// action: "rebuild" — 追问模式：结构性重建
{
  "action": "rebuild",
  "chatResponse": "好的，我重新规划了分析方案，增加了语法分析维度。",
  "blueprint": { "...": "全新的 Blueprint" },
  "clarifyOptions": null,
  "conversationId": "conv-001"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `action` | string | 后端决定的操作类型，见下表 |
| `chatResponse` | string \| null | 面向用户的回复 (Markdown) |
| `blueprint` | object \| null | Blueprint（仅 build_workflow/refine/rebuild 时有值） |
| `clarifyOptions` | object \| null | 交互式选项（仅 clarify 时有值） |
| `conversationId` | string \| null | 会话 ID |

**前端处理逻辑:**

| action | 模式 | 前端行为 |
|--------|------|---------|
| `chat_smalltalk` | 初始 | 显示 `chatResponse` |
| `chat_qa` | 初始 | 显示 `chatResponse` |
| `build_workflow` | 初始 | 拿 `blueprint` 调 `/api/page/generate`，可选先渲染 inputs UI |
| `clarify` | 初始 | 渲染 `clarifyOptions` 为交互式 UI（单选/多选/自定义输入），用户选择后重新发送 |
| `chat` | 追问 | 显示 `chatResponse`，页面不变 |
| `refine` | 追问 | 自动用新 `blueprint` 调 `/api/page/generate`，重新渲染页面 |
| `rebuild` | 追问 | 展示 `chatResponse` 说明变更，用户确认后调 `/api/page/generate` |

---

## SSE 协议 ✅ Phase 3

`POST /api/page/generate` 返回 SSE 事件流。每个事件格式为:

```
data: {"type":"<EVENT_TYPE>", ...payload}
```

### 事件类型

| type | 含义 | 前端必须处理 |
|------|------|-------------|
| `PHASE` | 执行阶段通知 | 可选 — 显示进度提示 |
| `TOOL_CALL` | 工具调用开始 | 可选 — 显示"正在计算..." |
| `TOOL_RESULT` | 工具调用结果 | 可选 |
| `MESSAGE` | 流式文本片段 | **是** — 累积拼接为完整文本 |
| `COMPLETE` | 流结束，包含完整结果 | **是** — 解析 `result` 获取页面 |
| `ERROR` | 错误 | **是** — 显示错误信息 |

### 事件示例

**PHASE — 阶段通知**

```json
{ "type": "PHASE", "phase": "data", "message": "Fetching data..." }
```

`phase` 值按顺序: `"data"` → `"compute"` → `"compose"`

**TOOL_CALL / TOOL_RESULT — 工具调用**

```json
{ "type": "TOOL_CALL", "tool": "calculate_stats", "args": { "metrics": ["mean", "median"] } }
{ "type": "TOOL_RESULT", "tool": "calculate_stats", "status": "success" }
```

**MESSAGE — 流式文本 (打字机效果)**

```json
{ "type": "MESSAGE", "content": "Based on my " }
{ "type": "MESSAGE", "content": "analysis of " }
{ "type": "MESSAGE", "content": "Form 1A..." }
```

前端将 `content` 依次拼接，实现打字机效果。

**COMPLETE — 最终结果**

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
          "blocks": [ "..." ]
        }
      ]
    }
  }
}
```

**ERROR — 错误**

```json
{ "type": "ERROR", "message": "Blueprint execution failed: invalid data binding", "code": "EXECUTION_ERROR" }
```

### SSE 前端消费参考

```typescript
const response = await fetch('/api/page/generate', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ blueprint, context }),
});

const reader = response.body!.getReader();
const decoder = new TextDecoder();
let buffer = '';

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  buffer += decoder.decode(value, { stream: true });
  const lines = buffer.split('\n');
  buffer = lines.pop() || '';

  for (const line of lines) {
    if (!line.startsWith('data: ')) continue;
    const event = JSON.parse(line.slice(6));

    switch (event.type) {
      case 'MESSAGE':
        // 拼接文本，实现打字机效果
        appendText(event.content);
        break;
      case 'COMPLETE':
        // 解析页面结构，渲染 blocks
        renderPage(event.result.page);
        break;
      case 'ERROR':
        showError(event.message);
        break;
      case 'PHASE':
        updateProgress(event.phase, event.message);
        break;
    }
  }
}
```

---

## Blueprint 结构

前端从 `/api/workflow/generate` 获得 Blueprint，整体回传给 `/api/page/generate`。

> **核心原则：** Blueprint 对前端来说是**不透明**的。前端只需关心 `dataContract.inputs`（渲染数据选择 UI），其余字段原样回传即可。

### 整体结构

```
Blueprint
├── id: string                    唯一标识
├── name: string                  名称
├── description: string           描述
├── icon: string                  图标 (默认 "chart")
├── category: string              分类 (默认 "analytics")
├── version: number               版本号
├── capabilityLevel: 1 | 2 | 3   能力等级
├── sourcePrompt: string          原始用户输入
├── createdAt: string             创建时间 (ISO 8601)
│
├── dataContract                  ← 前端需要关注
│   ├── inputs[]                  用户数据选择项
│   └── bindings[]                数据获取声明 (透传)
│
├── computeGraph                  ← 透传，无需关心
│   └── nodes[]
│
├── uiComposition                 ← 透传，无需关心
│   ├── layout: "tabs" | "single_page"
│   └── tabs[]
│       └── slots[]
│
└── pageSystemPrompt: string      ← 透传，无需关心
```

### `dataContract.inputs` — 前端需要渲染

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
    ],
    "bindings": [ "..." ]
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 输入项标识 |
| `type` | string | `"class"` \| `"assignment"` \| `"student"` \| `"date_range"` |
| `label` | string | 显示标签 |
| `required` | boolean | 是否必填 |
| `dependsOn` | string \| null | 依赖的其他输入项 id（级联选择） |

**级联依赖处理:** 当 `dependsOn` 不为 null 时，该输入项需要等待依赖项选择完成后才显示/请求选项。例如 `assignment` 依赖 `class`，用户先选班级，再加载对应作业列表。

> 完整 Blueprint 模型定义见 [Blueprint 数据模型](../architecture/blueprint-model.md)。

---

## Page 输出结构

`COMPLETE.result.page` 的完整结构:

```
page
├── meta
│   ├── pageTitle: string        页面标题 (必须)
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

AI 只能从以下 6 种组件中选择，不存在其他类型。

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

| 字段 | 类型 | 说明 |
|------|------|------|
| `data[].label` | string | 指标名称 |
| `data[].value` | string | 指标值 |
| `data[].status` | `"up"` \| `"down"` \| `"neutral"` | 趋势方向 |
| `data[].subtext` | string | 补充说明 |

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

| 字段 | 类型 | 说明 |
|------|------|------|
| `variant` | string | `"bar"` \| `"line"` \| `"radar"` \| `"pie"` \| `"gauge"` \| `"distribution"` |
| `title` | string | 图表标题 |
| `xAxis` | string[] | X 轴标签 |
| `series[].name` | string | 数据系列名称 |
| `series[].data` | number[] | 数据值 |
| `series[].color` | string | 颜色 (可选) |

#### 3. `table` — 数据表格

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

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | string | 表格标题 |
| `headers` | string[] | 列头 |
| `rows[].cells` | any[] | 单元格值 |
| `rows[].status` | string | 行状态高亮 (可选) |
| `highlightRules` | array | 条件高亮规则 (可选) |

#### 4. `markdown` — 富文本

```json
{
  "type": "markdown",
  "content": "### Key Findings\n\n1. **Strong performance** in reading comprehension...",
  "variant": "insight"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `content` | string | Markdown 内容 |
| `variant` | `"default"` \| `"insight"` \| `"warning"` \| `"success"` | 样式变体 |

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

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | string | 列表标题 |
| `items[].title` | string | 建议标题 |
| `items[].description` | string | 建议描述 |
| `items[].priority` | `"high"` \| `"medium"` \| `"low"` | 优先级 |
| `items[].category` | string | 分类 |

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

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | string | 练习题标题 |
| `knowledgePoint` | string | 知识点 |
| `questions[].type` | `"multiple_choice"` \| `"fill_in_blank"` \| `"short_answer"` \| `"true_false"` | 题型 |
| `questions[].difficulty` | `"easy"` \| `"medium"` \| `"hard"` | 难度 |
| `questions[].options` | string[] | 选项 (仅 multiple_choice) |
| `questions[].answer` | string | 答案 |
| `questions[].explanation` | string | 解析 |

---

## TypeScript 类型定义

以下类型定义可直接用于前端项目。

### 核心类型

```typescript
// ── Blueprint (从 /api/workflow/generate 获得) ──

interface Blueprint {
  id: string;
  name: string;
  description: string;
  icon: string;
  category: string;
  version: number;
  capabilityLevel: 1 | 2 | 3;
  sourcePrompt: string;
  createdAt: string;
  dataContract: DataContract;
  computeGraph: ComputeGraph;
  uiComposition: UIComposition;
  pageSystemPrompt: string;
}

interface DataContract {
  inputs: DataInputSpec[];
  bindings: DataBinding[];
}

interface DataInputSpec {
  id: string;
  type: 'class' | 'assignment' | 'student' | 'date_range';
  label: string;
  required: boolean;
  dependsOn: string | null;
}

interface DataBinding {
  id: string;
  sourceType: 'tool' | 'api' | 'static';
  toolName: string | null;
  apiPath: string | null;
  paramMapping: Record<string, string>;
  description: string;
  required: boolean;
  dependsOn: string[];
}

interface ComputeGraph {
  nodes: ComputeNode[];
}

interface ComputeNode {
  id: string;
  type: 'tool' | 'ai';
  toolName: string | null;
  toolArgs: Record<string, any> | null;
  promptTemplate: string | null;
  dependsOn: string[];
  outputKey: string;
}

interface UIComposition {
  layout: 'tabs' | 'single_page';
  tabs: TabSpec[];
}

interface TabSpec {
  id: string;
  label: string;
  slots: ComponentSlot[];
}

interface ComponentSlot {
  id: string;
  componentType: ComponentType;
  dataBinding: string | null;
  props: Record<string, any>;
  aiContentSlot: boolean;
}

type ComponentType =
  | 'kpi_grid'
  | 'chart'
  | 'table'
  | 'markdown'
  | 'suggestion_list'
  | 'question_generator';
```

### API 请求/响应类型

```typescript
// ── POST /api/workflow/generate ──

interface WorkflowGenerateRequest {
  userPrompt: string;
  language?: string;       // 默认 "en"
  teacherId?: string;
  context?: Record<string, any> | null;
}

interface WorkflowGenerateResponse {
  blueprint: Blueprint;
  model: string;
}

// ── POST /api/page/generate (Phase 3) ──

interface PageGenerateRequest {
  blueprint: Blueprint;
  context?: Record<string, any> | null;
  teacherId?: string;
}

// ── POST /api/conversation (Phase 4) ──

interface ConversationRequest {
  message: string;
  language?: string;                     // 默认 "en"
  teacherId?: string;
  context?: Record<string, any> | null;
  blueprint?: Blueprint | null;          // 有值 = 追问模式
  pageContext?: Record<string, any> | null;
  conversationId?: string | null;
}

type ConversationAction =
  | 'chat_smalltalk'   // 初始：闲聊
  | 'chat_qa'          // 初始：知识问答
  | 'build_workflow'   // 初始：生成 Blueprint
  | 'clarify'          // 初始：交互式反问
  | 'chat'             // 追问：页面数据追问
  | 'refine'           // 追问：微调 Blueprint
  | 'rebuild';         // 追问：重建 Blueprint

interface ClarifyChoice {
  label: string;
  value: string;
  description?: string;
}

interface ClarifyOptions {
  type: 'single_select' | 'multi_select';
  choices: ClarifyChoice[];
  allowCustomInput: boolean;             // true → 前端渲染 "其他" 自由输入框
}

interface ConversationResponse {
  action: ConversationAction;
  chatResponse: string | null;
  blueprint: Blueprint | null;           // 仅 build_workflow/refine/rebuild 时有值
  clarifyOptions: ClarifyOptions | null; // 仅 clarify 时有值
  conversationId: string | null;
}
```

### SSE 事件类型

```typescript
type SSEEvent =
  | { type: 'PHASE'; phase: 'data' | 'compute' | 'compose'; message: string }
  | { type: 'TOOL_CALL'; tool: string; args: Record<string, any> }
  | { type: 'TOOL_RESULT'; tool: string; status: 'success' | 'error' }
  | { type: 'MESSAGE'; content: string }
  | { type: 'COMPLETE'; message: string; progress: 100; result: PageResult }
  | { type: 'ERROR'; message: string; code: string };

interface PageResult {
  response: string;
  chatResponse: string;
  page: Page;
}

interface Page {
  meta: PageMeta;
  layout: 'tabs' | 'single_page';
  tabs: PageTab[];
}

interface PageMeta {
  pageTitle: string;
  frameworkUsed?: string;
  summary?: string;
  generatedAt?: string;
  dataSource?: string;
}

interface PageTab {
  id: string;
  label: string;
  blocks: Block[];
}

// ── 6 种 Block 类型 ──

type Block =
  | KpiGridBlock
  | ChartBlock
  | TableBlock
  | MarkdownBlock
  | SuggestionListBlock
  | QuestionGeneratorBlock;

interface KpiGridBlock {
  type: 'kpi_grid';
  data: Array<{
    label: string;
    value: string;
    status: 'up' | 'down' | 'neutral';
    subtext: string;
  }>;
}

interface ChartBlock {
  type: 'chart';
  variant: 'bar' | 'line' | 'radar' | 'pie' | 'gauge' | 'distribution';
  title: string;
  xAxis: string[];
  series: Array<{
    name: string;
    data: number[];
    color?: string;
  }>;
}

interface TableBlock {
  type: 'table';
  title: string;
  headers: string[];
  rows: Array<{
    cells: any[];
    status?: string;
  }>;
  highlightRules?: Array<{
    column: number;
    condition: string;
    value: number;
    style: string;
  }>;
}

interface MarkdownBlock {
  type: 'markdown';
  content: string;
  variant: 'default' | 'insight' | 'warning' | 'success';
}

interface SuggestionListBlock {
  type: 'suggestion_list';
  title: string;
  items: Array<{
    title: string;
    description: string;
    priority: 'high' | 'medium' | 'low';
    category: string;
  }>;
}

interface QuestionGeneratorBlock {
  type: 'question_generator';
  title: string;
  description: string;
  knowledgePoint: string;
  questions: Array<{
    id: string;
    order: number;
    type: 'multiple_choice' | 'fill_in_blank' | 'short_answer' | 'true_false';
    question: string;
    options?: string[];
    answer: string;
    explanation: string;
    difficulty: 'easy' | 'medium' | 'hard';
  }>;
  context?: {
    errorPatterns: string[];
    difficulty: string;
  };
}
```

---

## 错误处理

### HTTP 错误码

| Status | 场景 | Response Body |
|--------|------|---------------|
| 200 | 成功 | 正常响应体 |
| 400 | 请求参数错误 | `{ "detail": "..." }` |
| 422 | Pydantic 验证失败 | `{ "detail": [{ "loc": [...], "msg": "...", "type": "..." }] }` |
| 502 | LLM 调用失败 | `{ "detail": "Blueprint generation failed: ..." }` |
| 500 | 服务内部错误 | `{ "detail": "Internal server error" }` |

### SSE 流中的错误

当执行过程中发生错误时，服务发送 `ERROR` 事件后关闭流:

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
  -d '{"userPrompt":"Analyze Form 1A English performance","language":"zh-CN"}'

# 列出模型
curl http://localhost:8000/models

# 列出技能
curl http://localhost:8000/skills
```

---

## 待前端确认事项

以下事项需要前端团队确认后才能最终确定实现方案:

| # | 事项 | 影响 |
|---|------|------|
| 1 | **图表库选型** — ECharts 还是 Recharts？ | 影响 chart block 数据格式是否需要调整 |
| 2 | **SSE 消费方案** — 是否需要非流式 fallback 接口？ | 影响 Phase 3 是否需要额外端点 |
| 3 | **SSE 断连策略** — 中断后从头重试还是需要续传？ | 影响服务端是否需要缓存执行状态 |
| 4 | **数据传递方式** — 用户选择的数据如何传给 `/api/page/generate`？ | 当前模型定义中无 `data` 字段，需确认 |
| 5 | **页面缓存** — 已生成页面是否缓存？缓存在前端还是后端？ | 影响是否需要新增缓存端点 |
| 6 | **错误降级** — SSE 中途出错时保留已渲染部分还是整体报错？ | 影响前端 ERROR 事件处理逻辑 |
| 7 | **6 种组件 schema** — 字段是否满足渲染需求？是否缺失？ | 影响 component_registry 定义 |

---

## 完整对接示例 (E2E Verified)

> 以下示例来自 2026-02-03 的完整 E2E 测试验证，可作为前端开发的参考数据。

### 用户需求

```
分析某个班级某次作业的成绩：显示平均分、最高分、最低分、成绩分布图表，给出分析总结和教学建议
```

### Step 1: 生成 Blueprint

**POST /api/workflow/generate**

```json
{
  "userPrompt": "分析某个班级某次作业的成绩：显示平均分、最高分、最低分、成绩分布图表，给出分析总结和教学建议",
  "language": "zh-CN"
}
```

**Response (完整 Blueprint):**

```json
{
  "blueprint": {
    "id": "bp-assignment-analysis",
    "name": "Assignment Score Analysis",
    "description": "Analyze the scores of a specific assignment in a class...",
    "icon": "chart",
    "category": "analytics",
    "version": 1,
    "capabilityLevel": 1,
    "sourcePrompt": "分析某个班级某次作业的成绩...",
    "createdAt": "2026-02-03T10:02:36.595096+00:00",
    "dataContract": {
      "inputs": [
        {
          "id": "class",
          "type": "class",
          "label": "Class",
          "required": true,
          "dependsOn": null
        },
        {
          "id": "assignment",
          "type": "assignment",
          "label": "Assignment",
          "required": true,
          "dependsOn": "class"
        }
      ],
      "bindings": [
        {
          "id": "submissions",
          "sourceType": "tool",
          "toolName": "get_assignment_submissions",
          "paramMapping": {
            "teacher_id": "$context.teacherId",
            "assignment_id": "$input.assignment"
          },
          "description": "Fetch all student submissions for the selected assignment."
        }
      ]
    },
    "computeGraph": {
      "nodes": [
        {
          "id": "score_stats",
          "type": "tool",
          "toolName": "calculate_stats",
          "toolArgs": { "data": "$data.submissions.scores" },
          "outputKey": "scoreStats"
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
              "id": "kpi_overview",
              "componentType": "kpi_grid",
              "dataBinding": "$compute.scoreStats",
              "aiContentSlot": false
            },
            {
              "id": "score_distribution_chart",
              "componentType": "chart",
              "dataBinding": "$compute.scoreStats.distribution",
              "props": { "variant": "bar", "title": "Score Distribution Chart" },
              "aiContentSlot": false
            },
            {
              "id": "analysis_summary",
              "componentType": "markdown",
              "props": { "variant": "insight" },
              "aiContentSlot": true
            },
            {
              "id": "teaching_suggestions",
              "componentType": "suggestion_list",
              "props": { "title": "Teaching Suggestions" },
              "aiContentSlot": true
            }
          ]
        }
      ]
    },
    "pageSystemPrompt": "You are an educational data analyst..."
  },
  "model": "dashscope/qwen-max"
}
```

### Step 2: 前端处理 Blueprint

1. **解析 `dataContract.inputs`** — 渲染数据选择 UI
   - 先显示 Class 下拉框
   - 用户选择 Class 后，显示 Assignment 下拉框 (`dependsOn: "class"`)

2. **用户选择数据后构建 context:**

```json
{
  "teacherId": "t-001",
  "classId": "class-hk-f1a",
  "assignmentId": "a-001"
}
```

### Step 3: 执行 Blueprint 生成页面

**POST /api/page/generate**

```json
{
  "blueprint": { "...完整 Blueprint..." },
  "context": {
    "teacherId": "t-001",
    "classId": "class-hk-f1a",
    "assignmentId": "a-001"
  }
}
```

**SSE 事件流:**

```
data: {"type":"PHASE","phase":"data","message":"Fetching data..."}

data: {"type":"TOOL_CALL","tool":"get_assignment_submissions","args":{"teacher_id":"t-001","assignment_id":"a-001"}}

data: {"type":"TOOL_RESULT","tool":"get_assignment_submissions","status":"success"}

data: {"type":"PHASE","phase":"compute","message":"Computing analytics..."}

data: {"type":"TOOL_CALL","tool":"calculate_stats","args":{"data":[58,85,72,91,65]}}

data: {"type":"TOOL_RESULT","tool":"calculate_stats","status":"success"}

data: {"type":"PHASE","phase":"compose","message":"Composing page..."}

data: {"type":"BLOCK_START","blockId":"analysis_summary","componentType":"markdown"}

data: {"type":"SLOT_DELTA","blockId":"analysis_summary","slotKey":"content","deltaText":"## 分析总结\n\n### 关键发现\n- **平均分**: 74.2 分..."}

data: {"type":"BLOCK_COMPLETE","blockId":"analysis_summary"}

data: {"type":"BLOCK_START","blockId":"teaching_suggestions","componentType":"suggestion_list"}

data: {"type":"SLOT_DELTA","blockId":"teaching_suggestions","slotKey":"items","deltaText":"[{\"title\":\"加强低分学生辅导\"...}]"}

data: {"type":"BLOCK_COMPLETE","blockId":"teaching_suggestions"}

data: {"type":"COMPLETE","message":"completed","progress":100,"result":{...}}
```

### Step 4: 最终 Page 结构

**COMPLETE 事件中的 `result.page`:**

```json
{
  "meta": {
    "pageTitle": "Assignment Score Analysis",
    "summary": "Analyze the scores of a specific assignment in a class...",
    "generatedAt": "2026-02-03T10:02:36.601454+00:00",
    "dataSource": "tool"
  },
  "layout": "tabs",
  "tabs": [
    {
      "id": "overview",
      "label": "Overview",
      "blocks": [
        {
          "type": "kpi_grid",
          "data": [
            { "label": "Average", "value": "74.2", "status": "neutral", "subtext": "" },
            { "label": "Median", "value": "72.0", "status": "neutral", "subtext": "" },
            { "label": "Total Students", "value": "5", "status": "neutral", "subtext": "" },
            { "label": "Highest Score", "value": "91.0", "status": "neutral", "subtext": "" },
            { "label": "Lowest Score", "value": "58.0", "status": "neutral", "subtext": "" }
          ]
        },
        {
          "type": "chart",
          "variant": "bar",
          "title": "Score Distribution Chart",
          "xAxis": ["0-39", "40-49", "50-59", "60-69", "70-79", "80-89", "90-100"],
          "series": [{ "name": "Count", "data": [0, 0, 1, 1, 1, 1, 1] }]
        },
        {
          "type": "markdown",
          "content": "## 分析总结\n\n### 关键发现\n- **平均分**: 74.2 分\n- **中位数**: 72.0 分\n- **标准差**: 13.7 分\n- **最低分**: 58.0 分\n- **最高分**: 91.0 分\n- **四分位数**:\n  - 第25百分位: 65.0 分\n  - 第50百分位 (中位数): 72.0 分\n  - 第75百分位: 85.0 分\n  - 第90百分位: 88.6 分\n\n### 主要模式和趋势\n- **整体表现**: 学生的整体平均分为74.2分，中位数为72.0分，表明大多数学生的表现处于中等水平。\n- **成绩分布**: 成绩分布较为均匀，从50-59到90-100每个分数段都有一个学生。\n\n### 需要关注的学生\n- **Wong Ka Ho**: 得分58分，低于及格线，需要特别关注和支持。\n- **Lam Wai Yin**: 得分65分，虽然及格但接近及格线，也需要额外的支持。\n\n### 教学建议\n- **个性化辅导**: 对于得分较低的学生提供一对一或小组辅导。\n- **强化基础**: 针对全班学生的基础知识进行巩固。\n- **定期反馈**: 定期向学生提供反馈，帮助他们了解自己的进步和不足。",
          "variant": "insight"
        },
        {
          "type": "suggestion_list",
          "title": "Teaching Suggestions",
          "items": [
            {
              "title": "加强低分学生辅导",
              "description": "王家豪和林慧妍的分数低于70分，需要额外的辅导和支持以提高成绩。",
              "priority": "high",
              "category": "improvement"
            },
            {
              "title": "巩固中等水平学生的知识",
              "description": "陈大文的成绩处于中等水平，可以提供一些额外的练习来帮助他进一步提高。",
              "priority": "medium",
              "category": "improvement"
            },
            {
              "title": "保持高分学生的优秀表现",
              "description": "李梅和张小明的成绩优异，继续保持他们的学习方法。",
              "priority": "low",
              "category": "strength"
            },
            {
              "title": "增加课堂互动",
              "description": "通过小组讨论和互动活动，帮助所有学生更好地理解课程内容。",
              "priority": "medium",
              "category": "action"
            },
            {
              "title": "定期进行复习测试",
              "description": "定期进行小测验，以便及时发现并解决学生在学习中的问题。",
              "priority": "high",
              "category": "action"
            }
          ]
        }
      ]
    }
  ]
}
```

### 前端渲染示意

```
┌─────────────────────────────────────────────────────────────────┐
│  Assignment Score Analysis                                       │
├─────────────────────────────────────────────────────────────────┤
│  [Overview]                                                      │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐   │
│  │ Average │ │ Median  │ │ Total   │ │ Highest │ │ Lowest  │   │
│  │  74.2   │ │  72.0   │ │   5     │ │  91.0   │ │  58.0   │   │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘   │
├─────────────────────────────────────────────────────────────────┤
│  Score Distribution Chart                                        │
│  ┌────────────────────────────────────────────────────────┐     │
│  │    █                                                   │     │
│  │    █     █     █     █     █                          │     │
│  │   0-39  50-59 60-69 70-79 80-89 90-100               │     │
│  └────────────────────────────────────────────────────────┘     │
├─────────────────────────────────────────────────────────────────┤
│  ## 分析总结                                                     │
│                                                                  │
│  ### 关键发现                                                    │
│  - **平均分**: 74.2 分                                           │
│  - **中位数**: 72.0 分                                           │
│  - **标准差**: 13.7 分                                           │
│  - ...                                                          │
├─────────────────────────────────────────────────────────────────┤
│  Teaching Suggestions                                            │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ 🔴 高优先级: 加强低分学生辅导                            │     │
│  │    王家豪和林慧妍的分数低于70分...                       │     │
│  ├────────────────────────────────────────────────────────┤     │
│  │ 🟡 中优先级: 巩固中等水平学生的知识                      │     │
│  │    陈大文的成绩处于中等水平...                          │     │
│  └────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 前端关键对接要点

### 1. Blueprint 是不透明的

前端只需关注：
- `dataContract.inputs` — 渲染数据选择 UI
- `uiComposition.tabs[].label` — 仅用于显示 Tab 名称（可选）

其余字段（bindings, computeGraph, 各种 ID）直接原样传给 `/api/page/generate`，无需解析。

### 2. Context 传递规则

用户选择的数据通过 `context` 传递：

```json
{
  "context": {
    "teacherId": "教师 ID (必须)",
    "classId": "用户选择的班级 ID",
    "assignmentId": "用户选择的作业 ID"
  }
}
```

⚠️ **重要**: `assignmentId` 等值必须直接放在 context 根级别，不要嵌套在 `input` 对象中。后端会自动映射到 `$input.assignment`。

### 3. SSE 事件处理优先级

| 事件类型 | 必须处理 | 用途 |
|----------|----------|------|
| `COMPLETE` | ✅ 是 | 获取最终页面，结束流 |
| `ERROR` | ✅ 是 | 显示错误信息 |
| `PHASE` | 可选 | 显示进度提示 |
| `BLOCK_START` | 可选 | AI 内容开始 loading 状态 |
| `SLOT_DELTA` | 可选 | 打字机效果（实时显示 AI 生成） |
| `BLOCK_COMPLETE` | 可选 | AI 内容完成 |
| `TOOL_CALL/RESULT` | 可选 | 调试 / 详细日志 |

### 4. 6 种 Block 组件映射

| type | 前端组件 | 数据来源 |
|------|----------|----------|
| `kpi_grid` | 指标卡片网格 | `data[]` 数组 |
| `chart` | 图表 (ECharts/Recharts) | `xAxis`, `series` |
| `table` | 数据表格 | `headers`, `rows` |
| `markdown` | Markdown 渲染器 | `content` 字符串 |
| `suggestion_list` | 建议列表 | `items[]` 数组 |
| `question_generator` | 练习题 | `questions[]` 数组 |

---

## 文档版本

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| 0.5.0 | 2026-02-02 | 初版：Phase 4 API 设计 |
| 0.5.1 | 2026-02-03 | 新增完整 E2E 示例，明确前端对接要点 |
