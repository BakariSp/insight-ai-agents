# 变更日志

> 按日期记录所有变更。

---

## 2026-02-02 — Phase 2: PlannerAgent 完成

- 新增 `pydantic-ai>=1.0` 依赖，引入 PydanticAI Agent 框架
- 新增 `agents/provider.py`: `create_model()` / `execute_mcp_tool()` / `get_mcp_tool_names()` / `get_mcp_tool_descriptions()`
- 新增 `config/prompts/planner.py`: PlannerAgent system prompt + `build_planner_prompt()` 动态注入
- 新增 `agents/planner.py`: PydanticAI Agent (`output_type=Blueprint`, `retries=2`) + `generate_blueprint()` 异步函数
- 新增 `api/workflow.py`: `POST /api/workflow/generate` 端点 + 502 错误处理
- 更新 `tools/__init__.py`: 新增 `TOOL_REGISTRY` dict + `get_tool_descriptions()` 辅助函数
- 更新 `main.py`: 注册 workflow router
- 新增测试文件: `test_provider.py` (7 项) + `test_planner.py` (5 项) + 3 项新 API 测试
- 37 项测试全部通过

## 2026-02-02 — Phase 1: Foundation 完成

- Flask → FastAPI 迁移: `main.py` 入口 + `api/` 路由模块 + CORS 中间件
- Pydantic Settings 配置: `config/settings.py` 替代旧 `config.py`，支持类型校验和 `.env` 自动加载
- Blueprint 三层数据模型: `models/blueprint.py` (DataContract, ComputeGraph, UIComposition) + CamelModel 基类
- API 请求/响应模型: `models/request.py` (WorkflowGenerateRequest/Response 等)
- 组件注册表: `config/component_registry.py` — 6 种 UI 组件定义 + `get_registry_description()`
- FastMCP 工具注册: `tools/` — 4 个数据工具 + 2 个统计工具 (numpy)
- Mock 数据: `services/mock_data.py` — 班级、学生、成绩样本数据
- 依赖升级: 移除 Flask，新增 FastAPI/uvicorn/sse-starlette/pydantic-settings/fastmcp/numpy/httpx/pytest-asyncio
- 删除旧文件: `app.py`, `config.py`, `tests/test_app.py`
- 新增 `.env.example` 模板和 `pytest.ini` 配置
- 22 项测试全部通过 (test_api + test_models + test_tools)

## 2026-02-02 — 文档重构

- 将单一 `PROJECT.md` 拆分为多文件文档体系
- 新建 `docs/` 子目录: `architecture/`, `api/`, `guides/`, `integration/`
- 创建文档导航首页 `docs/README.md`
- 独立 `roadmap.md`, `changelog.md`, `tech-stack.md`

## 2026-02-02 — 文档创建 & 技能安装

- 创建项目全景文档
- 安装 Claude Code 开发技能:
  - `writing-plans`: 实施计划编写
  - `executing-plans`: 计划分批执行
  - `test-driven-development`: TDD 开发方法论
  - `systematic-debugging`: 系统化调试流程
  - `verification-before-completion`: 完成前验证协议
  - `debug-like-expert`: 专家级调试方法
  - `update-docs`: 文档自动更新技能

## 2026-02-02 — Phase 0 完成

- 初始项目搭建: Flask + LiteLLM + BaseSkill
- 实现 ChatAgent 工具循环
- 实现 WebSearch 和 Memory 技能
- 基础测试
- 从 Anthropic-specific 重构为 provider-agnostic 架构
