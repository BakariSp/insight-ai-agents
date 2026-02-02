# 当前 API（Phase 1）

> FastAPI 服务的 4 个 HTTP 端点。启动方式: `python main.py` 或 `uvicorn main:app --reload`

---

## 端点概览

| Method | Path | 功能 | 状态 |
|--------|------|------|------|
| `GET` | `/api/health` | 健康检查 | ✅ |
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
