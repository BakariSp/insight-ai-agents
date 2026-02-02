# SSE 协议与 Block 格式

> SSE 事件协议、6 种报告 Block 类型、CamelCase 字段映射。

---

## SSE 事件协议

Python 服务必须输出以下格式的 SSE 事件，前端 `handleSSEStream()` 解析此格式：

```
# (可选) 阶段事件 - 前端当前忽略
data: {"type":"PHASE","phase":"data","message":"Fetching data..."}

# (可选) 工具调用事件 - 前端当前忽略
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
data: {"type":"COMPLETE","message":"completed","progress":100,"result":{...}}
```

### 前端解析逻辑

```typescript
// studio-agents.ts handleSSEStream() 解析规则:
// 1. 逐行读取 SSE: "data: {...}\n\n"
// 2. 解析 JSON
// 3. type === 'MESSAGE' → accumulated += content; callbacks.onMessage(content)
// 4. type === 'COMPLETE' → finalResult = { chatResponse, report }; callbacks.onComplete(finalResult)
// 5. 忽略其他 type (PHASE, TOOL_CALL, TOOL_RESULT 等)
```

### COMPLETE 事件 `result` 结构

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
            // Block 类型见下文
          ]
        }
      ]
    }
  }
}
```

### 关键约束

- `COMPLETE.result.report` 输出 **camelCase** keys（用 Pydantic `alias_generator=to_camel`）
- 前端 `handleSSEStream()` 只消费 `MESSAGE` 和 `COMPLETE`，忽略其他类型
- `PHASE` 事件是可选的，前端忽略未知类型，向后兼容

### SSE 流错误处理

Python 服务在 SSE 流中遇到错误时，发送错误 COMPLETE 事件:

```
data: {"type":"COMPLETE","message":"error","progress":100,"result":{"response":"","chatResponse":"Report generation failed. Please try again.","report":null}}
```

前端 `handleSSEStream()` 已处理 `report: null` 的情况。

---

## 6 种报告 Block 类型

Python 服务输出的 `report` JSON 必须严格匹配以下格式，否则 ReportRenderer 无法渲染。

> **组件注册表约束：** AI 只能从注册表中选择这些组件类型，不能发明新类型。详见 [Blueprint 数据模型](../architecture/blueprint-model.md)。

### 1. KPI Grid

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

### 2. Chart

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

### 3. Markdown

```json
{
  "type": "markdown",
  "content": "### Key Findings\n\n1. **Strong performance** in multiple choice\n2. Application questions need improvement",
  "variant": "insight"
}
```

`variant`: `"default"` | `"insight"` | `"warning"` | `"success"`

### 4. Table

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

### 5. Suggestion List

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

`items` 必须是对象数组，不能是字符串数组。`priority`: `"high"` | `"medium"` | `"low"`

### 6. Question Generator

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

## CamelCase 字段映射

### 原则

- **Python 内部**: `snake_case`
- **API 输出**: `camelCase` (Pydantic `alias_generator=to_camel`)
- **Next.js proxy**: 直接透传，不做转换

### 基础模型

```python
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

class CamelModel(BaseModel):
    """所有 API 响应模型的基类，输出 camelCase"""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
```

### 字段映射表

**原有字段：**

| Python (内部) | JSON Output (camelCase) |
|---------------|------------------------|
| `chat_response` | `chatResponse` |
| `report_system_prompt` | `reportSystemPrompt` |
| `depends_on` | `dependsOn` |
| `source_prompt` | `sourcePrompt` |
| `created_at` | `createdAt` |
| `report_title` | `reportTitle` |
| `framework_used` | `frameworkUsed` |
| `generated_at` | `generatedAt` |
| `data_source` | `dataSource` |
| `x_axis` | `xAxis` |
| `highlight_rules` | `highlightRules` |
| `knowledge_point` | `knowledgePoint` |
| `error_patterns` | `errorPatterns` |

**Blueprint 新增字段：**

| Python (内部) | JSON Output (camelCase) |
|---------------|------------------------|
| `data_contract` | `dataContract` |
| `compute_graph` | `computeGraph` |
| `ui_composition` | `uiComposition` |
| `capability_level` | `capabilityLevel` |
| `source_type` | `sourceType` |
| `tool_name` | `toolName` |
| `param_mapping` | `paramMapping` |
| `output_key` | `outputKey` |
| `prompt_template` | `promptTemplate` |
| `component_type` | `componentType` |
| `data_binding` | `dataBinding` |
| `ai_content_slot` | `aiContentSlot` |
| `tool_args` | `toolArgs` |
