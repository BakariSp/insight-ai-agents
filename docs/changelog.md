# 变更日志

> 按日期记录所有变更。

---

## 2026-02-02 — Phase 4.5.1: 实体解析层（Entity Resolver）

实现确定性实体解析层，自动将自然语言班级引用解析为 classId，替代大部分手动点选场景。

- 新增 `models/entity.py`: ResolvedEntity（class_id, display_name, confidence, match_type）+ ResolveResult（matches, is_ambiguous, scope_mode）
- 新增 `services/entity_resolver.py`: `resolve_classes(teacher_id, query_text)` 核心解析函数
  - 四层匹配策略：精确匹配 → 别名匹配 → 年级展开 → 模糊匹配
  - 支持中英文混合引用：`1A班`、`Form 1A`、`F1A`、`Form 1 全年级`、`1A 和 1B`
  - Levenshtein 编辑距离模糊匹配（无额外依赖）
  - 数据获取复用 `execute_mcp_tool("get_teacher_classes")`
- 更新 `models/conversation.py`: `ConversationResponse` 新增 `resolved_entities` 字段
- 更新 `api/conversation.py`: `build_workflow` 分支集成实体解析
  - 高置信度匹配 → 自动注入 classId/classIds 到 context
  - 歧义匹配 → 降级为 clarify + 匹配结果作为选项
  - context 已有 classId → 跳过解析
- 更新 `models/__init__.py`: 导出 ResolvedEntity, ResolveResult
- 新增 `tests/test_entity_resolver.py`: 15 项单元测试
- 更新 `tests/test_conversation_api.py`: 4 项集成测试
- 更新 `tests/test_conversation_models.py`: 2 项序列化测试
- 209 项测试全部通过（21 项新增 + 188 项已有）

---

## 2026-02-02 — Roadmap 优化: Phase 4.5 + Phase 5/6 调整

基于 Phase 4 闭环后的稳定性分析，新增/调整以下路线图内容:

**新增 Phase 4.5: 健壮性增强 + 数据契约升级**
- 新增 `services/entity_validator.py` 计划: 实体存在性校验层，解决"用户提到不存在的班级"导致空壳页面的问题
- 新增 `errors/exceptions.py` 计划: EntityNotFoundError / DataFetchError / ToolError 自定义异常体系
- 规划 `agents/planner.py` sourcePrompt 强制覆写: 防止 LLM 改写用户原始请求
- 规划 `models/conversation.py` action 二维结构化: mode + action + chatKind 替代混用枚举
- 规划 Executor 数据阶段错误拦截: DATA_ERROR SSE 事件，防止 error dict 穿透到页面

**调整 Phase 5: 新增 Adapter 抽象层**
- 新增 Step 5.2: `adapters/` 目录 + `models/data.py` 内部标准数据结构
- 工具层 → adapter → java_client 三层架构，隔离 Java API 变化

**调整 Phase 6: SSE 升级 + Patch 机制**
- 新增 Step 6.2: SSE 协议升级到 block/slot 粒度 (BLOCK_START / SLOT_DELTA / BLOCK_COMPLETE)
- 新增 Step 6.4: Refine Patch 机制 (PATCH_LAYOUT / PATCH_COMPOSE / FULL_REBUILD)
- 更新里程碑总览

**新增 Future 长期策略**
- ComputeGraph 节点分类策略 (tool / deterministic / llm)
- 多 Agent 协作扩展方向

---

## 2026-02-02 — Phase 4: 统一会话网关完成

- 新增 `models/conversation.py`: IntentType/FollowupIntentType 枚举、RouterResult、ClarifyChoice/ClarifyOptions、ConversationRequest/ConversationResponse (13 项模型测试)
- 新增 `agents/router.py`: RouterAgent 双模式意图分类（初始 4 种 + 追问 3 种）+ 置信度路由 (≥0.7 build, 0.4-0.7 clarify, <0.4 chat) (13 项测试)
- 新增 `agents/chat.py`: ChatAgent 闲聊 + 知识问答 (3 项测试)
- 新增 `services/clarify_builder.py`: 交互式反问选项构建，支持 needClassId/needTimeRange/needAssignment/needSubject 路由 (8 项测试)
- 新增 `agents/page_chat.py`: PageChatAgent 页面追问对话，注入 blueprint 上下文 (7 项测试)
- 新增 `api/conversation.py`: `POST /api/conversation` 统一会话端点，7 种 action 路由 (10 项 API 测试)
- 新增 `config/prompts/`: router.py (双模式 prompt) + chat.py (教育助手 prompt) + page_chat.py (页面追问 prompt)
- 更新 `main.py`: 注册 conversation router
- 标记 `POST /chat` 为 deprecated
- 新增 E2E 测试: 闲聊→反问→生成→追问→微调→重建 全闭环 (5 项 E2E 测试)
- 151 项测试全部通过 (59 项 Phase 4 新增 + 92 项已有)

## 2026-02-02 — 架构调整: 统一追问端点

- **设计变更**: 废弃原计划的 `POST /api/intent/classify` 和 `POST /api/page/chat` 两个独立端点
- **新方案**: 合并为统一的 `POST /api/page/followup` 端点，后端内部通过 RouterAgent 分类意图
- RouterAgent 和 PageChatAgent 作为内部组件，不对外暴露 HTTP 端点
- 前端只需调一个端点，根据响应中的 `action` 字段 (`chat` / `refine` / `rebuild`) 做渲染
- 更新文档: roadmap.md (Phase 4), agents.md, overview.md, target-api.md, frontend-integration.md

## 2026-02-02 — Phase 3: ExecutorAgent 完成

- 新增 `agents/resolver.py`: 路径引用解析器，支持 `$context.` / `$input.` / `$data.` / `$compute.` 四种前缀和嵌套点号路径
- 新增 `agents/executor.py`: ExecutorAgent 三阶段执行引擎（Data → Compute → Compose）
  - Phase A: 拓扑排序 DataBinding，按依赖顺序调用工具获取数据
  - Phase B: 执行 ComputeGraph TOOL 节点，解析参数引用并存入 compute_results
  - Phase C: 确定性 block 构建（kpi_grid, chart, table）+ PydanticAI 生成 AI 叙事内容
  - 错误处理：工具失败/LLM 超时 → error COMPLETE 事件
- 新增 `config/prompts/executor.py`: compose prompt 构建器，注入数据上下文和计算结果
- 新增 `api/page.py`: `POST /api/page/generate` SSE 流式端点（EventSourceResponse）
- 更新 `main.py`: 注册 page router
- 新增测试文件: `test_resolver.py` (16 项) + `test_executor.py` (16 项) + `test_e2e_page.py` (5 项) + 3 项新 API 测试
- 92 项测试全部通过

## 2026-02-02 — LLMConfig: 可复用 LLM 生成参数管理

- 新增 `config/llm_config.py`: `LLMConfig` Pydantic 模型，支持 temperature/top_p/top_k/seed/frequency_penalty/repetition_penalty/response_format/stop
- `LLMConfig.merge()` 合并配置，`to_litellm_kwargs()` 转换为 litellm 参数
- 更新 `config/settings.py`: 新增 8 个 LLM 生成参数字段 + `get_default_llm_config()` 方法
- 重构 `services/llm_service.py`: 构造时接受 `LLMConfig`，三层优先级合并（全局 → Agent → per-call）
- 更新 `agents/planner.py`: 新增 `PLANNER_LLM_CONFIG`（temperature=0.2, response_format=json_object），通过 `model_settings` 传递
- 更新 `agents/chat_agent.py`: 新增 `CHAT_LLM_CONFIG`（temperature=0.8），传入 LLMService
- 新增 `tests/test_llm_config.py`: 15 项测试覆盖构造/验证/merge/to_litellm_kwargs/Settings 集成
- 52 项测试全部通过

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
