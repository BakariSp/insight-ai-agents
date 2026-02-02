# 当前 API（Phase 0）

> Flask 服务的 4 个 HTTP 端点。

---

## 端点概览

| Method | Path | 功能 | 状态 |
|--------|------|------|------|
| `GET` | `/health` | 健康检查 | ✅ |
| `POST` | `/chat` | 通用对话 (支持工具调用) | ✅ |
| `GET` | `/models` | 列出支持的模型 | ✅ |
| `GET` | `/skills` | 列出可用技能 | ✅ |

---

## POST /chat

核心端点，支持多模型切换和工具调用。

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

---

## GET /health

```bash
curl http://localhost:5000/health
# → {"status": "healthy"}
```

## GET /models

```bash
curl http://localhost:5000/models
# → {"models": ["dashscope/qwen-max", ...]}
```

## GET /skills

```bash
curl http://localhost:5000/skills
# → {"skills": [{"name": "web_search", "description": "..."}, ...]}
```
