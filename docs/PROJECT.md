# Insight AI Agent — 项目全景文档

> **最后更新**: 2026-02-02
> **当前阶段**: Phase 0 → Phase 1 过渡（Foundation 搭建中）
> **一句话概述**: 面向教育场景的 AI Agent 服务，为教师提供智能数据分析、报告生成和对话式交互。

---

## 目录

- [1. 项目愿景与目标](#1-项目愿景与目标)
- [2. 当前状态](#2-当前状态)
- [3. 目标架构](#3-目标架构)
- [4. 技术栈](#4-技术栈)
- [5. 项目结构](#5-项目结构)
- [6. API 契约](#6-api-契约)
- [7. 核心模块说明](#7-核心模块说明)
- [8. 实施路线图](#8-实施路线图)
- [9. 集成关系](#9-集成关系)
- [10. 开发指南](#10-开发指南)
- [11. 变更日志](#11-变更日志)

---

## 1. 项目愿景与目标

### 1.1 愿景

构建一个 **AI 驱动的教育数据分析平台**，教师只需用自然语言描述需求（如"分析我班级的期中考试成绩"），系统自动：
1. 理解意图并规划分析流程
2. 从后端获取数据并执行统计计算
3. 生成结构化的可视化报告
4. 支持对报告的追问和深度对话

### 1.2 核心目标

| 目标 | 说明 | 优先级 |
|------|------|--------|
| **多模型支持** | 通过 LiteLLM 支持 Anthropic/OpenAI/Qwen/GLM 等多家 LLM | ✅ 已实现 |
| **Agent 工具循环** | LLM 可调用工具获取数据、执行计算，形成完整 agent loop | ✅ 已实现 |
| **可扩展技能框架** | BaseSkill 抽象基类，新增工具只需实现接口 | ✅ 已实现 |
| **SSE 流式报告** | 报告生成过程实时推送给前端 | 🔲 待实现 |
| **多 Agent 协作** | Planner → Executor → Router 分工协作 | 🔲 待实现 |
| **FastMCP 工具注册** | 用 FastMCP 替代手写 JSON Schema，降低工具开发成本 | 🔲 待实现 |
| **Java 后端对接** | 从 Java 后端获取教师、班级、作业、成绩等真实数据 | 🔲 待实现 |
| **前端集成** | Next.js 通过 API Routes 代理，React 层零改动 | 🔲 待实现 |

### 1.3 面向用户

- **教师**: 通过对话生成班级分析报告
- **教务管理**: 跨班级/跨学科数据对比
- **前端开发者**: 消费标准化 API 和 SSE 事件流

---

## 2. 当前状态

### 2.1 已实现（Phase 0 - 基础原型）

```
✅ Flask 服务框架 (app.py)
✅ 环境配置管理 (config.py + .env)
✅ LiteLLM 多模型接入 (services/llm_service.py)
✅ Agent 工具调用循环 (agents/chat_agent.py)
✅ 技能基类框架 (skills/base.py)
✅ WebSearch 技能 - Brave Search API (skills/web_search.py)
✅ Memory 技能 - 持久化 JSON 存储 (skills/memory.py)
✅ 基础测试 (tests/test_app.py)
✅ 4 个 HTTP 端点: /health, /chat, /models, /skills
```

### 2.2 当前架构

```
Client (HTTP)
    │
    ▼
┌──────────────────────────────┐
│  Flask App (:5000)           │
│  GET  /health                │
│  POST /chat                  │
│  GET  /models                │
│  GET  /skills                │
└──────────┬───────────────────┘
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

### 2.3 当前支持的 LLM 模型

| Provider | 前缀 | 模型示例 |
|----------|------|----------|
| 阿里通义千问 | `dashscope/` | qwen-max, qwen-plus, qwen-turbo |
| 智谱 AI | `zai/` | glm-4.7, glm-4 |
| OpenAI | `openai/` | gpt-4o, gpt-4-turbo |
| Anthropic | `anthropic/` | claude-sonnet-4-20250514, claude-opus |

**默认模型**: `dashscope/qwen-max`

### 2.4 待解决问题

- [ ] 尚未从 Flask 迁移到 FastAPI
- [ ] 缺少 SSE 流式输出
- [ ] 缺少结构化报告生成逻辑
- [ ] 无 Java 后端连接（数据获取）
- [ ] 无前端集成
- [ ] 测试覆盖率低

---

## 3. 目标架构

### 3.1 系统全景

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
│  POST /api/report/generate     → ExecutorAgent (SSE)│
│  POST /api/intent/classify     → RouterAgent        │
│  POST /api/report/chat         → ChatAgent          │
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

### 3.2 多 Agent 分工

| Agent | 职责 | 输入 | 输出 |
|-------|------|------|------|
| **PlannerAgent** | 理解用户需求，生成 WorkflowTemplate | 用户自然语言 | 结构化分析方案 JSON |
| **ExecutorAgent** | 执行分析计划，调用工具，生成报告 | WorkflowTemplate + 数据 | SSE 流式报告 |
| **RouterAgent** | 对追问进行意图分类和路由 | 用户追问 | 意图类型 + 路由目标 |
| **ChatAgent** | 处理报告相关的对话式交互 | 用户消息 + 报告上下文 | 文本回复 |

### 3.3 从当前架构到目标的差距

| 方面 | 当前 | 目标 |
|------|------|------|
| Web 框架 | Flask (同步) | FastAPI (异步) |
| 工具框架 | 手写 BaseSkill + JSON Schema | FastMCP `@mcp.tool` + 自动 Schema |
| LLM 接入 | LiteLLM (通用) | Anthropic SDK (streaming + tool_use) |
| Agent 数量 | 1 个 ChatAgent | 4 个专职 Agent |
| 输出模式 | JSON 响应 | SSE 流式 + JSON |
| 数据来源 | 无 | Java Backend via httpx |
| 前端集成 | 无 | Next.js API Routes proxy |

---

## 4. 技术栈

### 4.1 当前（Phase 0）

```
flask>=3.0              # Web 框架
litellm>=1.0            # 多模型 LLM 抽象层
python-dotenv>=1.0      # 环境变量
requests>=2.31          # HTTP 客户端 (Brave Search)
pytest>=8.0             # 测试
```

### 4.2 目标（Phase 1+）

```
fastapi>=0.115.0        # 异步 Web 框架
uvicorn[standard]>=0.32 # ASGI 服务器
sse-starlette>=2.0      # SSE 响应
pydantic>=2.10          # 数据验证
pydantic-settings>=2.6  # 配置管理
fastmcp>=2.14           # 内部工具注册框架
anthropic>=0.40         # LLM SDK (streaming + tool_use)
httpx>=0.28             # 异步 HTTP 客户端 (调 Java)
numpy>=2.1              # 统计计算
python-dotenv>=1.0      # 环境变量
```

---

## 5. 项目结构

### 5.1 当前结构

```
insight-ai-agent/
├── app.py                      # Flask 入口
├── config.py                   # 配置 (dotenv)
├── requirements.txt            # 依赖
├── .env.example                # 环境变量模板
│
├── agents/
│   └── chat_agent.py           # 唯一 Agent: 对话 + 工具循环
│
├── services/
│   ├── __init__.py
│   └── llm_service.py          # LiteLLM 封装
│
├── skills/
│   ├── __init__.py
│   ├── base.py                 # BaseSkill 抽象基类
│   ├── web_search.py           # Brave Search 技能
│   └── memory.py               # 持久化记忆技能
│
├── tests/
│   └── test_app.py             # 基础测试
│
├── docs/
│   ├── PROJECT.md              # ← 本文档
│   ├── python-service.md       # 目标架构详细设计
│   └── frontend-python-integration.md  # 前端对接规范
│
└── .claude/
    ├── settings.local.json     # Claude Code 权限
    ├── agents/                 # Claude 子代理定义
    ├── skills/                 # Claude Code 开发技能
    └── commands/               # Claude Code 自定义命令
```

### 5.2 目标结构

```
insight-ai-agent/
├── main.py                     # FastAPI 入口
├── requirements.txt
├── .env
│
├── config/
│   ├── settings.py             # Pydantic Settings
│   └── prompts/
│       ├── planner.py          # PlannerAgent system prompt
│       ├── executor.py         # ExecutorAgent system prompt
│       ├── router.py           # RouterAgent system prompt
│       └── components.py       # UI block type 注册
│
├── models/
│   ├── workflow.py             # WorkflowTemplate 模型
│   ├── report.py               # 报告块类型定义
│   └── request.py              # API 请求/响应模型
│
├── tools/                      # FastMCP 工具
│   ├── __init__.py             # mcp = FastMCP(...) + imports
│   ├── data_tools.py           # Java 后端数据获取
│   └── stats_tools.py          # 统计计算
│
├── agents/
│   ├── llm.py                  # LLM Provider + Tool Bridge
│   ├── planner.py              # Agent 1: 方案规划
│   ├── executor.py             # Agent 2: 报告生成 (SSE)
│   ├── router.py               # 意图分类
│   └── chat.py                 # 对话交互
│
├── services/
│   └── mock_data.py            # Mock 数据 (开发用)
│
├── api/
│   ├── workflow.py             # POST /api/workflow/generate
│   ├── report.py               # POST /api/report/generate + chat
│   ├── intent.py               # POST /api/intent/classify
│   └── health.py               # GET /api/health
│
└── tests/
    ├── test_tools.py
    ├── test_agents.py
    └── test_api.py
```

---

## 6. API 契约

### 6.1 当前端点

| Method | Path | 功能 | 状态 |
|--------|------|------|------|
| `GET` | `/health` | 健康检查 | ✅ |
| `POST` | `/chat` | 通用对话 (支持工具调用) | ✅ |
| `GET` | `/models` | 列出支持的模型 | ✅ |
| `GET` | `/skills` | 列出可用技能 | ✅ |

**POST /chat 请求**:
```json
{
  "message": "string (必填)",
  "conversation_id": "string (可选, 续接会话)",
  "model": "string (可选, 如 'openai/gpt-4o')"
}
```

**POST /chat 响应**:
```json
{
  "conversation_id": "uuid",
  "response": "AI 回复文本",
  "model": "使用的模型",
  "usage": { "input_tokens": 0, "output_tokens": 0 }
}
```

### 6.2 目标端点

| Method | Path | 功能 | Agent | 状态 |
|--------|------|------|-------|------|
| `POST` | `/api/workflow/generate` | 生成分析方案 | PlannerAgent | 🔲 |
| `POST` | `/api/report/generate` | 生成报告 (SSE) | ExecutorAgent | 🔲 |
| `POST` | `/api/report/chat` | 报告对话 | ChatAgent | 🔲 |
| `POST` | `/api/intent/classify` | 意图分类 | RouterAgent | 🔲 |
| `GET` | `/api/health` | 健康检查 | - | 🔲 |

详细 API 契约见 [frontend-python-integration.md](./frontend-python-integration.md)。

---

## 7. 核心模块说明

### 7.1 ChatAgent (`agents/chat_agent.py`)

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

### 7.2 LLMService (`services/llm_service.py`)

LiteLLM 的轻封装:
- 统一的 `chat()` 接口
- 自动处理 system prompt 前置
- 解析 tool_calls 为标准格式
- 提取 token 用量统计

### 7.3 BaseSkill (`skills/base.py`)

所有技能的抽象基类:
- 定义 `name`, `description`, `input_schema` 抽象属性
- 定义 `execute(**kwargs)` 抽象方法
- 提供 `to_tool_definition()` → OpenAI function-calling 格式

### 7.4 现有技能

| 技能 | 文件 | 功能 |
|------|------|------|
| `web_search` | `skills/web_search.py` | Brave Search API 网络搜索 |
| `memory` | `skills/memory.py` | 持久化 JSON 键值存储 (store/retrieve/list) |

---

## 8. 实施路线图

### Phase 0: 基础原型 ✅ 已完成

- [x] Flask 服务框架
- [x] LiteLLM 多模型接入
- [x] Agent 工具循环
- [x] BaseSkill 技能框架
- [x] WebSearch + Memory 技能
- [x] 基础测试

### Phase 1: Foundation 🔄 进行中

- [ ] Flask → FastAPI 迁移
- [ ] uvicorn ASGI 服务器
- [ ] Pydantic Settings 配置
- [ ] FastMCP 工具注册 (`@mcp.tool`)
- [ ] 数据工具: mock 数据版本
- [ ] 统计工具: calculate_stats, compare_performance
- [ ] 验证: `fastmcp dev tools/__init__.py`

### Phase 2: 报告生成

- [ ] ExecutorAgent: streaming 工具循环
- [ ] PlannerAgent: 结构化方案输出 (generateObject)
- [ ] SSE 端点 `/api/report/generate`
- [ ] 报告块类型定义 (KPI Grid, Chart, Table, Markdown 等)
- [ ] 验证: curl SSE 输出格式

### Phase 3: 路由与对话

- [ ] RouterAgent + `/api/intent/classify`
- [ ] `/api/report/chat` 报告对话
- [ ] CamelCase 输出序列化

### Phase 4: Java 后端对接

- [ ] mock → httpx 调 Java API
- [ ] 错误处理 + 重试
- [ ] 数据格式映射

### Phase 5: 前端集成

- [ ] Next.js proxy routes (API Routes 代理)
- [ ] SSE 消费对接
- [ ] E2E 测试
- [ ] 上线

---

## 9. 集成关系

### 9.1 三层架构

```
React Pages (零改动)
    ↓ fetch('/api/ai/xxx')
Next.js API Routes (唯一改动层, Proxy)
    ↓ HTTP/SSE
Python FastAPI Service (本项目)
    ↓ httpx
Java Backend (:8080, 数据源)
```

### 9.2 SSE 事件协议

```
data: {"type":"TOOL_CALL",   "tool":"get_class_detail","args":{...}}
data: {"type":"TOOL_RESULT", "tool":"get_class_detail","result":{...}}
data: {"type":"MESSAGE",     "content":"Based on my analysis..."}
data: {"type":"COMPLETE",    "message":"completed","progress":100,"result":{...}}
```

前端只消费 `MESSAGE` 和 `COMPLETE`，忽略 `TOOL_CALL`/`TOOL_RESULT`。

### 9.3 字段映射

- Python 内部: `snake_case`
- API 输出: `camelCase` (Pydantic `alias_generator=to_camel`)
- Next.js proxy: 直接透传，不做转换

---

## 10. 开发指南

### 10.1 快速开始

```bash
# 克隆项目
git clone <repo-url>
cd insight-ai-agent

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key

# 启动服务
python app.py
# 服务运行在 http://localhost:5000
```

### 10.2 测试

```bash
# 运行测试
pytest tests/ -v

# 测试 /chat 端点
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好，介绍一下你自己"}'

# 使用其他模型
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello", "model": "openai/gpt-4o"}'
```

### 10.3 添加新技能

1. 在 `skills/` 下创建新文件
2. 继承 `BaseSkill`
3. 实现 `name`, `description`, `input_schema`, `execute()`
4. 在 `agents/chat_agent.py` 的 `_load_skills()` 中注册

```python
from skills.base import BaseSkill

class MySkill(BaseSkill):
    @property
    def name(self) -> str:
        return "my_skill"

    @property
    def description(self) -> str:
        return "Description shown to the LLM"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "..."}
            },
            "required": ["param1"]
        }

    def execute(self, **kwargs) -> str:
        return f"Result: {kwargs['param1']}"
```

### 10.4 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `FLASK_DEBUG` | 调试模式 | `false` |
| `SECRET_KEY` | Flask 密钥 | `dev-secret-key` |
| `LLM_MODEL` | 默认 LLM (含 provider 前缀) | `dashscope/qwen-max` |
| `MAX_TOKENS` | 最大 token 数 | `4096` |
| `DASHSCOPE_API_KEY` | 阿里通义千问 API Key | - |
| `ZAI_API_KEY` | 智谱 AI API Key | - |
| `OPENAI_API_KEY` | OpenAI API Key | - |
| `ANTHROPIC_API_KEY` | Anthropic API Key | - |
| `BRAVE_API_KEY` | Brave Search API Key | - |
| `MCP_SERVER_NAME` | MCP 服务名称 | `insight-ai-agent` |

---

## 11. 变更日志

### 2026-02-02 — 文档创建 & 技能安装

- 创建项目全景文档 (本文档)
- 安装 Claude Code 开发技能:
  - `writing-plans`: 实施计划编写
  - `executing-plans`: 计划分批执行
  - `test-driven-development`: TDD 开发方法论
  - `systematic-debugging`: 系统化调试流程
  - `verification-before-completion`: 完成前验证协议
  - `debug-like-expert`: 专家级调试方法
  - `update-docs`: 文档自动更新技能

### 2026-02-02 — Phase 0 完成

- 初始项目搭建: Flask + LiteLLM + BaseSkill
- 实现 ChatAgent 工具循环
- 实现 WebSearch 和 Memory 技能
- 基础测试
- 从 Anthropic-specific 重构为 provider-agnostic 架构

---

> **阅读本文档后你应该知道**:
> 1. 这是一个教育 AI Agent 服务，帮教师做数据分析和报告生成
> 2. 当前是 Flask + LiteLLM 的基础原型，支持多模型 + 工具调用
> 3. 目标是 FastAPI + FastMCP 的多 Agent 系统 (Planner/Executor/Router/Chat)
> 4. 需要对接 Java 后端获取教育数据，对接 Next.js 前端展示报告
> 5. 正在从 Phase 0 过渡到 Phase 1 (Foundation)
