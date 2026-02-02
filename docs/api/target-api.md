# 目标 API（Phase 1+）

> FastAPI 服务的 5 个端点。详细 SSE 协议和 Block 格式见 [sse-protocol.md](./sse-protocol.md)。

---

## 端点概览

| Method | Path | 功能 | Agent | 状态 |
|--------|------|------|-------|------|
| `POST` | `/api/workflow/generate` | 生成 Blueprint | PlannerAgent | 🔲 |
| `POST` | `/api/report/generate` | 执行 Blueprint (SSE) | ExecutorAgent | 🔲 |
| `POST` | `/api/report/chat` | 报告对话 | ChatAgent | 🔲 |
| `POST` | `/api/intent/classify` | 意图分类 | RouterAgent | 🔲 |
| `GET` | `/api/health` | 健康检查 | - | 🔲 |

---

## 1. Workflow Generate (PlannerAgent → Blueprint)

生成 Blueprint（可执行蓝图）。Blocking 模式，不需要 streaming。

```
Frontend                    Next.js Proxy                 Python Service
────────                    ─────────────                 ──────────────

POST /api/ai/               POST /api/workflow/
workflow-generate            generate

{                  ──►      {                    ──►     PlannerAgent
  userPrompt:                 user_prompt:                (result_type=Blueprint)
  "Analyze..."                "Analyze...",
}                             language: "en"
                              }

                  ◄──       {                    ◄──     Blueprint JSON
{                             success: true,
  success: true,              chat_response: "...",
  chatResponse: "...",        blueprint: {
  blueprint: {                  id: "bp-...",
    id: "bp-...",               name: "...",
    name: "...",                data_contract: {...},
    dataContract: {...},        compute_graph: {...},
    computeGraph: {...},        ui_composition: {...},
    uiComposition: {...},       report_system_prompt: "..."
    reportSystemPrompt: "..."   }
  }                           }
}
```

**Python Request:**

```python
class WorkflowGenerateRequest(BaseModel):
    user_prompt: str          # 用户原始输入
    language: str = "en"      # 输出语言
```

**Python Response:**

```python
class WorkflowGenerateResponse(CamelModel):
    success: bool
    chat_response: str
    blueprint: BlueprintOutput
```

---

## 2. Report Generate (ExecutorAgent — SSE Streaming)

最关键的端点。Python 服务**执行 Blueprint**（三阶段），输出 SSE stream。

```
Frontend                  Next.js Proxy              Python Service
────────                  ─────────────              ──────────────

POST /api/ai/             POST /api/report/
report-generate           generate

{                  ──►    {                   ──►    ExecutorAgent
  blueprint: {...},         blueprint: {...},          (execute Blueprint)
  data: {...},              data: {...},
  context: {                context: {
    teacherId: "t-001"       teacher_id: "t-001"
  }                         }
}                           }

                  ◄──     SSE stream            ◄──  SSE stream
```

**Python Request:**

```python
class ReportGenerateRequest(CamelModel):
    blueprint: dict                              # 完整 Blueprint JSON
    data: dict                                   # 用户选择的数据
    context: dict | None = None                  # 运行时上下文（teacherId 等）
```

SSE 事件格式详见 [sse-protocol.md](./sse-protocol.md)。

---

## 3. Report Chat (Follow-up Questions)

非流式端点，用于追问已有报告。

```
Frontend                  Next.js Proxy              Python Service
────────                  ─────────────              ──────────────

POST /api/ai/             POST /api/report/
report-chat               chat

{                  ──►    {                   ──►    Chat Agent
  userMessage:              user_message:
  "哪些学生...",            "哪些学生...",
  reportContext: {...},     report_context: {...},
  data: {...}               data: {...}
}                           }

{                  ◄──    {                   ◄──    Text response
  success: true,            success: true,
  chatResponse: "..."       chat_response: "..."
}                           }
```

**Python Request:**

```python
class ReportChatRequest(BaseModel):
    user_message: str
    report_context: dict | None = None    # { meta, data_summary }
    data: dict | None = None
```

**Python Response:**

```python
class ReportChatResponse(BaseModel):
    success: bool
    chat_response: str                    # Markdown 格式
```

---

## 4. Classify Intent (Follow-up Router)

替换当前的关键词路由，判断用户追问走哪个路径。

```
Frontend                  Next.js Proxy              Python Service
────────                  ─────────────              ──────────────

POST /api/ai/             POST /api/intent/
classify-intent           classify

{                  ──►    {                   ──►    Router Agent
  userMessage:              user_message:
  "增加语法...",            "增加语法...",
  workflowName:             workflow_name:
  "Performance...",         "Performance...",
  reportSummary:            report_summary:
  "Overall good..."        "Overall good..."
}                           }

{                  ◄──    {                   ◄──    Classification
  intent:                   intent:
  "workflow_rebuild",       "workflow_rebuild",
  confidence: 0.92          confidence: 0.92
}                           }
```

**Intent 值和前端处理:**

| Intent | 前端动作 | 调用的函数 |
|--------|---------|-----------|
| `workflow_rebuild` | 重新生成 Blueprint + report | `generateWorkflow()` → `generateReport()` |
| `report_refine` | 仅重新生成 report | `generateReport()` (带修改指令) |
| `data_chat` | 追问对话 | `chatWithReport()` |

---

## 5. Health Check

```bash
curl http://localhost:8000/api/health
# → {"status": "healthy", "version": "1.0.0"}
```

---

## FastAPI App 入口 (`main.py`)

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config.settings import get_settings

from api.workflow import router as workflow_router
from api.report import router as report_router
from api.intent import router as intent_router
from api.health import router as health_router

settings = get_settings()

app = FastAPI(title="Insight AI Agent Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

app.include_router(workflow_router)
app.include_router(report_router)
app.include_router(intent_router)
app.include_router(health_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port)
```
