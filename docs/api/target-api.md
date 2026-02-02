# 目标 API（Phase 6）

> FastAPI 服务的端点规划。详细 SSE 协议和 Block 格式见 [sse-protocol.md](./sse-protocol.md)。

---

## 端点概览

| Method | Path | 功能 | Agent | 状态 |
|--------|------|------|-------|------|
| `POST` | `/api/workflow/generate` | 生成 Blueprint | PlannerAgent | ✅ Phase 2 |
| `POST` | `/api/page/generate` | 执行 Blueprint (SSE) | ExecutorAgent | ✅ Phase 3 |
| `POST` | `/api/conversation` | 统一会话网关 (内部路由) | Router→Chat/PageChat/Planner | ✅ Phase 4 |
| `POST` | `/api/page/patch` | 增量 Patch 执行 (SSE) | ExecutorAgent | 🔲 Phase 6 |
| `GET` | `/api/health` | 健康检查 | - | ✅ |

> **设计变更 (2026-02-02)**: 原计划的 `POST /api/intent/classify` 和 `POST /api/page/chat` 合并为统一的 `POST /api/conversation` 端点。RouterAgent 作为内部组件，不再对外暴露。Phase 4 已完成实现。

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

## 3. Conversation (统一会话网关 — 内部路由)

**Phase 4 完成**。单一入口处理所有用户交互 — 初始模式（闲聊、问答、生成、反问）和追问模式（对话、微调、重建）。后端内部通过 RouterAgent 双模式分类意图，然后调度到 ChatAgent / PageChatAgent / PlannerAgent。

```
Frontend                  Next.js Proxy              Python Service
────────                  ─────────────              ──────────────

POST /api/ai/             POST /api/
conversation              conversation

{                  ──►    {                   ──►    RouterAgent (内部)
  message:                  message:                   │ blueprint=null → 初始模式
  "分析成绩...",             "分析成绩...",              │ blueprint≠null → 追问模式
  blueprint: null,          blueprint: null,           │
  pageContext: null          pageContext: null          ├─ chat_smalltalk → ChatAgent
}                           }                          ├─ chat_qa       → ChatAgent
                                                       ├─ build_workflow → PlannerAgent
                                                       ├─ clarify       → ClarifyBuilder
                                                       ├─ chat          → PageChatAgent
                                                       ├─ refine        → PlannerAgent(微调)
{                  ◄──    {                   ◄──      └─ rebuild       → PlannerAgent(重建)
  action: "build_workflow",  action: "build_workflow",
  chatResponse: "...",       chatResponse: "...",
  blueprint: {...},          blueprint: {...},
  clarifyOptions: null       clarifyOptions: null
}                           }
```

**Python Request:**

```python
class ConversationRequest(CamelModel):
    message: str                             # 用户输入 (必填)
    language: str = "en"                     # 输出语言
    teacher_id: str = ""                     # 教师 ID
    context: dict | None = None              # 附加上下文
    blueprint: Blueprint | None = None       # null=初始模式, 有值=追问模式
    page_context: dict | None = None         # 当前页面摘要 (追问模式)
    conversation_id: str | None = None       # 会话 ID
```

**Python Response:**

```python
class ConversationResponse(CamelModel):
    action: str                              # 7 种 action 之一
    chat_response: str = ""                  # 面向用户的回复 (Markdown)
    blueprint: Blueprint | None = None       # 生成/修改后的 Blueprint
    clarify_options: ClarifyOptions | None = None  # 反问选项 (action=clarify)
    conversation_id: str | None = None       # 会话 ID
```

**action 路由表 — 前端处理:**

| action | 模式 | 后端行为 | 响应内容 | 前端处理 |
|--------|------|---------|---------|---------|
| `chat_smalltalk` | 初始 | ChatAgent 回复 | `chatResponse` | 显示回复文本 |
| `chat_qa` | 初始 | ChatAgent 回复 | `chatResponse` | 显示回复文本 |
| `build_workflow` | 初始 | PlannerAgent 生成 | `blueprint` + `chatResponse` | 用 blueprint 调 `/api/page/generate` |
| `clarify` | 初始 | 返回反问选项 | `chatResponse` + `clarifyOptions` | 渲染选项 UI，用户选择后重新请求 |
| `chat` | 追问 | PageChatAgent 回答 | `chatResponse` | 显示回复文本 |
| `refine` | 追问 | PlannerAgent 微调 | `chatResponse` + 新 `blueprint` | 自动用新 blueprint 调 `/api/page/generate` |
| `rebuild` | 追问 | PlannerAgent 重建 | `chatResponse` + 新 `blueprint` | 展示说明，用户确认后调 `/api/page/generate` |

---

## 4. Health Check

```bash
curl http://localhost:8000/api/health
# → {"status": "healthy"}
```

---

## 5. Page Patch (Phase 6 计划) — `POST /api/page/patch` 🔲

增量 Patch 执行端点，接收 PatchPlan 对已有页面进行局部修改，避免每次 refine 都全页重建。

**Request (计划):**

```json
{
  "blueprint": { "...": "当前 Blueprint" },
  "page": { "...": "当前页面结构" },
  "patchPlan": {
    "scope": "patch_layout | patch_compose | full_rebuild",
    "instructions": [
      { "type": "update_props", "targetBlockId": "tab1-slot2", "changes": { "variant": "warning" } }
    ],
    "affectedBlockIds": ["tab1-slot2"]
  },
  "context": {},
  "dataContext": {},
  "computeResults": {}
}
```

**Response:** SSE 事件流（PATCH_LAYOUT 直接返回修改后页面，PATCH_COMPOSE 逐 block 重生成 AI 内容）。

---

## FastAPI App 入口 (`main.py`)

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config.settings import get_settings
from services.java_client import get_java_client

from api.workflow import router as workflow_router
from api.page import router as page_router
from api.conversation import router as conversation_router
from api.health import router as health_router

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    client = get_java_client()
    await client.start()
    yield
    await client.close()

app = FastAPI(title="Insight AI Agent Service", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

app.include_router(workflow_router)
app.include_router(page_router)
app.include_router(conversation_router)
app.include_router(health_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port)
```
