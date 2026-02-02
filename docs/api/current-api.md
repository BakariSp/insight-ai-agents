# 当前 API（Phase 3）

> FastAPI 服务的 6 个 HTTP 端点。启动方式: `python main.py` 或 `uvicorn main:app --reload`

---

## 端点概览

| Method | Path | 功能 | 状态 |
|--------|------|------|------|
| `GET` | `/api/health` | 健康检查 | ✅ |
| `POST` | `/api/workflow/generate` | 生成 Blueprint（PlannerAgent） | ✅ Phase 2 |
| `POST` | `/api/page/generate` | 执行 Blueprint → SSE 页面流（ExecutorAgent） | ✅ Phase 3 新增 |
| `POST` | `/chat` | 通用对话 (兼容路由, 支持工具调用) | ✅ |
| `GET` | `/models` | 列出支持的模型 | ✅ |
| `GET` | `/skills` | 列出可用技能 | ✅ |

> 自动生成的 API 文档: `http://localhost:5000/docs` (Swagger) / `http://localhost:5000/redoc`

---

## POST /chat

核心端点（兼容路由），支持多模型切换和工具调用。将在 Phase 4 被 `/api/page/generate` + `/api/page/chat` 替代。

**请求:**

```json
{
  "message": "string (必填)",
  "conversation_id": "string (可选, 续接会话)",
  "model": "string (可选, 如 'openai/gpt-4o')"
}
```

**响应:**

```json
{
  "conversation_id": "uuid",
  "response": "AI 回复文本",
  "model": "使用的模型",
  "usage": { "input_tokens": 0, "output_tokens": 0 }
}
```

**示例:**

```bash
# 基本对话
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好，介绍一下你自己"}'

# 使用其他模型
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello", "model": "openai/gpt-4o"}'

# 续接会话
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "继续", "conversation_id": "abc-123"}'
```

**错误处理:** 缺少 `message` 字段返回 `422` (FastAPI Pydantic 校验)。

---

## POST /api/workflow/generate

PlannerAgent 端点，将用户自然语言请求转换为结构化 Blueprint JSON。

**请求 (camelCase):**

```json
{
  "userPrompt": "分析 Form 1A 的 Unit 5 考试成绩",
  "language": "zh-CN",
  "teacherId": "",
  "context": null
}
```

**响应 (camelCase):**

```json
{
  "blueprint": {
    "id": "bp-unit5-analysis",
    "name": "Unit 5 考试分析",
    "description": "...",
    "capabilityLevel": 1,
    "dataContract": { "inputs": [...], "bindings": [...] },
    "computeGraph": { "nodes": [...] },
    "uiComposition": { "layout": "tabs", "tabs": [...] },
    "pageSystemPrompt": "..."
  },
  "model": ""
}
```

**示例:**

```bash
curl -X POST http://localhost:5000/api/workflow/generate \
  -H "Content-Type: application/json" \
  -d '{"userPrompt": "分析班级英语成绩", "language": "zh-CN"}'
```

**错误处理:**
- 缺少 `userPrompt` → `422`
- LLM 超时/输出格式错误 → `502` + `{"detail": "Blueprint generation failed: ..."}`

---

## POST /api/page/generate

ExecutorAgent 端点，执行 Blueprint 三阶段流水线（Data → Compute → Compose），通过 SSE 流式输出页面构建事件。

**请求 (camelCase):**

```json
{
  "blueprint": {
    "id": "bp-unit5-analysis",
    "name": "Unit 5 考试分析",
    "dataContract": { "inputs": [...], "bindings": [...] },
    "computeGraph": { "nodes": [...] },
    "uiComposition": { "layout": "tabs", "tabs": [...] },
    "pageSystemPrompt": "分析考试成绩..."
  },
  "context": { "teacherId": "t-001", "input": { "assignment": "a-001" } },
  "teacherId": "t-001"
}
```

**响应: SSE 事件流**

```
data: {"type":"PHASE","phase":"data","message":"Fetching data..."}
data: {"type":"TOOL_CALL","tool":"get_assignment_submissions","args":{...}}
data: {"type":"TOOL_RESULT","tool":"get_assignment_submissions","status":"success"}
data: {"type":"PHASE","phase":"compute","message":"Computing analytics..."}
data: {"type":"TOOL_CALL","tool":"calculate_stats","args":{...}}
data: {"type":"TOOL_RESULT","tool":"calculate_stats","status":"success","result":{...}}
data: {"type":"PHASE","phase":"compose","message":"Composing page..."}
data: {"type":"MESSAGE","content":"**Key Findings**: The class average is 74.2..."}
data: {"type":"COMPLETE","message":"completed","progress":100,"result":{"response":"...","chatResponse":"...","page":{...}}}
```

**SSE 事件类型:** `PHASE`, `TOOL_CALL`, `TOOL_RESULT`, `MESSAGE`, `COMPLETE`（详见 [SSE 协议](sse-protocol.md)）

**示例:**

```bash
curl -N -X POST http://localhost:5000/api/page/generate \
  -H "Content-Type: application/json" \
  -d '{"blueprint": {...}, "teacherId": "t-001"}'
```

**错误处理:**
- 缺少 `blueprint` → `422`
- 工具调用失败/LLM 超时 → SSE 流中的 error COMPLETE 事件 (`page: null`)

---

## GET /api/health

```bash
curl http://localhost:5000/api/health
# → {"status": "healthy"}
```

## GET /models

```bash
curl http://localhost:5000/models
# → {"default": "dashscope/qwen-max", "examples": ["dashscope/qwen-max", ...]}
```

## GET /skills

```bash
curl http://localhost:5000/skills
# → {"skills": [{"name": "web_search", "description": "..."}, ...]}
```
