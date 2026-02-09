# Insight AI Agent — Claude Code 项目指令

## 项目概览

教育场景 AI Agent 服务，用自然语言构建结构化的数据分析、题目生成等可交互页面。

**当前架构方向**: AI 原生 Tool Calling — 单 NativeAgent runtime，LLM 自主选择工具编排，取代旧多 Agent 硬编码路由。
详细方案: `docs/plans/2026-02-09-ai-native-rewrite.md`

技术栈: FastAPI + PydanticAI + LiteLLM + Pydantic 数据模型 + Java 后端 Adapter 层

## ⚠️ 重要提示

- ✅ **所有代码都可以自由修改**：无需担心用户端的前向兼容
- ✅ **架构正在重构**：从多 Agent 硬编码编排 → AI 原生 Tool Calling 单 runtime
- ✅ **API 可以 Breaking Change**：原地替换实现，端点路径不变
- ⚠️ **前提条件**：确保修改后通过测试（`pytest tests/ -v`）
- ⚠️ **迁移开关**：`NATIVE_AGENT_ENABLED=true`（默认新路径）/ `false`（紧急回退 legacy）

文档入口: `docs/README.md`（导航首页，链接到所有子文档）。

主要文档:
- `docs/plans/2026-02-09-ai-native-rewrite.md` — **AI 原生重构完整方案**（Step 0.5–4）
- `docs/architecture/` — 架构设计（总览、NativeAgent、Artifact 模型）
- `docs/api/` — API 文档（当前端点、SSE 协议）
- `docs/guides/` — 开发指南（快速开始、添加工具、环境变量）
- `docs/integration/` — 集成规范（前端对接、Java 后端）
- `docs/testing/` — 测试报告与用例记录
- `docs/roadmap.md` — 实施路线图
- `docs/changelog.md` — 变更日志
- `docs/tech-stack.md` — 技术栈

## 开发规范

- Python 3.9+，使用 type hints
- 遵循 PEP 8
- 新功能必须有对应测试
- **新工具**: 在 `tools/` 下定义，用 `@register_tool(toolset="xxx")` 注册到 `tools/registry.py`（单一注册源）
- **禁止**: 手工 tool loop、意图 if-elif 路由、文本启发式状态判断、生产环境 mock 回退
- LLM 调用通过 PydanticAI `Agent.run_stream()` / `Agent.run()`
- 配置通过 `config/settings.py` 的 `Settings(BaseSettings)` + `.env`

## 文档更新规则

**每次完成功能开发或结构性变更后**，使用 `/update-docs` 命令更新对应的文档文件。

需要更新文档的场景及对应文件:
- 新增或删除文件/模块 → `docs/architecture/overview.md`
- 新增或修改 API 端点 → `docs/api/`
- 新增或修改技能/工具 → `docs/guides/adding-skills.md`
- 完成路线图中的某个任务 → `docs/roadmap.md`
- 依赖变化 (requirements.txt) → `docs/tech-stack.md`
- 架构调整 → `docs/architecture/`
- 完成某阶段测试/新增用例 → `docs/testing/` (报告 + Use Case 索引)
- 所有变更 → `docs/changelog.md`（追加记录）

## 常用命令

```bash
# 启动服务
python main.py
# 或 uvicorn main:app --reload

# 运行测试
pytest tests/ -v

# 更新文档
# 使用 /update-docs 命令
```

## 当前关键文件 (AI 原生架构)

### 核心 Runtime（新）

| 文件 | 职责 |
|------|------|
| `agents/native_agent.py` | **NativeAgent**: 按上下文选 toolset → `Agent(tools=subset).run_stream()` |
| `tools/registry.py` | **单一工具注册源**: `@register_tool(toolset="xxx")` + `get_tools(toolsets=[...])` |
| `api/conversation.py` | **薄网关** (~100 行): 鉴权、会话、SSE 适配、限流 (含 `NATIVE_AGENT_ENABLED` 开关) |
| `services/stream_adapter.py` | PydanticAI stream → Data Stream Protocol 事件适配 |
| `config/prompts/native_agent.py` | NativeAgent system prompt: 角色定义 + 能力列表 + tool 使用规则 |

### 工具与数据

| 文件 | 职责 |
|------|------|
| `tools/data_tools.py` | 数据获取工具 (toolset=base_data): get_teacher_classes, get_class_detail 等 |
| `tools/stats_tools.py` | 统计分析工具 (toolset=analysis): calculate_stats, compare_performance 等 |
| `tools/assessment_tools.py` | 学情分析工具 (toolset=analysis): analyze_student_weakness 等 |
| `tools/document_tools.py` | RAG 文档检索工具 (toolset=platform): search_teacher_documents |
| `tools/quiz_tools.py` | 题目生成工具 (toolset=generation): generate_quiz_questions |
| `adapters/` | Java API → 内部 DTO 映射层 |
| `services/java_client.py` | Java 后端 HTTP 客户端 (httpx + retry + circuit breaker) |

### 基础设施

| 文件 | 职责 |
|------|------|
| `main.py` | FastAPI 入口，CORS 配置，路由注册 |
| `config/settings.py` | Pydantic Settings 配置 + `get_settings()` |
| `agents/provider.py` | `create_model()` — PydanticAI 模型创建（已删除 `execute_mcp_tool()`） |
| `services/conversation_store.py` | 会话历史持久化 (conversation_id 主键) |
| `models/blueprint.py` | Blueprint 数据模型（保留，作为 tool 输出类型） |
| `models/base.py` | CamelModel 基类 (camelCase 输出) |

### 已删除/计划删除（旧编排代码）

| 文件 | 状态 | 替代方案 |
|------|------|---------|
| `agents/router.py` | 删除 | LLM 自主选 tool |
| `agents/executor.py` | 删除 | NativeAgent + tool calling |
| `agents/resolver.py` | 删除 | tool 输出直接入 LLM context |
| `agents/patch_agent.py` | 删除 | `patch_artifact` tool |
| `agents/chat_agent.py` | 删除 | NativeAgent |
| `services/entity_resolver.py` | 删除 | `resolve_entity` tool |
| `config/prompts/router.py` | 删除 | 无需路由 prompt |
| `tools/__init__.py` (TOOL_REGISTRY) | 重写 | `tools/registry.py` 单一注册 |
