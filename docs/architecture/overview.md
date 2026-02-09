# 架构总览

> 系统全景、AI 原生架构、三层框架分工、项目结构。
> **架构方向**: AI 原生 Tool Calling — 从"代码控制 AI"到"AI 控制代码"

---

## 当前架构（AI 原生 — NativeAgent）

> 详细方案: [`docs/plans/2026-02-09-ai-native-rewrite.md`](../plans/2026-02-09-ai-native-rewrite.md)

```
Client (HTTP / SSE)
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  FastAPI App (:5000)                                      │
│                                                            │
│  POST /api/conversation/stream → 薄网关 → NativeAgent     │
│  POST /api/conversation        → 薄网关 → NativeAgent     │
│  GET  /api/health                                          │
│                                                            │
│  ┌──────────────────────────────────────────────────┐     │
│  │  conversation.py (薄网关, ~100 行)               │     │
│  │  职责: 鉴权 → 会话管理 → NativeAgent → SSE 适配   │     │
│  │  禁止: 意图路由、业务逻辑、Tool 选择              │     │
│  │  开关: NATIVE_AGENT_ENABLED=true/false            │     │
│  └──────────────────┬───────────────────────────────┘     │
│                      │                                     │
│  ┌──────────────────▼───────────────────────────────┐     │
│  │  NativeAgent (agents/native_agent.py)             │     │
│  │  每轮: select_toolsets() → Agent(tools=subset)    │     │
│  │       → agent.run_stream() → LLM 自主调 tool      │     │
│  └──────────────────┬───────────────────────────────┘     │
│                      │                                     │
│  ┌──────────────────▼───────────────────────────────┐     │
│  │  tools/registry.py (单一工具注册源)               │     │
│  │  5 个 Toolset:                                    │     │
│  │  base_data:    get_teacher_classes, get_class_detail,  │
│  │                get_assignment_submissions,              │
│  │                get_student_grades, resolve_entity       │
│  │  analysis:     calculate_stats, compare_performance,   │
│  │                analyze_student_weakness, ...            │
│  │  generation:   generate_quiz_questions,                │
│  │                generate_pptx, generate_docx, ...       │
│  │  artifact_ops: get_artifact, patch_artifact,           │
│  │                regenerate_from_previous                │
│  │  platform:     save_as_assignment, create_share_link,  │
│  │                search_teacher_documents,               │
│  │                ask_clarification, build_report_page    │
│  └──────────────────┬───────────────────────────────┘     │
│                      │                                     │
│  ┌──────────────────▼───────────────────────────────┐     │
│  │  Adapters (tools → adapters → java_client)        │     │
│  │  class_adapter / submission_adapter / grade_adapter│     │
│  └──────────────────┬───────────────────────────────┘     │
│                      │ httpx (retry + circuit breaker)     │
│                      ▼                                     │
│  ┌──────────────────────────────────────────────────┐     │
│  │  stream_adapter.py                                │     │
│  │  PydanticAI stream → Data Stream Protocol SSE     │     │
│  └──────────────────────────────────────────────────┘     │
│                                                            │
│  Agents → LLM (async, streaming, tool_use)                │
└──────────┬───────────────────────────────────────────────┘
           │ httpx
           ▼
┌──────────────────────────────────────────────────┐
│  Java Backend (SpringBoot :8080)                  │
│  /dify/teacher/{id}/classes/me                    │
│  /dify/teacher/{id}/classes/{classId}             │
│  /dify/teacher/{id}/classes/{classId}/assignments │
│  /dify/teacher/{id}/submissions/assignments/{id}  │
│  /dify/teacher/{id}/submissions/students/{id}     │
└──────────────────────────────────────────────────┘
```

### 架构核心原则（5 个"单一"+ 2 个"零"）

| 原则 | 说明 |
|------|------|
| **单入口** | `conversation.py` 薄网关，stream + non-stream 共用同一 runtime |
| **单编排** | 只用 `Agent.run_stream()` / `run()`，不再手写 tool loop |
| **单状态** | 只用 `conversation_id` + 持久化 store，不区分 initial/followup handler |
| **单工具源** | 工具只注册一次（`tools/registry.py`），无双 registry |
| **单模型入口** | `create_model()` 保留，删除 `router_model` / `executor_model` 分离 |
| **零路由规则** | 删除 intent if-elif、confidence threshold、keyword regex |
| **零 DSL** | 删除 `$data.xxx` 解析器，tool 输出直接入 LLM context |

---

## 三层框架分工

```
┌─────────────────────────────────────────────────────────────┐
│  tools/registry.py                                           │
│  Tool 注册层：@register_tool(toolset="xxx") + schema 自动生成  │
│  5 个 toolset 分包，每轮按上下文选择子集注入                    │
├─────────────────────────────────────────────────────────────┤
│  PydanticAI                                                   │
│  Agent 编排层：Agent(tools=subset).run_stream()               │
│  LLM 自主决定是否调 tool → 自动执行 → 自动循环                 │
├─────────────────────────────────────────────────────────────┤
│  LiteLLM                                                      │
│  Model Provider 层：100+ providers 统一接口                    │
│  dashscope/qwen-max, openai/gpt-4o, anthropic/claude-...    │
└─────────────────────────────────────────────────────────────┘
```

---

## Toolset 子集注入策略

按职责分为 5 个 toolset，每轮根据上下文选择子集注入，控制在 8-12 个 tools/轮。

| Toolset | 包含的 Tools | 注入条件 |
|---------|-------------|---------|
| `base_data` | get_teacher_classes, get_class_detail, get_assignment_submissions, get_student_grades, resolve_entity | **始终注入** |
| `analysis` | calculate_stats, compare_performance, analyze_student_weakness, get_student_error_patterns, calculate_class_mastery | 消息涉及数据/成绩/分析 |
| `generation` | generate_quiz_questions, propose_pptx_outline, generate_pptx, generate_docx, render_pdf, generate_interactive_html, request_interactive_content | 消息涉及生成/创建 |
| `artifact_ops` | get_artifact, patch_artifact, regenerate_from_previous | 会话中有已生成 artifact，或消息涉及修改 |
| `platform` | save_as_assignment, create_share_link, search_teacher_documents, ask_clarification, build_report_page | **始终注入** |

**关键约束**: 宽松包含式选择，非排他分类。误包含的代价极低（多占少量 context），误排除的代价极高（功能不可用）。

---

## 统一 Artifact 模型

```python
class Artifact(BaseModel):
    artifact_id: str                          # 唯一标识
    artifact_type: str                        # 业务类型: quiz / ppt / doc / interactive
    content_format: ContentFormat             # 技术格式: json / markdown / html
    content: Any                              # 主体内容
    resources: list[ArtifactResource] = []    # 关联资源索引
    version: int = 1                          # 版本号
```

| artifact_type | content_format | 编辑能力 |
|--------------|----------------|---------|
| `quiz` | `json` | Full — patch_artifact |
| `ppt` | `json` | Partial — patch or regen |
| `doc` | `markdown` | Regen-only (v1) |
| `interactive` | `html` | Full — patch_artifact |

---

## 核心模块说明

### NativeAgent (`agents/native_agent.py`)

AI 原生 runtime，每轮根据上下文动态选择 toolset 子集，创建 PydanticAI Agent 实例。

```
用户消息 + conversation_id
    ↓
select_toolsets(message, context)  → ["base_data", "platform", "generation", ...]
    ↓
registry.get_tools(toolsets)       → PydanticAI 兼容的 tool 子集
    ↓
Agent(model, tools=subset, system_prompt)
    ↓
agent.run_stream(message, message_history=history)
    ↓
LLM 自主决定: 是否调 tool → 调哪个 → 执行 → 继续调或生成文本
    ↓
stream_adapter → Data Stream Protocol SSE
    ↓
前端
```

### 薄网关 (`api/conversation.py`)

~100 行 API 层，**不做任何业务决策**:

| 职责 | 说明 |
|------|------|
| 鉴权 | 验证 JWT，提取 teacher_id，注入 AgentDeps |
| 会话管理 | 生成/校验 conversation_id，加载/保存 message_history |
| SSE 适配 | 调用 NativeAgent.run_stream()，通过 stream_adapter 转为 SSE |
| 限流 | per-teacher QPS 限流 |
| 终态校验 | 确认 stream 正常结束，异常时补发 error 事件 |

**禁止**: 意图分流、业务逻辑、Tool 选择、状态机、模型选择

### Tool Registry (`tools/registry.py`)

单一工具注册源，废弃 FastMCP + TOOL_REGISTRY 双注册:

```python
@register_tool(toolset="generation")
async def generate_quiz_questions(
    ctx: RunContext[AgentContext],
    subject: str,
    count: int = 5,
) -> QuizOutput:
    """Generate quiz questions for a given subject."""
    ...
```

### Stream Adapter (`services/stream_adapter.py`)

PydanticAI 流事件 → Data Stream Protocol SSE:

```
PydanticAI event          →  Data Stream Protocol SSE line
TextPart(content)         →  {"type":"text-delta","delta":"..."}
ToolCallPart(name, args)  →  {"type":"tool-input-start",...}
ToolReturnPart(result)    →  {"type":"tool-output-available",...}
stream end                →  {"type":"finish","finishReason":"stop"}
```

### Agent Provider (`agents/provider.py`)

保留 `create_model()`，已删除 `execute_mcp_tool()`。

---

## 工程硬约束

| 约束 | 说明 |
|------|------|
| **单次 tool 超时** | 30s，超时返回 ToolTimeoutError |
| **max_tool_calls** | 10 次/轮，超限强制停止 |
| **max_turn_duration** | 120s 整轮硬上限 |
| **teacher 隔离** | `ctx.deps.teacher_id` 必传，tool 内部过滤数据范围 |
| **禁止生产 mock** | `DEBUG=false` 时无 teacher_id → `{"status":"error"}`，不回退 mock |
| **禁止文本启发式** | 状态判断通过结构化返回（ToolResult），不扫描文本关键词 |
| **RAG 失败语义** | status: ok / no_result / error / degraded，LLM 据此决定行为 |

---

## 项目结构（AI 原生架构目标）

```
insight-ai-agent/
├── main.py                         # FastAPI 入口 + lifespan
├── requirements.txt
├── .env.example
│
├── api/                            # API 路由
│   ├── conversation.py             # 薄网关 (~100 行) + NATIVE_AGENT_ENABLED 开关
│   └── health.py                   # GET /api/health
│
├── agents/                         # Agent 层
│   ├── native_agent.py             # NativeAgent: toolset 选择 → Agent(tools=subset)
│   └── provider.py                 # create_model() — PydanticAI 模型创建
│
├── config/
│   ├── settings.py                 # Pydantic Settings
│   ├── llm_config.py               # LLMConfig 可复用生成参数
│   └── prompts/
│       └── native_agent.py         # NativeAgent system prompt
│
├── tools/                          # 工具层（单一注册源）
│   ├── registry.py                 # @register_tool + get_tools(toolsets)
│   ├── data_tools.py               # base_data toolset
│   ├── stats_tools.py              # analysis toolset
│   ├── assessment_tools.py         # analysis toolset
│   ├── document_tools.py           # platform toolset (RAG)
│   └── quiz_tools.py               # generation toolset
│
├── models/                         # Pydantic 数据模型
│   ├── base.py                     # CamelModel 基类
│   ├── blueprint.py                # Blueprint 模型（保留，tool 输出类型）
│   ├── artifact.py                 # Artifact + ContentFormat + ArtifactResource
│   ├── tool_result.py              # ToolResult envelope + PatchOp
│   ├── conversation.py             # ConversationRequest
│   └── data.py                     # 内部数据结构 (ClassInfo, GradeData 等)
│
├── adapters/                       # Data Adapter 层
│   ├── class_adapter.py
│   ├── submission_adapter.py
│   └── grade_adapter.py
│
├── services/
│   ├── stream_adapter.py           # PydanticAI stream → Data Stream Protocol
│   ├── conversation_store.py       # 会话历史持久化 + 成对截断
│   ├── java_client.py              # httpx 异步客户端
│   ├── metrics.py                  # 结构化日志 + 可观测性
│   └── datastream.py               # DataStreamEncoder (SSE 编码)
│
├── insight_backend/                # RAG 模块
│   ├── rag_engine.py
│   ├── auth.py
│   └── ...
│
├── tests/
│   ├── golden/                     # Golden conversations 行为回归
│   ├── test_native_agent.py
│   ├── test_registry.py
│   ├── test_stream_adapter.py
│   └── ...
│
├── scripts/
│   ├── native_smoke_test.py        # 最小场景验证
│   ├── native_full_regression.py   # S1-S11 全场景回归
│   └── golden_conversation_runner.py # 行为级回归
│
└── docs/
```

### 已删除的旧编排代码

| 文件 | 行数(估) | 删除原因 |
|------|---------|---------|
| `agents/router.py` | ~315 | LLM 自主选 tool，无需意图分类 |
| `agents/executor.py` | ~500+ | 三阶段流水线被 tool calling 取代 |
| `agents/resolver.py` | ~100 | `$prefix.path` DSL 被 tool 上下文取代 |
| `agents/patch_agent.py` | ~150 | 正则匹配被 `patch_artifact` tool 取代 |
| `agents/chat_agent.py` | ~90 | 手工 tool loop 被 native agent 取代 |
| `api/conversation.py` (旧) | ~2200 | 原地重写为 ~100 行薄网关 |
| `config/prompts/router.py` | ~200 | 路由 prompt 不再需要 |
| `services/entity_resolver.py` | ~200 | 改为 `resolve_entity` tool |

---

## 当前支持的 LLM 模型

| Provider | 前缀 | 模型示例 |
|----------|------|----------|
| 阿里通义千问 | `dashscope/` | qwen-max, qwen-plus, qwen-turbo |
| 智谱 AI | `zai/` | glm-4.7, glm-4 |
| OpenAI | `openai/` | gpt-4o, gpt-4-turbo |
| Anthropic | `anthropic/` | claude-sonnet-4-20250514, claude-opus |

**默认模型**: `dashscope/qwen-max`

---

## 回退策略

| 方式 | 说明 |
|------|------|
| **快速回退** | `NATIVE_AGENT_ENABLED=false` → 分流到 `conversation_legacy.py` 冻结副本 |
| **完全回退** | `git checkout pre-native-rewrite` 分支 |
