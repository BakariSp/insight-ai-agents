# 架构总览

> 系统全景、当前架构 vs 目标架构、三层框架分工、项目结构。

---

## 当前架构（Phase 1）

```
Client (HTTP)
    │
    ▼
┌──────────────────────────────────────────────┐
│  FastAPI App (:5000)                          │
│  GET  /api/health                             │
│  POST /chat              (兼容路由)            │
│  GET  /models                                 │
│  GET  /skills                                 │
│                                                │
│  ┌────────────────────────────────────────┐   │
│  │  FastMCP (in-process tool registry)    │   │
│  │  Data:  get_teacher_classes()          │   │
│  │         get_class_detail()             │   │
│  │         get_assignment_submissions()   │   │
│  │         get_student_grades()           │   │
│  │  Stats: calculate_stats()             │   │
│  │         compare_performance()          │   │
│  └────────────────────────────────────────┘   │
└──────────┬───────────────────────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  ChatAgent                   │
│  • 会话历史管理              │
│  • Agent 工具调用循环        │
│  • 技能注册与执行            │
└──────────┬───────────────────┘
           │
     ┌─────┴─────┐
     ▼           ▼
┌─────────┐  ┌──────────┐
│LLMService│  │  Skills  │
│(LiteLLM) │  │├ WebSearch│
│          │  │└ Memory   │
└────┬─────┘  └──────────┘
     ▼
 LLM Providers
 ├ dashscope/qwen-*
 ├ zai/glm-*
 ├ openai/gpt-*
 └ anthropic/claude-*
```

### 新增模块（Phase 1）

| 模块 | 文件 | 功能 |
|------|------|------|
| Pydantic Settings | `config/settings.py` | 类型安全配置，`.env` 自动加载 |
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
│  POST /api/intent/classify     → RouterAgent        │
│  POST /api/page/chat           → ChatAgent          │
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

| 方面 | 当前 (Phase 1) | 目标 |
|------|------|------|
| Web 框架 | ✅ FastAPI (异步) | FastAPI (异步) |
| 工具框架 | ✅ FastMCP 6 工具已注册 | FastMCP `@mcp.tool` + 自动 Schema |
| 数据模型 | ✅ Blueprint + CamelModel | Blueprint 三层结构 |
| 配置系统 | ✅ Pydantic Settings | Pydantic Settings |
| LLM 接入 | LiteLLM (通用) | PydanticAI + LiteLLM (streaming + tool_use) |
| Agent 数量 | 1 个 ChatAgent | 4 个专职 Agent |
| 输出模式 | JSON 响应 | SSE 流式 + JSON |
| 数据来源 | Mock 数据 | Java Backend via httpx |
| 前端集成 | 无 | Next.js API Routes proxy |

---

## 核心模块说明

### ChatAgent (`agents/chat_agent.py`)

当前唯一的 Agent，实现完整的 agent 工具循环:

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

### LLMService (`services/llm_service.py`)

LiteLLM 的轻封装:
- 统一的 `chat()` 接口
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

### 当前结构（Phase 1）

```
insight-ai-agent/
├── main.py                     # FastAPI 入口
├── requirements.txt            # 依赖
├── .env.example                # 环境变量模板
├── pytest.ini                  # pytest 配置 (asyncio_mode=auto)
│
├── api/                        # API 路由
│   ├── health.py               # GET /api/health
│   ├── chat.py                 # POST /chat (兼容路由)
│   └── models_routes.py        # GET /models, GET /skills
│
├── config/                     # 配置系统
│   ├── settings.py             # Pydantic Settings + get_settings()
│   └── component_registry.py   # 6 种 UI 组件定义
│
├── models/                     # Pydantic 数据模型
│   ├── base.py                 # CamelModel 基类 (camelCase 输出)
│   ├── blueprint.py            # Blueprint 三层模型
│   └── request.py              # API 请求/响应模型
│
├── tools/                      # FastMCP 工具
│   ├── __init__.py             # mcp = FastMCP(...) + 工具注册
│   ├── data_tools.py           # 4 个数据工具 (mock)
│   └── stats_tools.py          # 2 个统计工具 (numpy)
│
├── agents/
│   └── chat_agent.py           # ChatAgent: 对话 + 工具循环
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
│   ├── test_api.py             # FastAPI 端点测试 (httpx.AsyncClient)
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
│       ├── router.py           # Intent classification prompt
│       └── chat.py             # Chat agent prompt
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
│   ├── router.py               # RouterAgent: intent classification
│   └── chat.py                 # ChatAgent: page follow-up
│
├── services/
│   └── mock_data.py            # Mock data (dev)
│
├── api/
│   ├── workflow.py             # POST /api/workflow/generate
│   ├── page.py                 # POST /api/page/generate + chat
│   ├── intent.py               # POST /api/intent/classify
│   └── health.py               # GET /api/health
│
└── tests/
    ├── test_tools.py
    ├── test_agents.py
    └── test_api.py
```
