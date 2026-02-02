# Insight AI Agent — Claude Code 项目指令

## 项目概览

教育场景 AI Agent 服务，用自然语言构建结构化的数据分析，题目生成等可交互页面。当前: FastAPI + PydanticAI + FastMCP + Pydantic 数据模型 (Phase 3 完成)。目标: 多 Agent 协作闭环 + Java 后端对接 (Phase 4+)。

文档入口: `docs/README.md`（导航首页，链接到所有子文档）。

主要文档:
- `docs/architecture/` — 架构设计（总览、多 Agent、Blueprint 模型）
- `docs/api/` — API 文档（当前端点、目标端点、SSE 协议）
- `docs/guides/` — 开发指南（快速开始、添加技能、环境变量）
- `docs/integration/` — 集成规范（前端对接、Java 后端）
- `docs/roadmap.md` — 实施路线图
- `docs/changelog.md` — 变更日志
- `docs/tech-stack.md` — 技术栈

## 开发规范

- Python 3.9+，使用 type hints
- 遵循 PEP 8
- 新功能必须有对应测试
- 新工具在 `tools/` 下定义，通过 `tools/__init__.py` 注册到 FastMCP
- 旧技能继承 `skills/base.py` 的 `BaseSkill`（仅 ChatAgent 使用）
- LLM 调用通过 `services/llm_service.py` 的 `LLMService`
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

## 当前关键文件

| 文件 | 职责 |
|------|------|
| `main.py` | FastAPI 入口，CORS 配置，路由注册 |
| `config/settings.py` | Pydantic Settings 配置 + `get_settings()` |
| `config/component_registry.py` | 6 种 UI 组件注册表 |
| `config/prompts/planner.py` | PlannerAgent system prompt + `build_planner_prompt()` |
| `models/blueprint.py` | Blueprint 三层数据模型 |
| `models/base.py` | CamelModel 基类 (camelCase 输出) |
| `models/request.py` | API 请求/响应模型 |
| `tools/__init__.py` | FastMCP 工具注册 + TOOL_REGISTRY + get_tool_descriptions() |
| `tools/data_tools.py` | 4 个数据获取工具 (mock) |
| `tools/stats_tools.py` | 2 个统计计算工具 (numpy) |
| `services/mock_data.py` | 集中管理 mock 数据 |
| `agents/provider.py` | PydanticAI 模型创建 + MCP 工具桥接 |
| `agents/planner.py` | PlannerAgent: user prompt → Blueprint |
| `agents/resolver.py` | 路径引用解析器 ($context/$input/$data/$compute) |
| `agents/executor.py` | ExecutorAgent: Blueprint → Page (SSE 三阶段执行) |
| `config/prompts/executor.py` | ExecutorAgent compose prompt 构建器 |
| `agents/chat_agent.py` | Agent 工具循环 (旧) |
| `services/llm_service.py` | LiteLLM 多模型封装 |
| `api/workflow.py` | POST /api/workflow/generate |
| `api/page.py` | POST /api/page/generate (SSE) |
| `api/health.py` | GET /api/health |
| `api/chat.py` | POST /chat 兼容路由 |
| `api/models_routes.py` | GET /models, GET /skills |
