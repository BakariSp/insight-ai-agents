# 当前 API（AI 原生架构）

> FastAPI 服务端点。启动方式: `python main.py` 或 `uvicorn main:app --reload --port 5000`

---

## 端点概览

| Method | Path | 功能 | 状态 |
|--------|------|------|------|
| `POST` | `/api/conversation/stream` | 统一会话入口（SSE 流式）— NativeAgent | ✅ |
| `POST` | `/api/conversation` | 统一会话入口（JSON）— NativeAgent | ✅ |
| `GET` | `/api/health` | 健康检查 | ✅ |

> 自动生成的 API 文档: `http://localhost:5000/docs` (Swagger) / `http://localhost:5000/redoc`

> **迁移开关**: `NATIVE_AGENT_ENABLED=true`（默认新路径）/ `false`（紧急回退 legacy）

---

## POST /api/conversation/stream

统一会话端点（SSE 流式）。薄网关接收请求后调用 NativeAgent，LLM 自主选择 tool 编排，通过 stream_adapter 将事件转为 Data Stream Protocol SSE。

**请求 (camelCase):**

```json
{
  "message": "帮我出 5 道英语选择题",
  "teacherId": "t-001",
  "conversationId": "conv-xxx",
  "context": { "classId": "c-001" },
  "language": "zh-CN"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | string | 是 | 用户消息 |
| `teacherId` | string | 是 | 教师 ID |
| `conversationId` | string | 否 | 续接对话 |
| `context` | object | 否 | 上下文（classId 等） |
| `language` | string | 否 | 语言偏好 |

**响应: SSE 事件流 (Data Stream Protocol)**

```
data: {"type":"start","messageId":"msg-xxx"}
data: {"type":"tool-input-start","toolCallId":"tc-1","toolName":"generate_quiz_questions"}
data: {"type":"tool-output-available","toolCallId":"tc-1","output":{...}}
data: {"type":"text-start","id":"t-1"}
data: {"type":"text-delta","id":"t-1","delta":"已为您生成..."}
data: {"type":"text-end","id":"t-1"}
data: {"type":"finish","finishReason":"stop"}
data: [DONE]
```

**SSE 事件类型:**

| 事件 | 说明 |
|------|------|
| `start` | 消息开始 |
| `tool-input-start` | LLM 发起 tool 调用 |
| `tool-output-available` | tool 执行结果 |
| `text-start` | 文本段开始 |
| `text-delta` | 文本流式增量 |
| `text-end` | 文本段结束 |
| `artifact` | 生成的 artifact 数据 |
| `finish` | 消息结束 |
| `error` | 错误事件 |

**示例:**

```bash
# Quiz 生成
curl -N -X POST http://localhost:5000/api/conversation/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "帮我出 5 道英语选择题", "teacherId": "t-001"}'

# RAG 问答
curl -N -X POST http://localhost:5000/api/conversation/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Unit 5 教学重点是什么", "teacherId": "t-001"}'

# 续接对话
curl -N -X POST http://localhost:5000/api/conversation/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "把第 3 题改成填空题", "teacherId": "t-001", "conversationId": "conv-xxx"}'
```

---

## POST /api/conversation

统一会话端点（JSON 非流式）。行为与 stream 相同，但返回完整 JSON 响应。

**请求**: 与 `/api/conversation/stream` 相同。

**响应 (JSON):**

```json
{
  "messageId": "msg-xxx",
  "conversationId": "conv-xxx",
  "content": "已为您生成 5 道英语选择题...",
  "artifact": {
    "artifactId": "art-001",
    "artifactType": "quiz",
    "contentFormat": "json",
    "content": { "questions": [...] },
    "version": 1
  },
  "toolCalls": [
    { "toolName": "generate_quiz_questions", "status": "ok" }
  ]
}
```

---

## GET /api/health

```bash
curl http://localhost:5000/api/health
# → {"status": "healthy"}
```

---

## 错误处理

| 状态码 | 场景 | 说明 |
|--------|------|------|
| `422` | 请求校验失败 | 缺少 message 或 teacherId |
| `401` | JWT 校验失败 | 无效或过期的 token |
| `429` | 限流 | per-teacher QPS 超限 |
| `502` | Agent/LLM 失败 | NativeAgent 或 LLM provider 不可达 |

对于 SSE 流式端点，错误通过 SSE error 事件返回:

```
data: {"type":"error","message":"Tool timeout: generate_quiz_questions"}
data: {"type":"finish","finishReason":"error"}
data: [DONE]
```

---

## 前端协议兼容

SSE 事件格式（Data Stream Protocol）**不变**。前端零改动。
`stream_adapter.py` 负责将 PydanticAI 原生事件映射为前端期望的格式。
