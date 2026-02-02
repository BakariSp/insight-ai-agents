# 目标 API（Phase 3+）

> FastAPI 服务的 4 个端点。详细 SSE 协议和 Block 格式见 [sse-protocol.md](./sse-protocol.md)。

---

## 端点概览

| Method | Path | 功能 | Agent | 状态 |
|--------|------|------|-------|------|
| `POST` | `/api/workflow/generate` | 生成 Blueprint | PlannerAgent | ✅ |
| `POST` | `/api/page/generate` | 执行 Blueprint (SSE) | ExecutorAgent | ✅ |
| `POST` | `/api/page/followup` | 统一追问 (内部路由) | Router→Chat/Planner | 🔲 Phase 4 |
| `GET` | `/api/health` | 健康检查 | - | ✅ |

> **设计变更 (2026-02-02)**: 原计划的 `POST /api/intent/classify` 和 `POST /api/page/chat` 合并为统一的 `POST /api/page/followup` 端点。RouterAgent 作为内部组件，不再对外暴露。

---

## 1. Workflow Generate (PlannerAgent → Blueprint)

生成 Blueprint（可执行蓝图）。Blocking 模式，不需要 streaming。

```
Frontend                    Next.js Proxy                 Python Service
────────                    ─────────────                 ──────────────

POST /api/ai/               POST /api/workflow/
workflow-generate            generate

{                  ──►      {                    ──►     PlannerAgent
  userPrompt:                 userPrompt:                 (output_type=Blueprint)
  "Analyze..."                "Analyze...",
}                             language: "en"
                              }

                  ◄──       {                    ◄──     Blueprint JSON
{                             blueprint: {
  blueprint: {                  id: "bp-...",
    id: "bp-...",               name: "...",
    name: "...",                dataContract: {...},
    dataContract: {...},        computeGraph: {...},
    computeGraph: {...},        uiComposition: {...},
    uiComposition: {...},       pageSystemPrompt: "..."
    pageSystemPrompt: "..."   },
  },                          model: ""
  model: ""                  }
}
```

**Python Request:**

```python
class WorkflowGenerateRequest(CamelModel):
    user_prompt: str          # 用户原始输入
    language: str = "en"      # 输出语言
    teacher_id: str = ""      # 教师 ID
    context: dict | None = None  # 附加上下文
```

**Python Response:**

```python
class WorkflowGenerateResponse(CamelModel):
    blueprint: Blueprint
    model: str = ""
```

---

## 2. Page Generate (ExecutorAgent — SSE Streaming)

最关键的端点。Python 服务**执行 Blueprint**（三阶段），输出 SSE stream，构建结构化页面。

```
Frontend                  Next.js Proxy              Python Service
────────                  ─────────────              ──────────────

POST /api/ai/             POST /api/page/
page-generate             generate

{                  ──►    {                   ──►    ExecutorAgent
  blueprint: {...},         blueprint: {...},          (execute Blueprint)
  context: {                context: {
    teacherId: "t-001"       teacherId: "t-001"
  }                         }
}                           }

                  ◄──     SSE stream            ◄──  SSE stream
```

**Python Request:**

```python
class PageGenerateRequest(CamelModel):
    blueprint: Blueprint                     # 完整 Blueprint JSON
    context: dict | None = None              # 运行时上下文（teacherId 等）
    teacher_id: str = ""                     # 教师 ID
```

SSE 事件格式详见 [sse-protocol.md](./sse-protocol.md)。

---

## 3. Page Followup (统一追问 — 内部路由)

**Phase 4 新增**。单一入口处理所有追问场景，后端内部通过 RouterAgent 分类意图，然后调度到 PageChatAgent 或 PlannerAgent。

```
Frontend                  Next.js Proxy              Python Service
────────                  ─────────────              ──────────────

POST /api/ai/             POST /api/page/
page-followup             followup

{                  ──►    {                   ──►    RouterAgent (内部)
  message:                  message:                   │
  "加一个语法...",            "加一个语法...",            ├─ "chat"    → PageChatAgent
  blueprint: {...},         blueprint: {...},          ├─ "refine"  → PlannerAgent(微调)
  pageContext: {...}        pageContext: {...}          └─ "rebuild" → PlannerAgent(重建)
}                           }

{                  ◄──    {                   ◄──    Response
  action: "rebuild",        action: "rebuild",
  chatResponse: "...",      chatResponse: "...",
  blueprint: {...}          blueprint: {...}
}                           }
```

**Python Request:**

```python
class PageFollowupRequest(CamelModel):
    message: str                             # 用户追问内容
    blueprint: Blueprint                     # 当前 Blueprint
    page_context: dict | None = None         # 当前页面摘要
    conversation_id: str | None = None       # 会话 ID
```

**Python Response:**

```python
class PageFollowupResponse(CamelModel):
    action: str                              # "chat" | "refine" | "rebuild"
    chat_response: str                       # 面向用户的回复 (Markdown)
    blueprint: Blueprint | None = None       # 修改后的 Blueprint (refine/rebuild 时)
    conversation_id: str | None = None       # 会话 ID
```

**action 路由表 — 前端处理:**

| action | 后端行为 | 响应内容 | 前端处理 |
|--------|---------|---------|---------|
| `chat` | PageChatAgent 回答 | `chatResponse` 文本 | 显示回复文本 |
| `refine` | PlannerAgent 微调 Blueprint | `chatResponse` + 新 `blueprint` | 自动用新 blueprint 调 `/api/page/generate` |
| `rebuild` | PlannerAgent 重新生成 Blueprint | `chatResponse` + 新 `blueprint` | 展示说明，用户确认后调 `/api/page/generate` |

---

## 4. Health Check

```bash
curl http://localhost:8000/api/health
# → {"status": "healthy"}
```

---

## FastAPI App 入口 (`main.py`)

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config.settings import get_settings

from api.workflow import router as workflow_router
from api.page import router as page_router
from api.health import router as health_router

settings = get_settings()

app = FastAPI(title="Insight AI Agent Service", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

app.include_router(workflow_router)
app.include_router(page_router)
app.include_router(health_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port)
```
