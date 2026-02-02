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
| **版本** | `0.2.0` |

---

## 端点总览

| 端点 | 方法 | 状态 | 用途 |
|------|------|------|------|
| `/api/workflow/generate` | POST | ✅ 已实现 | 用户提示词 → Blueprint |
| `/api/page/generate` | POST | ✅ 已实现 | 执行 Blueprint → SSE 流式页面 |
| `/api/page/followup` | POST | 🔲 Phase 4 | 统一追问 (内部路由到 chat/refine/rebuild) |
| `/api/health` | GET | ✅ 已实现 | 健康检查 |
| `/models` | GET | ✅ 已实现 | 列出可用模型 |
| `/skills` | GET | ✅ 已实现 | 列出可用技能/工具 |
| `/chat` | POST | ✅ 遗留 | Phase 0 兼容路由，将被替代 |

---

## 集成流程

```
┌──────────────────────────────────────────────────────────────────┐
│                        完整交互流程                               │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 用户输入自然语言                                               │
│     ──────────────────────                                       │
│     "分析 F1A 班英语成绩"                                         │
│           │                                                      │
│           ▼                                                      │
│  2. POST /api/workflow/generate                                  │
│     ──────────────────────────                                   │
│     返回 Blueprint JSON (含 dataContract.inputs)                  │
│           │                                                      │
│           ▼                                                      │
│  3. 前端根据 inputs 渲染数据选择 UI                                │
│     ──────────────────────────────                               │
│     用户选择班级、作业等                                           │
│           │                                                      │
│           ▼                                                      │
│  4. POST /api/page/generate  (Phase 3)                           │
│     ──────────────────────────────────                           │
│     将 Blueprint + 用户选择 → SSE 事件流                          │
│           │                                                      │
│           ▼                                                      │
│  5. 前端渲染页面 (6 种 Block 组件)                                │
│           │                                                      │
│           ▼                                                      │
│  6. 用户追问 → POST /api/page/followup  (Phase 4)               │
│     后端内部路由，返回 action 字段:                                │
│     ├── action: "chat"    → 显示文本回复                          │
│     ├── action: "refine"  → 自动用新 blueprint 回到步骤 4        │
│     └── action: "rebuild" → 展示说明，确认后回到步骤 4            │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
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

### 5. 遗留聊天 — `POST /chat` ⚠️ 将被替代

Phase 0 兼容路由，将在 Phase 4 被 `/api/page/generate` + `/api/page/followup` 替代。

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

### 6. 构建页面 — `POST /api/page/generate` (SSE) 🔲 Phase 3

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

### 7. 统一追问 — `POST /api/page/followup` 🔲 Phase 4

单一入口处理所有追问场景。后端内部通过 RouterAgent 分类意图，然后调度到对应 Agent。前端无需理解内部路由逻辑，只根据响应中的 `action` 字段做渲染。

> **设计变更**: 原计划的 `POST /api/intent/classify` 和 `POST /api/page/chat` 合并为此端点。RouterAgent 作为内部组件，不对外暴露。

**Request:**

```json
{
  "message": "帮我加一个语法分析的板块",
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
| `message` | string | **是** | 用户追问内容 |
| `blueprint` | object | **是** | 当前 Blueprint，原样传入 |
| `pageContext` | object \| null | 否 | 当前页面的元信息和数据摘要 |
| `conversationId` | string \| null | 否 | 会话 ID，用于多轮对话 |

**Response (200) — 三种 action:**

```jsonc
// action: "chat" — 数据追问，直接返回文本回复
{
  "action": "chat",
  "chatResponse": "根据数据，进步最大的 5 位同学是...",
  "blueprint": null,
  "conversationId": "conv-001"
}

// action: "refine" — 页面微调，返回修改后的 Blueprint
{
  "action": "refine",
  "chatResponse": "好的，我已将图表颜色调整为蓝色系。",
  "blueprint": { "...": "修改后的 Blueprint" },
  "conversationId": "conv-001"
}

// action: "rebuild" — 结构性重建，返回全新 Blueprint
{
  "action": "rebuild",
  "chatResponse": "好的，我重新规划了分析方案，增加了语法分析维度。新方案包含...",
  "blueprint": { "...": "全新的 Blueprint" },
  "conversationId": "conv-001"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `action` | `"chat"` \| `"refine"` \| `"rebuild"` | 后端决定的操作类型 |
| `chatResponse` | string | 面向用户的回复 (Markdown) |
| `blueprint` | object \| null | 修改后的 Blueprint（仅 refine/rebuild 时有值） |
| `conversationId` | string \| null | 会话 ID |

**前端处理逻辑:**

| action | 前端行为 |
|--------|---------|
| `chat` | 显示 `chatResponse` 文本，页面不变 |
| `refine` | 自动用新 `blueprint` 调 `/api/page/generate`，重新渲染页面 |
| `rebuild` | 展示 `chatResponse` 说明变更，用户确认后调 `/api/page/generate` |

---

## SSE 协议 🔲 Phase 3

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

// ── POST /api/page/followup (Phase 4) ──

interface PageFollowupRequest {
  message: string;
  blueprint: Blueprint;
  pageContext?: Record<string, any> | null;
  conversationId?: string | null;
}

interface PageFollowupResponse {
  action: 'chat' | 'refine' | 'rebuild';
  chatResponse: string;
  blueprint: Blueprint | null;           // 仅 refine/rebuild 时有值
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
