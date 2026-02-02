# 实施路线图

> 分阶段任务与进度跟踪。每个 Phase 包含 **目标** → **步骤** → **子任务** 三层拆解。

**图例**: ✅ 已完成 | 🔄 进行中 | 🔲 待开始

---

## Phase 0: 基础原型 ✅ 已完成

**目标**: 搭建最小可运行的 AI Agent 服务原型，验证 LLM 工具调用循环可行性。

- [x] Flask 服务框架
- [x] LiteLLM 多模型接入
- [x] Agent 工具循环
- [x] BaseSkill 技能框架
- [x] WebSearch + Memory 技能
- [x] 基础测试

**交付物**: Flask 服务可启动、`/chat` 可对话、工具可被 LLM 调用。

---

## Phase 1: Foundation ✅ 已完成

**目标**: 从 Flask 迁移到 FastAPI 异步架构，建立 Pydantic 数据模型体系和 FastMCP 工具注册框架，为后续多 Agent 系统打下基础。

**前置条件**: Phase 0 完成。

### Step 1.1: Web 框架迁移 (Flask → FastAPI)

> 替换 Web 层，保留业务逻辑不变。

- [x] **1.1.1** 安装 FastAPI + uvicorn + sse-starlette 依赖，更新 `requirements.txt`
- [x] **1.1.2** 创建 `main.py` FastAPI 入口，配置 CORS 中间件
- [x] **1.1.3** 迁移 `/health` 端点 → `api/health.py` (GET `/api/health`)
- [x] **1.1.4** 迁移 `/chat` 端点 → 临时保留为兼容路由（Phase 4 替换）
- [x] **1.1.5** 迁移 `/models` 和 `/skills` 端点
- [x] **1.1.6** 删除 `app.py`（Flask 入口），确认 `python main.py` 可正常启动
- [x] **1.1.7** 更新测试：`test_app.py` 改用 `httpx.AsyncClient` + FastAPI TestClient

> ✅ 验收: `uvicorn main:app` 启动成功，所有原有端点功能不变，测试通过。

### Step 1.2: 配置系统升级

> 用 Pydantic Settings 替代手写 Config 类，支持类型校验和 `.env` 自动加载。

- [x] **1.2.1** 创建 `config/settings.py`：`Settings(BaseSettings)` 定义所有配置项
  - 服务配置: `service_port`, `cors_origins`, `debug`
  - LLM 配置: `default_model`, `executor_model`, API keys
  - 功能配置: `brave_api_key`, `memory_dir`
- [x] **1.2.2** 实现 `get_settings()` 单例函数（`@lru_cache`）
- [x] **1.2.3** 迁移 `config.py` 中的所有配置到新 Settings，删除旧 `config.py`
- [x] **1.2.4** 创建 `.env.example` 模板，列出所有环境变量

> ✅ 验收: `from config.settings import get_settings` 可正常加载 `.env`，类型校验生效。

### Step 1.3: Pydantic 数据模型体系

> 建立 Blueprint 三层数据模型，为 PlannerAgent 结构化输出做准备。

- [x] **1.3.1** 创建 `models/base.py`：`CamelModel` 基类（`alias_generator=to_camel`, `populate_by_name=True`）
- [x] **1.3.2** 创建 `models/blueprint.py`：
  - Layer A: `DataSourceType`, `DataInputSpec`, `DataBinding`, `DataContract`
  - Layer B: `ComputeNodeType`, `ComputeNode`, `ComputeGraph`
  - Layer C: `ComponentType`, `ComponentSlot`, `TabSpec`, `UIComposition`
  - 顶层: `CapabilityLevel`, `Blueprint`
- [x] **1.3.3** 创建 `models/request.py`：API 请求/响应模型
  - `WorkflowGenerateRequest/Response`
  - `PageGenerateRequest`
  - `PageChatRequest/Response`
- [x] **1.3.4** 编写 Blueprint 模型单元测试：验证 camelCase 序列化、嵌套结构、路径引用字段

> ✅ 验收: `Blueprint(**sample_data).model_dump(by_alias=True)` 输出正确的 camelCase JSON。

### Step 1.4: 组件注册表

> 定义 AI 可用的 UI 组件清单，约束 PlannerAgent 的输出范围。

- [x] **1.4.1** 创建 `config/component_registry.py`：定义 6 种组件（kpi_grid, chart, table, markdown, suggestion_list, question_generator）
- [x] **1.4.2** 每种组件包含: `description`, `data_shape`, `props`, `variants`（如适用）
- [x] **1.4.3** 编写辅助函数：`get_registry_description()` → 供 system prompt 注入

> ✅ 验收: `COMPONENT_REGISTRY` 包含 6 个组件定义，辅助函数可输出格式化描述。

### Step 1.5: FastMCP 工具注册

> 用 FastMCP 替代 BaseSkill，实现内部工具注册框架。

- [x] **1.5.1** 安装 fastmcp 依赖
- [x] **1.5.2** 创建 `tools/__init__.py`：实例化 `mcp = FastMCP("insight-ai-tools")`
- [x] **1.5.3** 创建 `tools/data_tools.py`：4 个数据工具（mock 版本）
  - `get_teacher_classes(teacher_id)` → mock 班级列表
  - `get_class_detail(teacher_id, class_id)` → mock 班级详情
  - `get_assignment_submissions(teacher_id, assignment_id)` → mock 提交数据
  - `get_student_grades(teacher_id, student_id)` → mock 学生成绩
- [x] **1.5.4** 创建 `tools/stats_tools.py`：2 个统计工具
  - `calculate_stats(data, metrics)` → 使用 numpy 计算 mean/median/stddev/min/max/percentiles/distribution
  - `compare_performance(group_a, group_b, metrics)` → 两组数据对比
- [x] **1.5.5** 创建 `services/mock_data.py`：集中管理 mock 数据（班级、学生、成绩样本）
- [x] **1.5.6** 编写工具单元测试：验证每个 `@mcp.tool` 的输入输出

> ✅ 验收: `fastmcp dev tools/__init__.py` 交互式测试全部工具可调用、返回正确数据。

### Phase 1 总验收

- [x] `uvicorn main:app` 启动正常
- [x] `/api/health` 返回 `{"status": "healthy"}`
- [x] Blueprint model camelCase 序列化正确
- [x] 6 个 FastMCP 工具可通过 `fastmcp dev` 测试
- [x] `pytest tests/ -v` 全部通过（22 项测试）

---

## Phase 2: PlannerAgent (Blueprint 生成) 🔲

**目标**: 实现 PlannerAgent，接收用户自然语言输入，输出结构化的 Blueprint JSON。这是"用户需求 → 可执行计划"的核心环节。

**前置条件**: Phase 1 完成（FastAPI 运行、Blueprint 模型定义、FastMCP 工具注册、组件注册表）。

### Step 2.1: Agent 基础设施

> 建立 PydanticAI + LiteLLM 的 Agent 通用层。

- [ ] **2.1.1** 安装 `pydantic-ai[litellm]` 依赖
- [ ] **2.1.2** 创建 `agents/provider.py`：
  - `create_model(model_name)` → `LiteLLMModel` 实例
  - `execute_mcp_tool(name, arguments)` → in-process 调用 FastMCP tool
  - `get_mcp_tool_names()` → 获取已注册工具列表
- [ ] **2.1.3** 编写 provider 单元测试：mock LLM 和 MCP 调用

> ✅ 验收: `create_model()` 返回可用的 LiteLLMModel，`execute_mcp_tool()` 可调用已注册工具。

### Step 2.2: Planner System Prompt

> 设计精确的 system prompt，指导 LLM 生成合法的 Blueprint。

- [ ] **2.2.1** 创建 `config/prompts/planner.py`：定义 `PLANNER_SYSTEM_PROMPT`
  - 角色定义：教育数据分析规划师
  - 输出要求：严格遵循 Blueprint 三层结构
  - 约束规则：只能使用注册组件、只能引用已有工具
  - 示例：包含 1-2 个完整 Blueprint 示例
- [ ] **2.2.2** 实现动态注入：组件注册表 + 工具列表自动追加到 prompt

> ✅ 验收: prompt 包含结构指导、组件清单、工具清单、示例。

### Step 2.3: PlannerAgent 实现

> 核心 Agent，接收 prompt 输出 Blueprint。

- [ ] **2.3.1** 创建 `agents/planner.py`：
  - 初始化 `Agent(model, result_type=Blueprint, system_prompt=...)`
  - 动态 system_prompt 注入组件注册表
  - `generate_blueprint(user_prompt, language)` → `Blueprint`
- [ ] **2.3.2** 处理 LLM 输出校验失败的重试逻辑（PydanticAI 内置 retry）
- [ ] **2.3.3** 编写 PlannerAgent 集成测试：给定 prompt，验证输出 Blueprint 结构完整

> ✅ 验收: `generate_blueprint("分析班级英语成绩")` 返回合法 Blueprint，三层结构完整。

### Step 2.4: API 端点

> 暴露 HTTP 接口供前端调用。

- [ ] **2.4.1** 创建 `api/workflow.py`：`POST /api/workflow/generate`
  - 接收 `WorkflowGenerateRequest`
  - 调用 `generate_blueprint()`
  - 返回 `WorkflowGenerateResponse`（含 blueprint JSON）
- [ ] **2.4.2** 错误处理：LLM 超时、输出格式错误、模型不可用
- [ ] **2.4.3** 在 `main.py` 注册 workflow router

> ✅ 验收: `curl -X POST /api/workflow/generate -d '{"user_prompt":"分析班级成绩"}'` 返回完整 Blueprint JSON。

---

## Phase 3: ExecutorAgent (Blueprint 执行, Level 1) 🔲

**目标**: 实现 ExecutorAgent，接收 Blueprint 执行三阶段流水线（Data → Compute → Compose），通过 SSE 流式构建页面。这是"可执行计划 → 结构化页面"的核心环节。

**前置条件**: Phase 2 完成（PlannerAgent 可生成 Blueprint、FastMCP 工具可调用）。

### Step 3.1: 路径引用解析器

> Blueprint 中的 `$context.`, `$data.`, `$compute.` 引用需要在运行时解析。

- [ ] **3.1.1** 实现路径解析函数 `resolve_ref(ref_string, contexts)` → 按前缀从对应上下文取值
- [ ] **3.1.2** 实现批量解析 `resolve_refs(args_dict, *contexts)` → 递归解析 dict 中所有 `$` 引用
- [ ] **3.1.3** 处理边界情况：路径不存在返回 `None`，嵌套点号路径（如 `$data.submissions.scores`）
- [ ] **3.1.4** 编写解析器单元测试

> ✅ 验收: `resolve_ref("$data.submissions.scores", {"data": {"submissions": {"scores": [...]}}})` 正确返回。

### Step 3.2: 三阶段执行引擎

> ExecutorAgent 核心逻辑。

- [ ] **3.2.1** 创建 `agents/executor.py`：`ExecutorAgent` 类
- [ ] **3.2.2** **Phase A — Data Contract 解析**：
  - 拓扑排序 `DataBinding`（按 `depends_on`）
  - 按序调用 `execute_mcp_tool()` 获取数据
  - 构建 `data_context` 字典
- [ ] **3.2.3** **Phase B — Compute Graph 执行**：
  - 分离 TOOL 节点和 AI 节点
  - TOOL 节点：解析参数引用 → 调用工具 → 存入 `compute_results`
  - AI 节点：暂跳过（Phase C 中由 AI 统一生成）
- [ ] **3.2.4** **Phase C — AI Compose**：
  - 构建 compose prompt（注入 data_context + compute_results + UIComposition 布局要求）
  - 使用 PydanticAI `agent.iter()` 流式生成
  - 产出 SSE 事件序列

> ✅ 验收: 给定一个 Blueprint + mock 数据，三阶段顺序执行，输出完整的事件序列。

### Step 3.3: SSE 流式端点

> 将执行引擎的事件流通过 SSE 推送给前端。

- [ ] **3.3.1** 创建 `api/page.py`：`POST /api/page/generate`
  - 接收 `PageGenerateRequest`
  - 调用 `ExecutorAgent.execute_blueprint_stream()`
  - 使用 `sse-starlette` 的 `EventSourceResponse` 包装
- [ ] **3.3.2** 定义 SSE 事件类型：`PHASE`, `TOOL_CALL`, `TOOL_RESULT`, `MESSAGE`, `COMPLETE`, `ERROR`
- [ ] **3.3.3** 实现错误处理：工具调用失败、LLM 超时 → `ERROR` 事件
- [ ] **3.3.4** 在 `main.py` 注册 page router

> ✅ 验收: `curl -N -X POST /api/page/generate` 收到 SSE 事件流，最终 `COMPLETE` 事件包含完整页面结构。

### Step 3.4: 端到端验证

> 串联 Phase 2 + Phase 3，完成完整流程。

- [ ] **3.4.1** 编写端到端测试：`user_prompt` → `generate_blueprint()` → `execute_blueprint_stream()` → SSE events
- [ ] **3.4.2** 验证页面内容：KPI 数值来自 tool 计算（可信），叙事文本来自 AI（基于数据）
- [ ] **3.4.3** 验证 SSE 事件格式符合 [sse-protocol.md](api/sse-protocol.md) 规范

> ✅ 验收: 完整流程可跑通，SSE 输出符合协议，页面结构匹配 Blueprint 的 UIComposition。

---

## Phase 4: Router + Chat 🔲

**目标**: 实现 RouterAgent（意图分类）和 ChatAgent（页面追问对话），完成多 Agent 协作闭环。用户可以在页面生成后继续追问、修改或重新生成。

**前置条件**: Phase 3 完成（ExecutorAgent 可执行 Blueprint 并 SSE 输出页面）。

### Step 4.1: RouterAgent (意图分类)

> 判断用户追问属于哪种类型，路由到对应处理流程。

- [ ] **4.1.1** 创建 `config/prompts/router.py`：意图分类 system prompt
  - 定义三种意图：`workflow_rebuild` / `page_refine` / `data_chat`
  - 包含分类示例和判断规则
- [ ] **4.1.2** 创建 `agents/router.py`：`RouterAgent`
  - 输入：用户消息 + 当前 workflow 名称 + 页面摘要
  - 输出：`{ intent, confidence }`
- [ ] **4.1.3** 创建 `api/intent.py`：`POST /api/intent/classify`
- [ ] **4.1.4** 编写意图分类测试：覆盖三种意图的典型 case

> ✅ 验收: 给定追问消息，正确分类意图并返回 confidence 分数。

### Step 4.2: ChatAgent (页面对话)

> 基于已有页面上下文回答用户追问。

- [ ] **4.2.1** 创建 `config/prompts/chat.py`：对话 system prompt
- [ ] **4.2.2** 创建 `agents/chat.py`：`ChatAgent`
  - 输入：用户消息 + 页面上下文（摘要 + 关键数据）
  - 输出：Markdown 格式文本回复
- [ ] **4.2.3** 在 `api/page.py` 添加 `POST /api/page/chat` 端点
- [ ] **4.2.4** 编写对话测试：验证回复与页面上下文相关

> ✅ 验收: 给定页面上下文和追问，返回有意义的回复，不产生幻觉数据。

### Step 4.3: CamelCase 输出与多 Agent 联调

> 确保所有 API 输出统一 camelCase，多 Agent 协作流程跑通。

- [ ] **4.3.1** 检查所有 Response model 继承 `CamelModel`，序列化 `by_alias=True`
- [ ] **4.3.2** 联调测试：生成页面 → 追问 → Router 分类 → 对应 Agent 处理
- [ ] **4.3.3** 补充 API 错误响应的统一格式

> ✅ 验收: 完整的"生成 → 追问 → 路由 → 响应"闭环可跑通，所有输出 camelCase。

---

## Phase 5: Java 后端对接 🔲

**目标**: 将 mock 数据替换为真实的 Java 后端 API 调用，实现数据从教务系统到 AI 分析的完整链路。

**前置条件**: Phase 4 完成（多 Agent 系统功能完整，mock 数据跑通）。

### Step 5.1: HTTP 客户端封装

> 建立与 Java 后端通信的基础设施。

- [ ] **5.1.1** 安装 httpx 依赖
- [ ] **5.1.2** 创建 `services/java_client.py`：
  - 封装 `httpx.AsyncClient`，配置 base_url / timeout / headers
  - 通用请求方法：`get()`, `post()`，统一错误处理
- [ ] **5.1.3** 在 Settings 中添加 Java 后端配置：`java_backend_url`, `java_api_timeout`
- [ ] **5.1.4** 实现连接池管理和优雅关闭（FastAPI lifespan）

> ✅ 验收: `java_client.get("/dify/teacher/t-001/classes/me")` 可成功调用（或在 Java 不可用时优雅降级）。

### Step 5.2: 数据工具切换

> 将 mock 数据工具替换为调用 Java API 的真实版本。

- [ ] **5.2.1** 重构 `tools/data_tools.py`：每个工具内部调用 `java_client`
  - `get_teacher_classes` → `GET /dify/teacher/{id}/classes/me`
  - `get_class_detail` → `GET /dify/teacher/{id}/classes/{classId}`
  - `get_assignment_submissions` → `GET /dify/teacher/{id}/classes/{classId}/assignments` + `GET .../submissions`
  - `get_student_grades` → `GET /dify/teacher/{id}/submissions/students/{studentId}`
- [ ] **5.2.2** 数据格式映射：Java API 响应 → 工具输出格式（保持工具接口不变）
- [ ] **5.2.3** 保留 mock fallback：当 Java 不可用时降级到 mock 数据（通过配置开关）

> ✅ 验收: 连接 Java 后端时使用真实数据，断连时降级到 mock，工具对外接口不变。

### Step 5.3: 错误处理与健壮性

> 确保外部依赖不稳定时系统仍可用。

- [ ] **5.3.1** 实现重试策略：网络超时、5xx 错误自动重试（指数退避，最多 3 次）
- [ ] **5.3.2** 实现熔断/降级：连续失败 N 次后自动切换到 mock 数据
- [ ] **5.3.3** 添加请求日志：记录 Java API 调用耗时、状态码
- [ ] **5.3.4** 端到端测试：模拟 Java 服务超时/500 → 验证降级行为

> ✅ 验收: Java 后端宕机时，系统自动降级到 mock 数据，不影响用户使用。

---

## Phase 6: 前端集成 + Level 2 🔲

**目标**: 与 Next.js 前端对接，完成 Level 2 能力（AI 填充组件内容），进行端到端测试并上线。

**前置条件**: Phase 5 完成（真实数据链路打通）。

### Step 6.1: Next.js Proxy 对接

> 前端通过 API Routes 代理所有 AI 请求，避免跨域和密钥暴露。

- [ ] **6.1.1** 协调前端创建 proxy routes（参见 [前端集成文档](integration/frontend-integration.md)）：
  - `/api/ai/workflow-generate` → `POST /api/workflow/generate`
  - `/api/ai/page-generate` → `POST /api/page/generate` (SSE passthrough)
  - `/api/ai/page-chat` → `POST /api/page/chat`
  - `/api/ai/classify-intent` → `POST /api/intent/classify`
- [ ] **6.1.2** 确认字段映射：前端 camelCase ↔ Python snake_case（由 CamelModel 自动处理）
- [ ] **6.1.3** 联调：前端 → Proxy → Python Service → 真实数据，全链路跑通

> ✅ 验收: 前端页面可发起请求，SSE 流式显示页面构建过程。

### Step 6.2: Level 2 — AI 内容插槽

> 让 AI 不仅选择和排列组件，还能填充组件内部内容。

- [ ] **6.2.1** 在 ExecutorAgent 的 Compose 阶段支持 `ai_content_slot=true` 的 ComponentSlot
- [ ] **6.2.2** AI 生成内容类型：
  - `markdown` blocks → AI 撰写叙事分析文本
  - `suggestion_list` → AI 生成教学建议条目
  - `table` cells → AI 填写分析性文字列
- [ ] **6.2.3** 更新 SSE 事件：AI 填充内容作为增量 `MESSAGE` 事件推送
- [ ] **6.2.4** 前端适配：PageRenderer 处理 `aiContentSlot` 标记的组件

> ✅ 验收: 页面中 markdown / suggestion_list 等组件内容由 AI 实时生成并流式推送。

### Step 6.3: E2E 测试与上线

> 全链路质量保障。

- [ ] **6.3.1** 编写 E2E 测试用例：
  - 正常流程：输入 prompt → 生成 Blueprint → 构建页面 → 追问 → 对话
  - 异常流程：Java 超时降级、LLM 不可用、无效 prompt
- [ ] **6.3.2** 性能基线：记录 Blueprint 生成耗时、页面构建耗时、SSE 首字节时间
- [ ] **6.3.3** 部署配置：Docker / 环境变量 / 健康检查
- [ ] **6.3.4** 上线 checklist：
  - [ ] 所有测试通过
  - [ ] API 文档（FastAPI Swagger）可访问
  - [ ] 日志和监控就绪
  - [ ] Java 后端连接配置正确

> ✅ 验收: 生产环境部署成功，教师可通过前端完成完整的"提问 → 页面 → 追问"流程。

---

## 里程碑总览

| 里程碑 | Phase | 核心交付 |
|--------|-------|---------|
| **M0: 原型验证** | 0 ✅ | Flask + LLM 工具调用可运行 |
| **M1: 技术基座** | 1 ✅ | FastAPI + Pydantic Models + FastMCP Tools |
| **M2: 智能规划** | 2 | 用户 prompt → 结构化 Blueprint |
| **M3: 页面构建** | 3 | Blueprint → SSE 流式页面 |
| **M4: 多 Agent 闭环** | 4 | 构建 + 追问 + 路由，完整交互循环 |
| **M5: 真实数据** | 5 | Java 后端对接，mock → 真实教务数据 |
| **M6: 产品上线** | 6 | 前端集成 + Level 2 + 部署上线 |
