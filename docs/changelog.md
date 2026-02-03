# 变更日志

> 按日期记录所有变更。

---

## 2026-02-03 — Phase 6.3-6.4 完成: Per-Block AI 生成 + Patch 机制

实现 Per-Block AI 生成（Level 2）和 Patch 机制，支持增量页面修改。

**Step 6.3: Per-Block AI 生成**
- 新增 `config/prompts/block_compose.py`: Per-block prompt 构建器
  - `build_block_prompt()` → `(prompt, output_format)` 根据 component_type 选择 prompt
  - `_build_markdown_prompt()` — 分析叙事文本 prompt (output_format="text")
  - `_build_suggestion_prompt()` — JSON 建议列表 prompt (output_format="json")
  - `_build_question_prompt()` — JSON 题目生成 prompt (output_format="json")
  - `_build_data_summary()` — 注入 data_context + compute_results
- 新增 `tests/test_block_compose.py`: 15 项 prompt 构建器测试
- 重构 `agents/executor.py`:
  - `_generate_block_content()` 使用 `build_block_prompt()` 生成 per-block prompt
  - `_parse_json_output()` 解析 LLM JSON 返回值（支持 markdown code block 包装）
  - `_fill_single_block()` 处理 list/dict 返回值
  - 删除旧的 `_generate_ai_narrative()` + `_fill_ai_content()`
- 新增 10 项 Executor 测试 (`tests/test_executor.py`)

**Step 6.4: Patch 机制**
- 新增 `models/patch.py`: Patch 数据模型
  - `PatchType` 枚举: update_props, reorder, add_block, remove_block, recompose
  - `RefineScope` 枚举: patch_layout, patch_compose, full_rebuild
  - `PatchInstruction(CamelModel)`: type, target_block_id, changes
  - `PatchPlan(CamelModel)`: scope, instructions, affected_block_ids, compose_instruction
- 新增 `tests/test_patch_models.py`: 10 项 Patch 模型测试
- 新增 `agents/patch_agent.py`: Patch 分析 agent
  - `analyze_refine()` 根据 refine_scope 生成 PatchPlan
  - `_analyze_layout_patch()` 检测颜色/样式修改
  - `_analyze_compose_patch()` 识别 ai_content_slot blocks
- 更新 `agents/executor.py`:
  - 新增 `execute_patch()` 异步生成器执行 PatchPlan
  - 辅助函数: `_find_slot()`, `_find_block_by_id()`, `_apply_prop_patch()`
- 新增 `tests/test_patch.py`: 18 项 Patch 执行测试
- 更新 `models/conversation.py`:
  - `RouterResult` 新增 `refine_scope: str | None`
  - `ConversationResponse` 新增 `patch_plan: PatchPlan | None`
- 更新 `config/prompts/router.py`: followup prompt 新增 refine_scope 输出指导
- 更新 `models/request.py`: 新增 `PagePatchRequest`
- 更新 `api/page.py`: 新增 `POST /api/page/patch` 端点
- 更新 `api/conversation.py`: refine 分支按 scope 分流
- 新增 4 项 conversation API 测试 + 4 项 Router 测试

- 312 项测试全部通过（74 项新增 + 238 项已有）

---

## 2026-02-03 — Phase 6.1 完成: SSE 事件模型 + 前端 Proxy 文档契约

Phase 6 首步，定义 SSE block/slot 粒度事件模型并编写前端对接文档。

**Step 6.1: SSE 事件模型 + Proxy 文档契约**
- 新增 `models/sse_events.py`: BlockStartEvent, SlotDeltaEvent, BlockCompleteEvent（继承 CamelModel）
  - `BlockStartEvent`: blockId + componentType
  - `SlotDeltaEvent`: blockId + slotKey + deltaText
  - `BlockCompleteEvent`: blockId
- 新增 `tests/test_sse_events.py`: camelCase 序列化测试（blockId, componentType, slotKey, deltaText）
- 新增 `docs/integration/nextjs-proxy.md`: 前端 proxy 路由契约文档（SSE 透传、CORS 策略、路由映射）
- 更新 `docs/api/sse-protocol.md`: Block/Slot 粒度事件从 "planned" 改为 "implemented"，新增事件详情、slotKey 映射表、事件顺序说明

---

## 2026-02-03 — Phase 5 完成: Java 后端对接

实现 Adapter 抽象层 + HTTP 客户端封装 + 数据工具双源切换 + 重试/熔断/降级机制。

**Step 5.1: HTTP 客户端封装**
- 新增 `services/java_client.py`: `JavaClient` 封装 `httpx.AsyncClient`，配置 base_url / timeout / Bearer token 认证
- 自定义异常: `JavaClientError`（非 2xx）+ `CircuitOpenError`（熔断器打开）
- `get_java_client()` 单例模式 + `main.py` lifespan 管理生命周期
- 更新 `config/settings.py`: 新增 `spring_boot_base_url`, `spring_boot_api_prefix`, `spring_boot_timeout`, `spring_boot_access_token`, `spring_boot_refresh_token`, `use_mock_data` 配置项

**Step 5.2: Data Adapter 抽象层**
- 新增 `models/data.py`: 8 个内部数据模型（ClassInfo, ClassDetail, StudentInfo, AssignmentInfo, SubmissionData, SubmissionRecord, GradeData, GradeRecord）
- 新增 `adapters/class_adapter.py`: Java Classroom API → ClassInfo/ClassDetail/AssignmentInfo
- 新增 `adapters/submission_adapter.py`: Java Submission API → SubmissionData/SubmissionRecord
- 新增 `adapters/grade_adapter.py`: Java Grade API → GradeData/GradeRecord
- 每个 adapter 实现 `_unwrap_data()` 解包 Java `Result<T>` + `_parse_*()` 字段映射

**Step 5.3: 数据工具切换**
- 重构 `tools/data_tools.py`: 4 个数据工具调用 adapter → java_client，保留 mock fallback
- `_should_use_mock()` → `Settings.use_mock_data` 开关
- 所有工具 `except Exception` → 自动降级到 mock 数据
- 工具对外接口（返回 dict）不变，Planner/Executor 无需修改

**Step 5.4: 错误处理与健壮性**
- 重试: 指数退避（MAX_RETRIES=3, RETRY_BASE_DELAY=0.5s），重试网络错误 + 5xx，不重试 4xx
- 熔断: CIRCUIT_OPEN_THRESHOLD=5 次连续失败 → 打开，CIRCUIT_RESET_TIMEOUT=60s 后 HALF_OPEN 探测
- 请求日志: `"{method} {path} → {status_code} ({elapsed_ms}ms)"`
- 新增 `tests/test_java_client.py`: 20 项测试（重试/熔断/生命周期/单例）
- 新增 `tests/test_adapters.py`: 15 项测试（3 个 adapter × Java 响应样本 → 内部模型）
- 更新 `tests/test_tools.py`: 8 项新增（4 个工具降级 + 4 个 adapter 路径）
- 更新 `tests/test_e2e_page.py`: 2 项新增（Java 500/timeout → mock 降级 → 完整页面输出）

- 238 项测试全部通过（8 项新增 + 230 项已有）

---

## 2026-02-02 — Phase 4.5 完成: 健壮性增强 + 数据契约升级

完成 Phase 4.5 剩余三步（4.5.2–4.5.4），全面提升系统健壮性。

**Step 4.5.2: sourcePrompt 一致性校验**
- 更新 `agents/planner.py`: `generate_blueprint()` 强制覆写 sourcePrompt（不再判空），LLM 篡改时记录 warning
- 更新 `api/conversation.py`: 新增 `_verify_source_prompt()` 防御性校验函数，在 build/refine/rebuild 共 5 处调用
- 新增 3 项 sourcePrompt 测试（`test_planner.py`）

**Step 4.5.3: Action 命名统一化**
- 重构 `models/conversation.py`: ConversationResponse 从扁平 `action: str` 改为结构化 `mode + action + chat_kind` 三维字段
- 新增 `@computed_field legacy_action` 向下兼容（`chat_smalltalk` / `chat_qa` / `build_workflow` 等旧值）
- 更新 `api/conversation.py`: 13 处 ConversationResponse 构造器适配新字段
- 更新 `tests/test_conversation_models.py`, `test_conversation_api.py`, `test_e2e_conversation.py` 适配新断言

**Step 4.5.4: Executor 数据阶段错误拦截**
- 新增 `errors/__init__.py` + `errors/exceptions.py`: ToolError → DataFetchError → EntityNotFoundError 异常体系
- 更新 `agents/executor.py`: `_resolve_data_contract` 检查 error dict，required binding → DATA_ERROR + DataFetchError，non-required → warning + 跳过
- 新增 DATA_ERROR SSE 事件类型 + error COMPLETE 含 `errorType: "data_error"`
- 新增 3 项 DATA_ERROR 测试 + 1 项异常属性测试（`test_executor.py`）

- 230 项测试全部通过（8 项新增 + 222 项已有）

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
