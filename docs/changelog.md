# 变更日志

> 按日期记录所有变更。

---

## 2026-02-09 — 架构重构: AI 原生单栈重构方案

**文档**: `docs/plans/2026-02-09-ai-native-rewrite.md`

从"代码控制 AI"重构为"AI 控制代码"。删除所有硬编码路由/阈值/正则/DSL/手工 tool loop，改用 LLM 原生 tool calling 自主编排。

**架构变更**
- 新增 `agents/native_agent.py` — NativeAgent 单 runtime，每轮按上下文选 toolset 子集
- 新增 `tools/registry.py` — 单一工具注册源，5 个 toolset 分包 (base_data/analysis/generation/artifact_ops/platform)
- 重写 `api/conversation.py` — 薄网关 (~100 行)，不做业务决策
- 新增 `services/stream_adapter.py` — PydanticAI stream → Data Stream Protocol 适配
- 新增 `config/prompts/native_agent.py` — NativeAgent system prompt

**删除的模块**
- `agents/router.py` (RouterAgent) — LLM 自主选 tool
- `agents/executor.py` (ExecutorAgent) — tool calling 取代三阶段流水线
- `agents/resolver.py` (Path Resolver) — tool 输出直接入 LLM context
- `agents/patch_agent.py` (PatchAgent) — `patch_artifact` tool 取代
- `agents/chat_agent.py` (ChatAgent) — NativeAgent 取代
- `services/entity_resolver.py` — `resolve_entity` tool 取代
- `config/prompts/router.py` — 无需路由 prompt

**新概念**
- Artifact 统一模型: artifact_type (业务) + content_format (技术) + resources (资源索引)
- ToolResult envelope: 生成/RAG/写操作 tool 的结构化返回
- Golden Conversations: 行为级回归测试（20-30 条固定测试集）

**前端影响**: SSE 事件格式 (Data Stream Protocol) 不变，前端零改动。

**文档更新**
- 更新 `CLAUDE.md` (根目录 + AI Agent 模块) — 新架构方向
- 重写 `docs/architecture/overview.md` — AI 原生架构全景
- 重写 `docs/architecture/agents.md` — NativeAgent 设计
- 更新 `docs/api/current-api.md` — 新 API 端点
- 更新 `docs/guides/adding-skills.md` — registry 单一注册方式
- 更新 `docs/README.md` — 导航更新
- 更新 `docs/roadmap.md` — 新增 AI 原生重构进度
- 更新 `docs/convergence/README.md` — Phase 3+4 由 AI 原生重构取代
- 更新 `docs/integration/frontend-integration.md` — 新端点
- 更新 `docs/studio-v1/architecture/07-agent-convergence-plan.md` — 前向引用
- 更新 `docs/studio-v1/architecture/06-current-ai-runtime-flow.md` — 标记为旧架构

---

## 2026-02-04 — 文档更新: Phase 6 前端集成规范完善

更新 `docs/integration/frontend-integration.md`，补充 Phase 6 (SSE Block 事件流 + Patch 机制) 的完整 API 契约。

**版本升级**
- 文档版本从 0.5.1 → 0.6.0
- 项目版本标识从 Phase 5 → Phase 6 完成

**新增端点**
- `/api/page/patch` (POST, SSE): Patch 机制增量修改端点

**新增 SSE 事件**
- `BLOCK_START`: AI 内容块开始生成
- `SLOT_DELTA`: 流式内容增量（打字机效果）
- `BLOCK_COMPLETE`: AI 内容块完成
- `DATA_ERROR`: 数据获取错误（Phase 4.5）

**新增数据模型**
- `PatchPlan`: scope (patch_layout/patch_compose/full_rebuild) + instructions + affectedBlockIds
- `PatchInstruction`: type (update_props/reorder/add_block/remove_block/recompose) + targetBlockId + changes
- `PagePatchRequest`: blueprint + page + patchPlan + dataContext + computeResults
- `ResolvedEntity`: entityType + entityId + displayName (Phase 4.5)

**ConversationResponse 字段更新**
- 新增 `mode`: "entry" | "followup"
- 新增 `action`: "chat" | "build" | "clarify" | "refine" | "rebuild"
- 新增 `chatKind`: "smalltalk" | "qa" | "page" | null
- 新增 `patchPlan`: PatchPlan | null (refine 时可能有值)
- 新增 `resolvedEntities`: ResolvedEntity[] | null
- `legacyAction` 改为向下兼容字段

**前端处理逻辑变更**
- refine 分流：有 `patchPlan` → `/api/page/patch`，无则 → `/api/page/generate`
- Patch 模式复用缓存数据 (dataContext, computeResults)，避免重新获取

**TypeScript 类型补充**
- SSEEvent 新增 BLOCK_START/SLOT_DELTA/BLOCK_COMPLETE/DATA_ERROR
- ConversationResponse 完整结构化字段
- PatchPlan, PatchInstruction, RefineScope, PatchType
- ResolvedEntity

---

## 2026-02-04 — Phase 7 测试完成: 测试基础设施 + Live 测试

完成 Phase 7 全量测试，新增 live-test skill 和 Live 集成测试。

**测试工具**
- 新增 `.claude/skills/live-test/SKILL.md`: 真实后端数据 + AI 集成测试 skill
- 更新 `pytest.ini`: 新增 live/live_llm/integration/e2e 标记

**Live 集成测试 (`tests/test_live_integration.py`)**
- E1-E6: Phase 7 RAG/Knowledge/Rubric 服务测试 (无需 LLM)
- F1-F4: Question Pipeline 测试 (需要 LLM API Key)
- G1: Assessment Tools 弱项分析测试

**文档**
- 新增 `docs/testing/phase7-test-report.md`: Phase 7 测试报告 (445 项测试全部通过)
- 更新 `docs/testing/README.md`: 新增 Phase 7 Use Cases 索引

**测试结果**
- 单元测试: 438 项通过
- Phase 7 专项测试: 79 项通过
- Live 集成测试 (非 LLM): 7 项通过
- 总计: 445 项测试，100% 通过率

---

## 2026-02-03 — Phase 7 P1 完成: HKDSE Math, Chinese, ICT 知识库

基于官方 HKDSE 课纲，补充数学、中文、ICT 的知识点和评分标准，完善 RAG 向量库。

**知识点文件 (data/knowledge_points/)**
- 新增 `dse-math.json`: 29 个数学知识点（代数、几何、统计、M1 微积分）
- 新增 `dse-chinese.json`: 22 个中文知识点（阅读、写作、聆听说话、语文基础）
- 新增 `dse-ict.json`: 30 个 ICT 知识点（信息处理、计算机系统、网络、编程、社会影响）

**评分标准文件 (data/rubrics/)**
- 新增 `dse-math-problem-solving.json`: 数学解题评分（理解/过程/表达）
- 新增 `dse-math-multiple-choice.json`: 数学选择题质量标准
- 新增 `dse-chi-writing-essay.json`: 中文写作评分（内容/表达/结构）
- 新增 `dse-chi-reading-comprehension.json`: 中文阅读理解评分
- 新增 `dse-ict-programming.json`: ICT 编程评分（逻辑/代码质量/输出）
- 新增 `dse-ict-database.json`: ICT 数据库评分（SQL/查询逻辑/设计）

**服务更新**
- 更新 `services/knowledge_service.py`: SUBJECT_CODE_MAP 新增 ICT；ERROR_TAG_MAPPING 新增 Math/Chinese/ICT 错误标签映射

**测试**
- 新增 `tests/test_rag_question_generation.py`: 31 项 RAG + 知识点 + Rubric 测试
- 新增 `scripts/test_question_generation.py`: 手动测试脚本

**数据来源**
- [HKEAA Mathematics 课纲](https://www.hkeaa.edu.hk/DocLibrary/HKDSE/Subject_Information/math/2024hkdse-e-math.pdf)
- [HKEAA ICT 课纲](https://www.hkeaa.edu.hk/DocLibrary/HKDSE/Subject_Information/ict/2024hkdse-e-ict.pdf)
- [教育局中國語文課程指引](https://www.edb.gov.hk/attachment/tc/curriculum-development/kla/chi-edu/CHI_LANG_CAGuide_2021.pdf)

---

## 2026-02-03 — Phase 6.5 完成: E2E 测试 + Phase 6 全量验收

完成 Phase 6 最后一步，编写全链路 E2E 测试，验证 BLOCK 事件、Patch 机制和错误处理。

**Step 6.5: E2E 测试**
- 新增 `tests/test_e2e_phase6.py`: 8 项 E2E 测试
  - `test_e2e_full_lifecycle_with_block_events()` — 完整生命周期 + BLOCK 事件验证
  - `test_e2e_refine_patch_layout()` — 布局 patch (无 LLM 调用)
  - `test_e2e_refine_patch_compose()` — 内容 patch (只重生成 AI blocks)
  - `test_e2e_refine_full_rebuild()` — 完整重建 (新 blueprint)
  - `test_e2e_java_timeout_with_block_events()` — Java 超时降级 + BLOCK 事件
  - `test_e2e_llm_failure_error_complete()` — LLM 失败 → error COMPLETE
  - `test_e2e_nonexistent_entity_data_error()` — 实体不存在 → DATA_ERROR
  - `test_e2e_http_page_patch_endpoint()` — HTTP /api/page/patch SSE 端点

**Phase 6 总验收**
- 320 项测试全部通过（8 项新增 + 312 项已有）
- Phase 6 所有功能完成: SSE 事件模型、Per-Block AI、Patch 机制、E2E 测试

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

## 2026-02-06 - Dify submissions now include guest records

- Java Dify endpoint `/dify/teacher/{teacherId}/submissions/assignments/{assignmentId}` now returns merged student + guest submissions.
- Added source marker `type` (`student`/`guest`) in each record.
- Adapter update: `adapters/submission_adapter.py` now falls back to `guestName` when `studentName` is absent.
