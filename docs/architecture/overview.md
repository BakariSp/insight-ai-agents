# 架构总览

> 系统全景、当前架构 vs 目标架构、三层框架分工、项目结构。

---

## 当前架构（Phase 3）

```
Client (HTTP / SSE)
    │
    ▼
┌──────────────────────────────────────────────────┐
│  FastAPI App (:5000)                              │
│  POST /api/workflow/generate  → PlannerAgent      │
│  POST /api/page/generate      → ExecutorAgent(SSE)│
│  GET  /api/health                                 │
│  POST /chat                   (兼容路由)           │
│  GET  /models                                     │
│  GET  /skills                                     │
│                                                    │
│  ┌────────────────────────────────────────────┐   │
│  │  FastMCP (in-process tool registry)        │   │
│  │  + TOOL_REGISTRY dict for direct invoke    │   │
│  │  Data:  get_teacher_classes()              │   │
│  │         get_class_detail()                 │   │
│  │         get_assignment_submissions()       │   │
│  │         get_student_grades()               │   │
│  │  Stats: calculate_stats()                  │   │
│  │         compare_performance()              │   │
│  └────────────────────────────────────────────┘   │
└──────────┬────────────────────────────────────────┘
           │
     ┌─────┴──────────┐
     ▼                ▼
┌──────────────┐  ┌───────────────────────────┐
│  PlannerAgent │  │  ExecutorAgent (Phase 3)   │
│  (PydanticAI) │  │  • Blueprint → Page (SSE) │
│  • user prompt│  │  • Data → Compute → Compose│
│    → Blueprint│  │  • 确定性 block + AI 叙事  │
│  • retries=2  │  └──────────┬────────────────┘
└──────┬───────┘             │
       │               ┌─────┴─────┐
       ▼               ▼           ▼
   LLM Providers   ┌─────────┐  ┌──────────┐
   (via litellm)   │LLMService│  │  Skills  │
                   │(LiteLLM) │  │├ WebSearch│
                   │          │  │└ Memory   │
                   └──────────┘  └──────────┘
```

### 新增模块（Phase 3）

| 模块 | 文件 | 功能 |
|------|------|------|
| Path Resolver | `agents/resolver.py` | `$context.` / `$data.` / `$compute.` 路径引用解析 |
| ExecutorAgent | `agents/executor.py` | Blueprint 三阶段执行引擎（Data → Compute → Compose） |
| Executor Prompt | `config/prompts/executor.py` | compose prompt 构建器（注入数据上下文 + 计算结果） |
| Page API | `api/page.py` | POST /api/page/generate SSE 端点 |

### 新增模块（Phase 2）

| 模块 | 文件 | 功能 |
|------|------|------|
| Agent Provider | `agents/provider.py` | PydanticAI 模型创建 + FastMCP 工具桥接 |
| PlannerAgent | `agents/planner.py` | 用户 prompt → Blueprint（PydanticAI + output_type） |
| Planner Prompt | `config/prompts/planner.py` | system prompt + 动态注入组件/工具列表 |
| Workflow API | `api/workflow.py` | POST /api/workflow/generate 端点 |
| Tool Registry | `tools/__init__.py` | `TOOL_REGISTRY` dict + `get_tool_descriptions()` |

### LLM 配置管理（Phase 2 增强）

| 模块 | 文件 | 功能 |
|------|------|------|
| LLMConfig | `config/llm_config.py` | 可复用 LLM 生成参数模型（temperature, top_p, seed 等） |

LLMConfig 提供三层优先级链：`.env` 全局默认 → Agent 级覆盖 → per-call 覆盖。
每个 Agent 声明自己的 `LLMConfig` 实例，通过 `merge()` 与全局默认合并。

### Phase 1 模块（延续）

| 模块 | 文件 | 功能 |
|------|------|------|
| Pydantic Settings | `config/settings.py` | 类型安全配置，`.env` 自动加载 + `get_default_llm_config()` |
| Blueprint 模型 | `models/blueprint.py` | 三层可执行蓝图数据模型 |
| CamelModel 基类 | `models/base.py` | API 输出 camelCase 序列化 |
| API 请求模型 | `models/request.py` | Workflow / Page 请求响应 |
| 组件注册表 | `config/component_registry.py` | 6 种 UI 组件定义 |
| FastMCP 工具 | `tools/` | 4 个数据工具 + 2 个统计工具 |
| Mock 数据 | `services/mock_data.py` | 班级、学生、成绩样本 |

### 当前支持的 LLM 模型

| Provider | 前缀 | 模型示例 |
|----------|------|----------|
| 阿里通义千问 | `dashscope/` | qwen-max, qwen-plus, qwen-turbo |
| 智谱 AI | `zai/` | glm-4.7, glm-4 |
| OpenAI | `openai/` | gpt-4o, gpt-4-turbo |
| Anthropic | `anthropic/` | claude-sonnet-4-20250514, claude-opus |

**默认模型**: `dashscope/qwen-max`

---

## 目标架构

```
┌────────────────────────────────────────────────────┐
│  Next.js Frontend (React UI, SSE consumer)         │
│  studio-agents.ts → /api/ai/* proxy routes         │
└──────────────┬─────────────────────────────────────┘
               │ HTTP / SSE
               ▼
┌────────────────────────────────────────────────────┐
│  FastAPI Application (:8000)                        │
│                                                      │
│  POST /api/workflow/generate   → PlannerAgent       │
│  POST /api/page/generate       → ExecutorAgent (SSE)│
│  POST /api/page/followup       → Router→Chat/Plan   │
│  GET  /api/health                                    │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │  FastMCP (in-process tool registry)          │   │
│  │                                              │   │
│  │  Data:  get_teacher_classes()                │   │
│  │         get_class_detail()                   │   │
│  │         get_assignment_submissions()         │   │
│  │         get_student_grades()                 │   │
│  │                                              │   │
│  │  Stats: calculate_stats()                    │   │
│  │         compare_performance()                │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  Agents → LLM (async, streaming, tool_use)          │
└──────────────┬─────────────────────────────────────┘
               │ httpx
               ▼
┌────────────────────────────────────────────────────┐
│  Java Backend (:8080)                               │
│  /dify/teacher/{id}/classes/me                      │
│  /dify/teacher/{id}/classes/{classId}               │
│  /dify/teacher/{id}/classes/{classId}/assignments   │
│  /dify/teacher/{id}/submissions/assignments/{id}    │
│  /dify/teacher/{id}/submissions/students/{id}       │
└────────────────────────────────────────────────────┘
```

### 三层框架分工

```
┌─────────────────────────────────────────────────────────────┐
│  FastMCP                                                     │
│  Tool 注册层：数据获取 + 统计计算                              │
│  @mcp.tool + Pydantic 参数验证                                │
├─────────────────────────────────────────────────────────────┤
│  PydanticAI                                                   │
│  Agent 编排层：Blueprint 生成 + 执行 + 结构化页面输出           │
│  agent.run(result_type=Blueprint) / agent.iter() streaming   │
├─────────────────────────────────────────────────────────────┤
│  LiteLLM                                                      │
│  Model Provider 层：100+ providers 统一接口                    │
│  dashscope/qwen-max, openai/gpt-4o, anthropic/claude-...    │
└─────────────────────────────────────────────────────────────┘
```

### 当前 → 目标的差距

| 方面 | 当前 (Phase 3) | 目标 |
|------|------|------|
| Web 框架 | ✅ FastAPI (异步) | FastAPI (异步) |
| 工具框架 | ✅ FastMCP 6 工具 + TOOL_REGISTRY | FastMCP `@mcp.tool` + 自动 Schema |
| 数据模型 | ✅ Blueprint + CamelModel | Blueprint 三层结构 |
| 配置系统 | ✅ Pydantic Settings | Pydantic Settings |
| LLM 接入 | ✅ PydanticAI + LiteLLM | PydanticAI + LiteLLM (streaming + tool_use) |
| Agent 数量 | 2 个 (PlannerAgent + ExecutorAgent) + 1 个旧 ChatAgent | 4 个 Agent (2 对外 + 2 内部) |
| 输出模式 | ✅ SSE 流式 + JSON | SSE 流式 + JSON |
| 数据来源 | Mock 数据 | Java Backend via httpx |
| 前端集成 | 无 | Next.js API Routes proxy |

---

## 核心模块说明

### ExecutorAgent (`agents/executor.py`) — Phase 3 新增

三阶段执行引擎，将 Blueprint 转化为结构化页面:

```
Blueprint + Context
    ↓
Phase A: Data — 拓扑排序 DataBinding，调用 tools 获取数据
    ↓
Phase B: Compute — 执行 ComputeGraph TOOL 节点（解析 $data. 引用）
    ↓
Phase C: Compose — 确定性 block 构建 + AI 叙事生成
    ↓
SSE Events → PHASE / TOOL_CALL / TOOL_RESULT / MESSAGE / COMPLETE
```

关键特性:
- 拓扑排序解析 DataBinding 和 ComputeNode 的依赖关系
- 确定性 block 构建: kpi_grid (从 stats)、chart (从 distribution)、table (从 submissions)
- AI 叙事: PydanticAI Agent 根据数据上下文生成分析文本
- 路径引用解析: `resolve_ref()` / `resolve_refs()` 支持 `$context.` / `$input.` / `$data.` / `$compute.`
- 错误处理: 工具失败/LLM 超时 → error COMPLETE 事件（`page: null`）

### PlannerAgent (`agents/planner.py`) — Phase 2 新增

PydanticAI Agent，将用户自然语言请求转换为结构化 Blueprint:

```
用户 prompt + 语言偏好
    ↓
PydanticAI Agent (output_type=Blueprint, retries=2)
    ↓ system prompt 含组件注册表 + 工具列表 + 示例
LLM 生成 → Pydantic 校验 → 失败则重试
    ↓
Blueprint (DataContract + ComputeGraph + UIComposition)
```

关键特性:
- `output_type=Blueprint` 确保 LLM 输出通过 Pydantic 校验
- `retries=2` — 校验失败时自动重试
- 动态 system prompt 注入组件注册表和工具描述
- 自动填充 `source_prompt` 和 `created_at` 元数据

### Agent Provider (`agents/provider.py`) — Phase 2 新增

Agent 通用基础设施:
- `create_model()` → `"litellm:<model>"` 标识符
- `execute_mcp_tool()` → 直接调用 TOOL_REGISTRY 中的函数
- `get_mcp_tool_names()` / `get_mcp_tool_descriptions()` → 工具发现

### ChatAgent (`agents/chat_agent.py`)

旧 Agent（Phase 0 遗留），实现完整的 agent 工具循环:

```
用户消息 → 追加到历史 → 发送给 LLM (含工具定义)
    ↓
LLM 返回 → 有 tool_calls? → 执行工具 → 结果追加历史 → 重新发送
    ↓ 无 tool_calls
最终文本回复
```

关键特性:
- 按 `conversation_id` 维护多轮对话历史
- 支持 per-request 模型切换 (`model` 参数)
- 工具执行带 try/except 错误处理

### LLMConfig (`config/llm_config.py`)

可复用的 LLM 生成参数 Pydantic 模型:
- 支持 `temperature`, `top_p`, `top_k`, `seed`, `frequency_penalty`, `repetition_penalty`, `response_format`, `stop` 等参数
- `merge(overrides)` — 返回合并后的新配置（base + overrides 非 None 字段）
- `to_litellm_kwargs()` — 转换为 `litellm.completion()` 可接受的参数字典
- 每个 Agent 声明自己的 `LLMConfig`（如 PlannerAgent 用低温度 + json_object，ChatAgent 用高温度）

优先级链: `.env` 全局默认 → Agent 级 LLMConfig → per-call `**overrides`

### LLMService (`services/llm_service.py`)

LiteLLM 的轻封装:
- 构造时接受 `LLMConfig`，与全局默认合并
- 保留 `model=` 参数向后兼容
- 统一的 `chat()` 接口，支持 `**overrides` per-call 覆盖
- 自动处理 system prompt 前置
- 解析 tool_calls 为标准格式
- 提取 token 用量统计

### BaseSkill (`skills/base.py`)

所有技能的抽象基类:
- 定义 `name`, `description`, `input_schema` 抽象属性
- 定义 `execute(**kwargs)` 抽象方法
- 提供 `to_tool_definition()` → OpenAI function-calling 格式

### 现有技能

| 技能 | 文件 | 功能 |
|------|------|------|
| `web_search` | `skills/web_search.py` | Brave Search API 网络搜索 |
| `memory` | `skills/memory.py` | 持久化 JSON 键值存储 (store/retrieve/list) |

---

## 项目结构

### 当前结构（Phase 3）

```
insight-ai-agent/
├── main.py                     # FastAPI 入口
├── requirements.txt            # 依赖 (含 pydantic-ai)
├── .env.example                # 环境变量模板
├── pytest.ini                  # pytest 配置 (asyncio_mode=auto)
│
├── api/                        # API 路由
│   ├── health.py               # GET /api/health
│   ├── workflow.py             # POST /api/workflow/generate
│   ├── page.py                 # POST /api/page/generate (SSE) ← Phase 3 新增
│   ├── chat.py                 # POST /chat (兼容路由)
│   └── models_routes.py        # GET /models, GET /skills
│
├── config/                     # 配置系统
│   ├── settings.py             # Pydantic Settings + get_settings() + get_default_llm_config()
│   ├── llm_config.py           # LLMConfig 可复用生成参数模型 (merge / to_litellm_kwargs)
│   ├── component_registry.py   # 6 种 UI 组件定义
│   └── prompts/
│       ├── planner.py          # PlannerAgent system prompt + build_planner_prompt()
│       └── executor.py         # ExecutorAgent compose prompt ← Phase 3 新增
│
├── models/                     # Pydantic 数据模型
│   ├── base.py                 # CamelModel 基类 (camelCase 输出)
│   ├── blueprint.py            # Blueprint 三层模型
│   └── request.py              # API 请求/响应模型
│
├── tools/                      # FastMCP 工具
│   ├── __init__.py             # mcp + TOOL_REGISTRY + get_tool_descriptions()
│   ├── data_tools.py           # 4 个数据工具 (mock)
│   └── stats_tools.py          # 2 个统计工具 (numpy)
│
├── agents/                     # ← Phase 3 扩展
│   ├── provider.py             # create_model / execute_mcp_tool / get_mcp_tool_*
│   ├── planner.py              # PlannerAgent: user prompt → Blueprint
│   ├── resolver.py             # 路径引用解析器 ($context/$data/$compute) ← Phase 3 新增
│   ├── executor.py             # ExecutorAgent: Blueprint → Page (SSE) ← Phase 3 新增
│   └── chat_agent.py           # ChatAgent: 对话 + 工具循环 (旧)
│
├── services/
│   ├── llm_service.py          # LiteLLM 封装
│   └── mock_data.py            # 集中 mock 数据
│
├── skills/                     # 旧技能系统 (Phase 0 遗留，ChatAgent 使用)
│   ├── base.py                 # BaseSkill 抽象基类
│   ├── web_search.py           # Brave Search 技能
│   └── memory.py               # 持久化记忆技能
│
├── tests/
│   ├── test_api.py             # FastAPI 端点测试 (含 workflow + page 端点)
│   ├── test_e2e_page.py        # E2E 端到端测试 (Blueprint → SSE) ← Phase 3 新增
│   ├── test_executor.py        # ExecutorAgent 单元测试 ← Phase 3 新增
│   ├── test_resolver.py        # 路径解析器单元测试 ← Phase 3 新增
│   ├── test_llm_config.py      # LLMConfig 单元测试
│   ├── test_planner.py         # PlannerAgent 测试 (TestModel)
│   ├── test_provider.py        # Provider 单元测试
│   ├── test_models.py          # Blueprint 模型测试
│   └── test_tools.py           # FastMCP 工具测试
│
├── docs/                       # ← 本文档
│
└── .claude/                    # Claude Code 配置
```

### 目标结构

```
insight-ai-agent/
├── main.py                     # FastAPI 入口
├── requirements.txt
├── .env
│
├── config/
│   ├── settings.py             # Pydantic Settings
│   ├── component_registry.py   # 组件注册表定义
│   └── prompts/
│       ├── planner.py          # PlannerAgent system prompt
│       ├── executor.py         # ExecutorAgent system prompt
│       ├── router.py           # RouterAgent 意图分类 prompt (内部)
│       └── page_chat.py       # PageChatAgent prompt (内部)
│
├── models/
│   ├── base.py                 # CamelModel 基类
│   ├── blueprint.py            # Blueprint, DataContract, ComputeGraph, UIComposition
│   ├── components.py           # ComponentType, ComponentSlot, TabSpec
│   ├── page.py                 # PageMeta, PageTab, blocks (输出模型)
│   └── request.py              # API request/response models
│
├── tools/                      # FastMCP tools
│   ├── __init__.py             # mcp = FastMCP(...) + imports
│   ├── data_tools.py           # Java backend → data
│   └── stats_tools.py          # numpy → stats
│
├── agents/
│   ├── provider.py             # PydanticAI + LiteLLM provider + FastMCP bridge
│   ├── planner.py              # PlannerAgent: user prompt → Blueprint
│   ├── executor.py             # ExecutorAgent: Blueprint → Page (SSE)
│   ├── router.py               # RouterAgent: 意图分类 (内部组件)
│   └── page_chat.py            # PageChatAgent: 页面追问 (内部组件)
│
├── services/
│   └── mock_data.py            # Mock data (dev)
│
├── api/
│   ├── workflow.py             # POST /api/workflow/generate
│   ├── page.py                 # POST /api/page/generate + followup
│   └── health.py               # GET /api/health
│
└── tests/
    ├── test_tools.py
    ├── test_agents.py
    └── test_api.py
```
