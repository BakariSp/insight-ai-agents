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

## Phase 2: PlannerAgent (Blueprint 生成) ✅ 已完成

**目标**: 实现 PlannerAgent，接收用户自然语言输入，输出结构化的 Blueprint JSON。这是"用户需求 → 可执行计划"的核心环节。

**前置条件**: Phase 1 完成（FastAPI 运行、Blueprint 模型定义、FastMCP 工具注册、组件注册表）。

### Step 2.1: Agent 基础设施

> 建立 PydanticAI + LiteLLM 的 Agent 通用层。

- [x] **2.1.1** 安装 `pydantic-ai` 依赖，更新 `requirements.txt`
- [x] **2.1.2** 创建 `agents/provider.py`：
  - `create_model(model_name)` → `"litellm:<model>"` 标识符（PydanticAI v1.x 格式）
  - `execute_mcp_tool(name, arguments)` → in-process 调用 TOOL_REGISTRY 中的函数
  - `get_mcp_tool_names()` → 获取已注册工具列表
  - `get_mcp_tool_descriptions()` → 获取工具名 + 描述（供 prompt 注入）
- [x] **2.1.3** 在 `tools/__init__.py` 新增 `TOOL_REGISTRY` dict + `get_tool_descriptions()` 辅助函数
- [x] **2.1.4** 编写 provider 单元测试（7 项）：model 创建、工具名列表、工具描述、工具执行、工具未找到

> ✅ 验收: `create_model()` 返回可用的 litellm 模型标识，`execute_mcp_tool()` 可调用已注册工具。

### Step 2.2: Planner System Prompt

> 设计精确的 system prompt，指导 LLM 生成合法的 Blueprint。

- [x] **2.2.1** 创建 `config/prompts/planner.py`：定义 `PLANNER_SYSTEM_PROMPT`
  - 角色定义：教育数据分析规划师
  - 输出要求：严格遵循 Blueprint 三层结构 + 路径引用语法
  - 约束规则：只能使用注册组件、只能引用已有工具（10 条规则）
  - 示例：包含 1 个完整 Blueprint JSON 示例
- [x] **2.2.2** 实现 `build_planner_prompt(language)` 动态注入：组件注册表 + 工具列表 + 语言指令

> ✅ 验收: prompt 包含结构指导、组件清单、工具清单、示例，约 8000 字符。

### Step 2.3: PlannerAgent 实现

> 核心 Agent，接收 prompt 输出 Blueprint。

- [x] **2.3.1** 创建 `agents/planner.py`：
  - 初始化 `Agent(model, output_type=Blueprint, system_prompt=...)`（PydanticAI v1.x API）
  - 通过 `build_planner_prompt()` 注入完整 system prompt（含组件注册表 + 工具列表）
  - `generate_blueprint(user_prompt, language, model)` → `Blueprint`
- [x] **2.3.2** 处理 LLM 输出校验失败的重试逻辑（PydanticAI 内置 `retries=2`）
- [x] **2.3.3** 自动填充元数据（`source_prompt`, `created_at`）
- [x] **2.3.4** 编写 PlannerAgent 集成测试（5 项）：使用 PydanticAI `TestModel` 验证结构、三层、元数据、camelCase、语言

> ✅ 验收: `generate_blueprint("分析班级英语成绩")` 返回合法 Blueprint，三层结构完整。

### Step 2.4: API 端点

> 暴露 HTTP 接口供前端调用。

- [x] **2.4.1** 创建 `api/workflow.py`：`POST /api/workflow/generate`
  - 接收 `WorkflowGenerateRequest`
  - 调用 `generate_blueprint()`
  - 返回 `WorkflowGenerateResponse`（含 blueprint JSON）
- [x] **2.4.2** 错误处理：LLM 异常统一返回 502 + 错误详情
- [x] **2.4.3** 在 `main.py` 注册 workflow router
- [x] **2.4.4** 编写 API 测试（3 项）：成功生成（mock LLM）、缺少参数 422、LLM 失败 502

> ✅ 验收: `curl -X POST /api/workflow/generate -d '{"userPrompt":"分析班级成绩"}'` 返回完整 Blueprint JSON。

### Phase 2 总验收

- [x] `agents/provider.py` — create_model / execute_mcp_tool / get_mcp_tool_names 全部可用
- [x] `config/prompts/planner.py` — system prompt 含结构指导 + 组件清单 + 工具清单 + 示例
- [x] `agents/planner.py` — PydanticAI Agent + output_type=Blueprint + retries=2
- [x] `api/workflow.py` — POST /api/workflow/generate 端点 + 错误处理
- [x] `pytest tests/ -v` 全部通过（52 项测试：15 llm_config + 7 provider + 5 planner + 7 API + 5 models + 13 tools）

---

## Phase 3: ExecutorAgent (Blueprint 执行, Level 1) ✅ 已完成

**目标**: 实现 ExecutorAgent，接收 Blueprint 执行三阶段流水线（Data → Compute → Compose），通过 SSE 流式构建页面。这是"可执行计划 → 结构化页面"的核心环节。

**前置条件**: Phase 2 完成（PlannerAgent 可生成 Blueprint、FastMCP 工具可调用）。

### Step 3.1: 路径引用解析器

> Blueprint 中的 `$context.`, `$data.`, `$compute.` 引用需要在运行时解析。

- [x] **3.1.1** 实现路径解析函数 `resolve_ref(ref_string, contexts)` → 按前缀从对应上下文取值
- [x] **3.1.2** 实现批量解析 `resolve_refs(args_dict, *contexts)` → 递归解析 dict 中所有 `$` 引用
- [x] **3.1.3** 处理边界情况：路径不存在返回 `None`，嵌套点号路径（如 `$data.submissions.scores`）
- [x] **3.1.4** 编写解析器单元测试

> ✅ 验收: `resolve_ref("$data.submissions.scores", {"data": {"submissions": {"scores": [...]}}})` 正确返回。

### Step 3.2: 三阶段执行引擎

> ExecutorAgent 核心逻辑。

- [x] **3.2.1** 创建 `agents/executor.py`：`ExecutorAgent` 类
- [x] **3.2.2** **Phase A — Data Contract 解析**：
  - 拓扑排序 `DataBinding`（按 `depends_on`）
  - 按序调用 `execute_mcp_tool()` 获取数据
  - 构建 `data_context` 字典
- [x] **3.2.3** **Phase B — Compute Graph 执行**：
  - 分离 TOOL 节点和 AI 节点
  - TOOL 节点：解析参数引用 → 调用工具 → 存入 `compute_results`
  - AI 节点：暂跳过（Phase C 中由 AI 统一生成）
- [x] **3.2.4** **Phase C — AI Compose**：
  - 构建 compose prompt（注入 data_context + compute_results + UIComposition 布局要求）
  - 确定性 block 构建（kpi_grid, chart, table）+ AI 叙事生成
  - 产出 SSE 事件序列

> ✅ 验收: 给定一个 Blueprint + mock 数据，三阶段顺序执行，输出完整的事件序列。

### Step 3.3: SSE 流式端点

> 将执行引擎的事件流通过 SSE 推送给前端。

- [x] **3.3.1** 创建 `api/page.py`：`POST /api/page/generate`
  - 接收 `PageGenerateRequest`
  - 调用 `ExecutorAgent.execute_blueprint_stream()`
  - 使用 `sse-starlette` 的 `EventSourceResponse` 包装
- [x] **3.3.2** 定义 SSE 事件类型：`PHASE`, `TOOL_CALL`, `TOOL_RESULT`, `MESSAGE`, `COMPLETE`, `ERROR`
- [x] **3.3.3** 实现错误处理：工具调用失败、LLM 超时 → error COMPLETE 事件
- [x] **3.3.4** 在 `main.py` 注册 page router

> ✅ 验收: `curl -N -X POST /api/page/generate` 收到 SSE 事件流，最终 `COMPLETE` 事件包含完整页面结构。

### Step 3.4: 端到端验证

> 串联 Phase 2 + Phase 3，完成完整流程。

- [x] **3.4.1** 编写端到端测试：`user_prompt` → `generate_blueprint()` → `execute_blueprint_stream()` → SSE events
- [x] **3.4.2** 验证页面内容：KPI 数值来自 tool 计算（可信），叙事文本来自 AI（基于数据）
- [x] **3.4.3** 验证 SSE 事件格式符合 [sse-protocol.md](api/sse-protocol.md) 规范

> ✅ 验收: 完整流程可跑通，SSE 输出符合协议，页面结构匹配 Blueprint 的 UIComposition。

### Phase 3 总验收

- [x] `agents/resolver.py` — resolve_ref / resolve_refs 解析 4 种前缀引用
- [x] `agents/executor.py` — ExecutorAgent 三阶段执行引擎 + 确定性 block 构建 + AI 叙事
- [x] `config/prompts/executor.py` — compose prompt 构建器
- [x] `api/page.py` — POST /api/page/generate SSE 端点 + EventSourceResponse
- [x] `pytest tests/ -v` 全部通过（92 项测试：16 resolver + 16 executor + 10 API + 5 E2E + 45 existing）

---

## Phase 4: 统一会话网关 (Intent Router + Conversation API) ✅ 已完成

**目标**: 引入中心意图路由器，统一初始入口和追问入口为 `POST /api/conversation`。后端内部完成意图分类 + 置信度路由 + 交互式反问 + 执行调度。前端只需发一次请求、看 `action` 字段、做对应渲染。

**前置条件**: Phase 3 完成（ExecutorAgent 可执行 Blueprint 并 SSE 输出页面）。

**核心设计变更**:

```
旧方案（Phase 3 现状）:
  用户输入 → 前端直调 /api/workflow/generate → 无条件生成 Blueprint
  问题: 无意图检测, 闲聊/无关请求也被硬编为 Blueprint, 前端承担路由判断

新方案:
  用户输入 → 前端调 /api/conversation → RouterAgent 意图分类 → 按 action 路由
  优点: 单一入口, 置信度控制, 交互式反问, 前端零路由逻辑
```

**意图分类体系:**

| 意图 | 触发条件 | 示例 |
|------|---------|------|
| `chat_smalltalk` | 闲聊/寒暄/无明确任务 | "天气怎么样"、"你好"、"谢谢" |
| `chat_qa` | 问答/咨询（不涉及数据分析） | "怎么用这个功能"、"解释一下 KPI" |
| `build_workflow` | 明确要生成分析页面/报告/题目 | "分析 1A 班英语成绩"、"给 1B 出一套阅读题" |
| `clarify` | 看起来像任务但缺关键参数 | "分析英语表现"（没说哪个班/哪个时间段） |

**置信度路由策略:**

| confidence | 路由行为 |
|------------|---------|
| `≥ 0.7` | 直接执行 `build_workflow` |
| `0.4 ~ 0.7` | 走 `clarify`，返回交互式反问 |
| `< 0.4` | 当 `chat` 处理 |

**追问模式** (有 blueprint/pageContext 上下文时):

| 意图 | 触发条件 | 示例 |
|------|---------|------|
| `chat` | 针对已有页面数据的提问 | "哪些学生需要关注？" |
| `refine` | 微调当前页面 | "把图表颜色换成蓝色" |
| `rebuild` | 结构性重建 | "加一个语法分析板块" |

### Step 4.1: 意图模型与 Clarify 交互模型

> 定义 Router 输出结构和交互式反问的数据契约。

- [x] **4.1.1** 在 `models/` 下创建 `conversation.py`：
  - `IntentType` 枚举：`chat_smalltalk` / `chat_qa` / `build_workflow` / `clarify`
  - `FollowupIntentType` 枚举：`chat` / `refine` / `rebuild`
  - `RouterResult(CamelModel)`：
    ```python
    intent: IntentType
    confidence: float           # 0~1
    should_build: bool          # 便于后续开关策略
    clarifying_question: str | None
    route_hint: str | None      # 如 "needClassId", "needTimeRange"
    ```
- [x] **4.1.2** 定义 Clarify 交互模型：
  - `ClarifyChoice(CamelModel)`：`label`, `value`, `description`
  - `ClarifyOptions(CamelModel)`：
    ```python
    type: Literal["single_select", "multi_select"]
    choices: list[ClarifyChoice]
    allow_custom_input: bool = True  # 前端渲染 "其他" 自由输入框
    ```
- [x] **4.1.3** 定义统一请求/响应模型：
  - `ConversationRequest(CamelModel)`：
    ```python
    message: str                        # 用户消息
    language: str = "en"
    teacher_id: str = ""
    context: dict | None = None         # 运行时上下文
    blueprint: Blueprint | None = None  # 有值 → 追问模式
    page_context: dict | None = None    # 页面摘要
    conversation_id: str | None = None  # 多轮会话 ID
    ```
  - `ConversationResponse(CamelModel)`：
    ```python
    action: str                             # 见 action 路由表
    chat_response: str | None = None        # chat 回复 (Markdown)
    blueprint: Blueprint | None = None      # build/refine/rebuild 时有值
    clarify_options: ClarifyOptions | None  # clarify 时有值
    conversation_id: str | None = None
    ```
- [x] **4.1.4** 编写模型单元测试：验证 camelCase 序列化、枚举值、可选字段

> ✅ 验收: `ConversationResponse` 支持 6 种 action（chat_smalltalk/chat_qa/build_workflow/clarify/refine/rebuild），clarify 响应包含结构化选项。

### Step 4.2: RouterAgent (统一意图分类器)

> RouterAgent 是内部组件，不对外暴露端点。根据是否有 blueprint 上下文自动切换初始/追问模式。

- [x] **4.2.1** 创建 `config/prompts/router.py`：Router system prompt
  - **初始模式** prompt：4 种意图分类规则 + 置信度评估指引 + 分类示例
  - **追问模式** prompt：3 种意图分类规则 + 页面上下文注入
  - 输入模板：用户消息 + (可选) blueprint 名称 + 页面摘要
- [x] **4.2.2** 创建 `agents/router.py`：`RouterAgent`
  - 初始化 PydanticAI `Agent(output_type=RouterResult)`
  - `classify_intent(message, blueprint?, page_context?)` → `RouterResult`
  - 自动检测模式：`blueprint is None` → 初始模式，否则 → 追问模式
  - 置信度路由逻辑：
    ```
    if confidence >= 0.7 and intent == build_workflow → 直接 build
    if 0.4 <= confidence < 0.7 → 强制 clarify（即使 LLM 说 build）
    if confidence < 0.4 → 当 chat 处理
    ```
- [x] **4.2.3** 编写 Router 单元测试（使用 PydanticAI TestModel）：
  - 初始模式：覆盖 4 种意图 + 置信度边界
  - 追问模式：覆盖 3 种意图
  - 模式自动切换测试

> ✅ 验收: `classify_intent("天气怎么样")` → `chat_smalltalk, confidence<0.4`；`classify_intent("分析 1A 班英语成绩")` → `build_workflow, confidence≥0.7`；`classify_intent("分析英语表现")` → `clarify, confidence~0.5`。

### Step 4.3: ChatAgent (闲聊 + 知识问答)

> 处理 `chat_smalltalk` 和 `chat_qa` 意图，作为教育场景的友好对话入口。

- [x] **4.3.1** 创建 `config/prompts/chat.py`：Chat system prompt
  - 角色：教育数据分析助手
  - `chat_smalltalk`：友好回复，引导用户使用分析功能
  - `chat_qa`：回答教育相关问题、功能使用指导
  - 约束：不编造数据，不生成 Blueprint 结构
- [x] **4.3.2** 创建 `agents/chat.py`：`ChatAgent`
  - `generate_response(message, intent_type, language)` → `str`（Markdown）
  - 轻量级 Agent，不需要工具调用
- [x] **4.3.3** 编写 ChatAgent 测试：闲聊回复、QA 回复、不泄露内部结构

> ✅ 验收: `generate_response("你好", "chat_smalltalk")` → 友好问候 + 功能引导；`generate_response("KPI 是什么", "chat_qa")` → 教育相关解释。

### Step 4.4: Clarify 交互机制

> 当 Router 置信度不足时，生成结构化的反问选项，前端渲染为可交互 UI。

- [x] **4.4.1** 在 RouterAgent 中扩展 clarify 逻辑：
  - 当 `intent == clarify` 时，额外生成 `ClarifyOptions`
  - Router prompt 指导 LLM 输出 `clarifying_question` + `route_hint`
- [x] **4.4.2** 创建 `services/clarify_builder.py`：
  - `build_clarify_options(route_hint, teacher_id)` → `ClarifyOptions`
  - 根据 `route_hint` 调用对应工具获取选项数据：
    - `"needClassId"` → 调用 `get_teacher_classes()` → 生成班级单选列表
    - `"needTimeRange"` → 生成预设时间范围选项（本周/本月/本学期）
    - `"needAssignment"` → 调用工具获取作业列表 → 生成作业单选
  - 所有选项列表自动附加 `allow_custom_input=True`
- [x] **4.4.3** 实现多轮 clarify 流转：
  - 用户选择选项后，将选择结果注入 `context` 字段重新发送
  - Router 检测到 context 中有补全参数 → 重新分类为 `build_workflow`
- [x] **4.4.4** 编写 clarify 测试：
  - 选项生成正确性
  - 多轮流转（clarify → 用户选择 → build_workflow）
  - `allow_custom_input` 自定义输入处理

> ✅ 验收: "分析英语表现" → clarify + 班级选项列表；用户选择 "1A 班" → 自动进入 build_workflow 并带上 classId。

### Step 4.5: PageChatAgent (页面追问对话)

> 基于已有页面上下文回答用户追问（追问模式下的 `chat` 意图）。

- [x] **4.5.1** 创建 `config/prompts/page_chat.py`：页面对话 system prompt
  - 注入：页面摘要 + 关键数据点 + blueprint 结构
  - 约束：只基于已有数据回答，不编造数值
- [x] **4.5.2** 创建 `agents/page_chat.py`：`PageChatAgent`
  - `generate_response(message, blueprint, page_context, language)` → `str`
  - 有工具访问权限（可查询补充数据）
- [x] **4.5.3** 编写 PageChatAgent 测试：回复相关性、不产生幻觉数据

> ✅ 验收: 给定页面上下文 + "哪些学生需要关注？" → 基于数据的具体回复。

### Step 4.6: 统一会话端点 `POST /api/conversation`

> 单一入口处理所有用户交互，后端内部决策和调度。

- [x] **4.6.1** 创建 `api/conversation.py`：`POST /api/conversation`
  - 接收 `ConversationRequest`
  - 检测模式：`blueprint is None` → 初始模式，否则 → 追问模式
  - **初始模式路由:**
    - `chat_smalltalk` / `chat_qa` → ChatAgent → 返回文本
    - `build_workflow` → PlannerAgent → 返回 Blueprint
    - `clarify` → 构建 ClarifyOptions → 返回交互选项
  - **追问模式路由:**
    - `chat` → PageChatAgent → 返回文本
    - `refine` → PlannerAgent 微调 → 返回新 Blueprint
    - `rebuild` → PlannerAgent 重建 → 返回新 Blueprint + 说明
  - 返回 `ConversationResponse`
- [x] **4.6.2** 保留 `/api/workflow/generate` 和 `/api/page/generate` 作为直调端点（不删除）
- [x] **4.6.3** 在 `main.py` 注册 conversation router
- [x] **4.6.4** 编写端点测试：6 种 action 路径 + 错误处理 + clarify 多轮

**action 路由表（完整版）:**

| action | 模式 | 后端行为 | 响应关键字段 | 前端处理 |
|--------|------|---------|-------------|---------|
| `chat_smalltalk` | 初始 | ChatAgent 回复 | `chatResponse` | 显示回复 |
| `chat_qa` | 初始 | ChatAgent 回复 | `chatResponse` | 显示回复 |
| `build_workflow` | 初始 | PlannerAgent 生成 | `blueprint` + `chatResponse` | 调 `/api/page/generate` |
| `clarify` | 初始 | 返回反问 + 选项 | `chatResponse` + `clarifyOptions` | 渲染交互式选项 UI |
| `chat` | 追问 | PageChatAgent 回答 | `chatResponse` | 显示回复 |
| `refine` | 追问 | PlannerAgent 微调 | `blueprint` + `chatResponse` | 自动调 `/api/page/generate` |
| `rebuild` | 追问 | PlannerAgent 重建 | `blueprint` + `chatResponse` | 展示说明，确认后调 `/api/page/generate` |

> ✅ 验收: 单一端点处理全部 7 种场景，前端根据 `action` 字段做对应渲染。

### Step 4.7: 多 Agent 联调与端到端验证

> 完整闭环测试。

- [x] **4.7.1** 检查所有 Response model 继承 `CamelModel`，序列化 `by_alias=True`
- [x] **4.7.2** 联调测试 — 初始流程：
  - 闲聊 → chat 回复
  - 模糊请求 → clarify 选项 → 用户选择 → build_workflow → Blueprint
  - 明确请求 → build_workflow → Blueprint → page/generate → SSE 页面
- [x] **4.7.3** 联调测试 — 追问流程：
  - 生成页面 → 追问(chat) → 微调(refine) → 重建(rebuild) 全路径
- [x] **4.7.4** 补充 API 错误响应的统一格式
- [x] **4.7.5** 清理遗留路由：标记 `POST /chat` 为 deprecated

> ✅ 验收: 完整的 "闲聊 → 反问 → 生成 → 追问 → 微调" 全闭环可跑通，所有输出 camelCase。

### Phase 4 总验收

- [x] `models/conversation.py` — IntentType + RouterResult + ClarifyOptions + ConversationRequest/Response
- [x] `agents/router.py` — RouterAgent 初始/追问双模式 + 置信度路由
- [x] `agents/chat.py` — ChatAgent 闲聊 + QA
- [x] `agents/page_chat.py` — PageChatAgent 页面追问
- [x] `services/clarify_builder.py` — 交互式反问选项构建
- [x] `api/conversation.py` — POST /api/conversation 统一端点
- [x] `config/prompts/router.py` — Router 双模式 prompt
- [x] `config/prompts/chat.py` — ChatAgent prompt
- [x] `config/prompts/page_chat.py` — PageChatAgent prompt
- [x] `pytest tests/ -v` 全部通过（151 项测试：13 conversation_models + 13 router + 3 chat + 8 clarify + 7 page_chat + 10 conversation_api + 5 E2E + 92 existing）

---

## Phase 4.5: 健壮性增强 + 数据契约升级 ✅ 已完成

**目标**: 解决 Phase 4 闭环后暴露的稳定性与可控性问题——实体解析与校验、sourcePrompt 一致性、action 命名规范化、Executor 错误拦截。确保自然语言班级引用自动解析，LLM 不编造不存在的实体，错误不穿透到前端页面。

**前置条件**: Phase 4 完成（统一会话网关 + 意图路由 + 交互式反问闭环）。

**核心交互升级**:

```
用户: "分析 1A 班英语成绩"
旧流程: Router→build_workflow→Planner 生成 Blueprint（用户需手动选班级）
新流程: Router→build_workflow→EntityResolver 自动解析"1A"→classId→注入 context→PlannerAgent

用户: "对比 1A 和 1B 的成绩"
新流程: EntityResolver 解析多班→classIds[]→注入 context→PlannerAgent

用户: "分析学生 Wong Ka Ho 的成绩"（有班级上下文）
新流程: EntityResolver 自动解析学生→studentId→注入 context→PlannerAgent

用户: "分析学生 Wong Ka Ho 的成绩"（无班级上下文）
新流程: EntityResolver 检测缺少 class 上下文→降级 clarify→展示班级选项

用户: "分析 2C 班英语成绩"（2C 班不存在）
新流程: EntityResolver 匹配失败→降级 clarify→展示实际班级选项
```

### Step 4.5.1: 通用实体解析层（General Entity Resolver）✅ 已完成

> 在 Router → Planner 之间加入确定性实体解析（无 LLM 调用），根据用户输入内容自动识别并解析实体引用（班级/学生/作业）。学生和作业解析依赖班级上下文，缺失时降级为 clarify。

- [x] **4.5.1.1** 创建 `models/entity.py`：
  - `EntityType` 枚举：`class` / `student` / `assignment`
  - `ResolvedEntity(CamelModel)`: entity_type, entity_id, display_name, confidence, match_type
  - `ResolveResult(CamelModel)`: entities, is_ambiguous, scope_mode, missing_context
- [x] **4.5.1.2** 创建 `services/entity_resolver.py`：
  - `resolve_entities(teacher_id, query_text, context?) → ResolveResult`（通用入口）
  - `resolve_classes()` 保留为向下兼容 wrapper
  - **班级解析**: regex 四层匹配（精确 → 别名 → 年级展开 → 模糊）
  - **学生解析**: 关键词触发（"学生"/"student"/"同学"）+ 姓名匹配
  - **作业解析**: 关键词触发（"作业"/"test"/"考试"/"quiz"/"essay"）+ 标题匹配
  - 依赖链: 学生/作业解析依赖 class context（已解析的班级或 context.classId）
  - 无 class context 时 → `missing_context=["class"]`
  - 支持中英文混合引用
  - 数据获取通过 `execute_mcp_tool`（`get_teacher_classes` + `get_class_detail`）
- [x] **4.5.1.3** 在 `api/conversation.py` 的 `build_workflow` 分支中集成通用解析：
  - `missing_context` → 降级为 clarify（"哪个班级？"）
  - 高置信度匹配 → 按 entity_type 注入 classId/studentId/assignmentId 到 context
  - 歧义/低置信度 → 降级为 clarify，choices 从匹配结果生成
  - context 已有 classId 时 → 跳过解析（支持多轮 clarify 流转）
- [x] **4.5.1.4** 更新 `models/conversation.py`：
  - `ConversationResponse` 的 `resolved_entities: list[ResolvedEntity] | None` 字段适配新模型
  - 前端可据 `entityType` 显示对应提示
- [x] **4.5.1.5** 编写测试（31 项新增）：
  - 15 项班级解析单元测试（精确/别名/多班/年级/模糊/边界）
  - 5 项学生解析测试（精确匹配/context classId/缺失 class/英文关键词）
  - 4 项作业解析测试（精确匹配/context classId/缺失 class/关键词触发）
  - 3 项混合实体测试（class+student/class+assignment/student+assignment 无 class）
  - 1 项向下兼容测试（resolve_classes wrapper）
  - 2 项序列化测试（entityType/entityId/missingContext camelCase）
  - 1 项 API 集成测试更新

> ✅ 验收: "分析 1A 班英语成绩" → 自动解析 class + build_workflow；"分析 1A 班学生 Wong Ka Ho 的成绩" → 解析 class + student；"分析学生 Wong Ka Ho"（无班级）→ missing_context + clarify；"对比 1A 和 1B" → 多班自动解析。

### Step 4.5.2: sourcePrompt 一致性校验 ✅ 已完成

> 防止 LLM 改写用户原始请求。确保 Blueprint.sourcePrompt 始终等于原始 message。

- [x] **4.5.2.1** 在 `agents/planner.py` 的 `generate_blueprint()` 返回前增加强制覆写：
  - `blueprint.source_prompt = user_prompt`（不再判空，直接覆写）
  - 如果 LLM 生成的 `source_prompt` 与原文不一致，记录 warning 日志
- [x] **4.5.2.2** 在 `api/conversation.py` 的 build/refine/rebuild 三个分支各加断言：
  - `_verify_source_prompt(blueprint, expected_prompt)` 防御性校验
- [x] **4.5.2.3** 编写测试：验证 sourcePrompt 始终等于原始输入

> ✅ 验收: 无论 LLM 输出什么 sourcePrompt，最终 Blueprint 的 sourcePrompt 必等于原始 message。

### Step 4.5.3: Action 命名统一化 ✅ 已完成

> 消除 action 枚举混用问题（chat_smalltalk/chat_qa vs chat），前端/日志/统计可统一解读。

- [x] **4.5.3.1** 在 `ConversationResponse` 中新增结构化字段：
  ```python
  mode: Literal["entry", "followup"]
  action: Literal["chat", "build", "clarify", "refine", "rebuild"]
  chat_kind: Literal["smalltalk", "qa", "page"] | None = None
  ```
- [x] **4.5.3.2** 保留旧 `action` 字段作为 `@computed_field` 向下兼容：
  - `mode=entry, action=chat, chat_kind=smalltalk` → legacy `"chat_smalltalk"`
  - `mode=entry, action=chat, chat_kind=qa` → legacy `"chat_qa"`
  - `mode=followup, action=chat, chat_kind=page` → legacy `"chat"`
- [x] **4.5.3.3** 更新 Router / Conversation API 适配新字段结构
- [x] **4.5.3.4** 更新所有测试验证新字段

> ✅ 验收: 前端可按 `action` + `chatKind` 二维判断渲染策略；旧 `action` 字段保持兼容。

### Step 4.5.4: Executor 数据阶段错误拦截 ✅ 已完成

> 防止 error dict 穿透到 Compose 阶段，产出空壳页面。

- [x] **4.5.4.1** Executor `_resolve_data_contract` 中检查 tool 返回值：
  - 如果返回包含 `"error"` key 且 binding.required == True → 抛出 `DataFetchError`
  - 非 required binding 的错误 → warning 日志 + 跳过
- [x] **4.5.4.2** 新增 SSE 事件类型 `DATA_ERROR`：
  ```json
  {"type": "DATA_ERROR", "entity": "class-2c", "message": "班级不存在", "suggestions": [...]}
  ```
- [x] **4.5.4.3** 前端收到 `DATA_ERROR` 时可展示友好提示而非空页面
- [x] **4.5.4.4** 编写测试：required binding 返回 error → 终止 + DATA_ERROR 事件

> ✅ 验收: Executor 遇到不存在的实体时，返回 DATA_ERROR 事件，不再产出空壳页面。

### Phase 4.5 总验收

- [x] `models/entity.py` — EntityType 枚举 + ResolvedEntity (entity_type/entity_id) + ResolveResult (entities/missing_context)
- [x] `services/entity_resolver.py` — 通用实体解析: class/student/assignment 三类 + 依赖链 + 降级逻辑
- [x] `models/conversation.py` — resolved_entities 字段适配新模型 (Phase 4.5.1)
- [x] `api/conversation.py` — 通用实体解析集成 + missing_context 处理 + 多类型 context 注入 (Phase 4.5.1)
- [x] `errors/exceptions.py` — ToolError + DataFetchError + EntityNotFoundError 自定义异常体系
- [x] `agents/planner.py` — sourcePrompt 强制覆写 + warning 日志
- [x] `models/conversation.py` — mode/action/chatKind 三维结构化 + legacyAction computed_field 向下兼容
- [x] `api/conversation.py` — _verify_source_prompt() 防御性校验 + 13 处 ConversationResponse 适配
- [x] `agents/executor.py` — 数据阶段错误拦截 + DATA_ERROR 事件 + DataFetchError 处理
- [x] `pytest tests/ -v` 全部通过（230 项测试）

---

## Phase 5: Java 后端对接 ✅ 已完成

**目标**: 将 mock 数据替换为真实的 Java 后端 API 调用，通过 Adapter 抽象层隔离外部 API 变化，实现数据从教务系统到 AI 分析的完整链路。

**前置条件**: Phase 4.5 完成（实体校验 + 错误拦截机制就位）。

### Step 5.1: HTTP 客户端封装 ✅ 已完成

> 建立与 Java 后端通信的基础设施。

- [x] **5.1.1** 安装 httpx 依赖
- [x] **5.1.2** 创建 `services/java_client.py`：
  - 封装 `httpx.AsyncClient`，配置 base_url / timeout / headers
  - 通用请求方法：`get()`, `post()`，统一错误处理
  - 自定义异常：`JavaClientError`（非 2xx 响应）, `CircuitOpenError`（熔断器打开）
- [x] **5.1.3** 在 Settings 中添加 Java 后端配置：`spring_boot_base_url`, `spring_boot_api_prefix`, `spring_boot_timeout`, `spring_boot_access_token`, `spring_boot_refresh_token`
- [x] **5.1.4** 实现连接池管理和优雅关闭（FastAPI lifespan）
  - `main.py` 的 `lifespan()` 中 `await client.start()` / `await client.close()`
  - `get_java_client()` 单例模式

> ✅ 验收: `java_client.get("/dify/teacher/t-001/classes/me")` 可成功调用（或在 Java 不可用时优雅降级）。

### Step 5.2: Data Adapter 抽象层 ✅ 已完成

> 在工具层和 Java 客户端之间建立适配层，隔离外部 API 变化对内部系统的影响。

- [x] **5.2.1** 定义内部标准数据结构 `models/data.py`：
  - `ClassInfo`, `ClassDetail`, `StudentInfo`, `AssignmentInfo`, `SubmissionData`, `SubmissionRecord`, `GradeData`, `GradeRecord`
  - 工具层、Planner、Executor 只依赖这些内部模型
- [x] **5.2.2** 创建 `adapters/` 目录，实现各数据适配器：
  - `adapters/class_adapter.py` — Java 班级 API 响应 → `ClassInfo` / `ClassDetail` / `AssignmentInfo`
  - `adapters/grade_adapter.py` — Java 成绩 API 响应 → `GradeData` / `GradeRecord`
  - `adapters/submission_adapter.py` — Java 作业 API 响应 → `SubmissionData` / `SubmissionRecord`
  - 每个 adapter 实现 `_unwrap_data()` 解包 Java `Result<T>` 包装 + `_parse_*()` 字段映射
- [x] **5.2.3** 编写 adapter 单元测试：Java 响应样本 → 内部模型映射正确（15 项测试）

> ✅ 验收: Java API 字段改名/结构变化 → 只改 adapter，工具层/Planner/Executor 不受影响。

```
架构:
tools/data_tools.py  →  adapters/class_adapter.py       →  services/java_client.py
                     →  adapters/grade_adapter.py        →
                     →  adapters/submission_adapter.py   →
```

### Step 5.3: 数据工具切换 ✅ 已完成

> 将 mock 数据工具替换为调用 Java API 的真实版本（通过 adapter 层）。

- [x] **5.3.1** 重构 `tools/data_tools.py`：每个工具内部调用 adapter → `java_client`
  - `get_teacher_classes` → `class_adapter.list_classes(java_client, teacher_id)`
  - `get_class_detail` → `class_adapter.get_detail(java_client, teacher_id, class_id)` + `list_assignments()`
  - `get_assignment_submissions` → `submission_adapter.get_submissions(java_client, ...)`
  - `get_student_grades` → `grade_adapter.get_student_submissions(java_client, ...)`
- [x] **5.3.2** 保留 mock fallback：当 Java 不可用时降级到 mock 数据（通过配置开关 `USE_MOCK_DATA`）
  - `_should_use_mock()` 检查 `Settings.use_mock_data`
  - 所有工具 `except Exception` → 自动降级到 mock
- [x] **5.3.3** 工具对外接口保持不变，Planner/Executor 无需修改

> ✅ 验收: 连接 Java 后端时使用真实数据，断连时降级到 mock，工具对外接口不变。

### Step 5.4: 错误处理与健壮性 ✅ 已完成

> 确保外部依赖不稳定时系统仍可用。

- [x] **5.4.1** 实现重试策略：网络超时、5xx 错误自动重试（指数退避，最多 3 次）
  - `MAX_RETRIES=3`, `RETRY_BASE_DELAY=0.5s`（每次翻倍）
  - 重试条件：`httpx.TransportError`（网络错误）+ 5xx 响应
  - 不重试：4xx 客户端错误（立即抛出）
- [x] **5.4.2** 实现熔断/降级：连续失败 5 次后自动切换到 mock 数据
  - `CIRCUIT_OPEN_THRESHOLD=5`, `CIRCUIT_RESET_TIMEOUT=60s`
  - 三状态：CLOSED → OPEN（快速失败）→ HALF_OPEN（探测恢复）
  - 成功请求自动重置计数器
- [x] **5.4.3** 添加请求日志：记录 Java API 调用耗时、状态码
  - `"{method} {path} → {status_code} ({elapsed_ms}ms)"`
- [x] **5.4.4** 端到端测试：模拟 Java 服务超时/500 → 验证降级行为
  - 20 项 Java 客户端测试（重试、熔断、生命周期）
  - 8 项工具降级测试（4 个工具 × fallback + adapter path）
  - 2 项 E2E 降级测试（Java 500/timeout → mock → 完整页面输出）

> ✅ 验收: Java 后端宕机时，系统自动降级到 mock 数据，不影响用户使用。

### Phase 5 总验收

- [x] `services/java_client.py` — httpx.AsyncClient + 重试（指数退避 3 次）+ 熔断器（5 次阈值）+ Bearer token 认证
- [x] `models/data.py` — 8 个内部数据模型：ClassInfo/ClassDetail/StudentInfo/AssignmentInfo/SubmissionData/SubmissionRecord/GradeData/GradeRecord
- [x] `adapters/class_adapter.py` — Java Classroom API → ClassInfo/ClassDetail/AssignmentInfo
- [x] `adapters/submission_adapter.py` — Java Submission API → SubmissionData/SubmissionRecord
- [x] `adapters/grade_adapter.py` — Java Grade API → GradeData/GradeRecord
- [x] `tools/data_tools.py` — 4 个数据工具通过 adapter 调用 Java API + 自动 mock 降级
- [x] `config/settings.py` — spring_boot_base_url/api_prefix/timeout/access_token/refresh_token/use_mock_data
- [x] `main.py` — lifespan 管理 JavaClient 生命周期
- [x] `pytest tests/ -v` 全部通过（238 项测试：15 adapters + 20 java_client + 21 tools + 7 E2E_page + 175 existing）

---

## Phase 6: 前端集成 + Level 2 + SSE 升级 + Patch 机制 ✅ 已完成

**目标**: 将 Executor Phase C 从单次 AI 生成升级为逐 block 流式生成，新增 BLOCK_START/SLOT_DELTA/BLOCK_COMPLETE SSE 事件，实现 Per-Block AI 内容生成（Level 2），引入 Patch 机制支持增量修改（避免每次微调都全页重建），编写完整 E2E 测试。

**前置条件**: Phase 5 完成（真实数据链路打通）。

**备注**：这个阶段代码尚未部署，不需要考虑前向兼容问题。

**依赖关系**:
- 6.1 (文档契约) → 独立
- 6.2 (SSE 事件流) → 6.3 (Per-Block AI) → 6.5 (E2E 测试)
- 6.4 (Patch 机制) → 6.5 (E2E 测试)

### Step 6.1: SSE 事件模型 + 前端 Proxy 文档契约 ✅ 已完成

> SSE block/slot 事件模型定义 + 前端 proxy 路由契约文档。

- [x] **6.1.1** 创建 `models/sse_events.py`：BlockStartEvent, SlotDeltaEvent, BlockCompleteEvent（继承 CamelModel）
- [x] **6.1.2** 编写 `tests/test_sse_events.py`：camelCase 序列化测试（blockId, componentType, slotKey, deltaText）
- [x] **6.1.3** 创建 `docs/integration/nextjs-proxy.md`：前端 proxy 路由契约文档
- [x] **6.1.4** 更新 `docs/api/sse-protocol.md`：将 Phase 6 事件从 "planned" 改为 "implemented"

> ✅ 验收: 测试通过，SSE 事件模型序列化正确，前端对接文档就绪。

### Step 6.2: Executor Phase C 重构 — 逐 block 事件流 ✅ 已完成

> 将 Executor Phase C 从单次 AI 生成升级为逐 block 流式输出，发送 BLOCK_START/SLOT_DELTA/BLOCK_COMPLETE 事件。

- [x] **6.2.1** SSE 事件模型已在 Step 6.1 完成
- [x] **6.2.2** 重构 `agents/executor.py`：
  - 新增 `_stream_ai_content()` 异步生成器：遍历 ai_content_slot，逐 block yield BLOCK_START → SLOT_DELTA → BLOCK_COMPLETE
  - 新增 `_generate_block_content()`：单 block AI 内容生成入口
  - 新增 `_fill_single_block()` 模块级函数：从 `_fill_ai_content()` 提取单 block 填充逻辑
  - 新增 `_get_slot_key()` 辅助函数：component_type → slot key 映射
  - 重构 `execute_blueprint_stream()` Phase C：用 `_stream_ai_content()` 替代旧的 `_generate_ai_narrative()` + `_fill_ai_content()`
  - 移除旧 MESSAGE 事件，Phase C 统一使用 BLOCK_START/SLOT_DELTA/BLOCK_COMPLETE
- [x] **6.2.3** 编写 Executor 新测试（`tests/test_executor.py`）：
  - `test_stream_emits_block_start_for_ai_slots()` — 每个 ai_content_slot 产生 BLOCK_START
  - `test_stream_emits_slot_delta_with_content()` — SLOT_DELTA 含 blockId + slotKey + deltaText
  - `test_block_event_ordering()` — BLOCK_START → SLOT_DELTA → BLOCK_COMPLETE 顺序
  - `test_non_ai_slots_no_block_events()` — kpi_grid/chart/table 不产生 BLOCK 事件
- [x] **6.2.4** 更新 E2E 测试（`tests/test_e2e_page.py`）：
  - 更新 `test_e2e_sse_event_format()` — 增加 BLOCK_START/SLOT_DELTA/BLOCK_COMPLETE 格式验证
  - 更新现有测试：mock 改为 `_generate_block_content` 而非 `_generate_ai_narrative`

> ✅ 验收: 全部 251 项测试通过（243 existing + 8 new），Phase C 统一使用 BLOCK 事件流。

### Step 6.3: Per-Block AI 生成（Level 2）✅ 已完成

> 让每个 ai_content_slot 独立 AI 生成，支持 markdown/suggestion_list/question_generator 等多种内容类型。

- [x] **6.3.1** 创建 `config/prompts/block_compose.py`：
  - `build_block_prompt(slot, blueprint, data_context, compute_results)` → `(prompt, output_format)`
  - `_build_markdown_prompt()` — 分析叙事文本 prompt
  - `_build_suggestion_prompt()` — JSON 结构化建议 prompt（返回 `[{title, description, priority, category}]`）
  - `_build_question_prompt()` — JSON 题目生成 prompt
  - `_build_data_summary()` — 注入 data_context + compute_results
- [x] **6.3.2** 编写 prompt 构建器测试（`tests/test_block_compose.py`）：
  - `test_markdown_prompt_contains_data_summary()` — 验证数据注入
  - `test_suggestion_prompt_requests_json_format()` — output_format == "json"
  - `test_question_prompt_includes_slot_props()` — 使用 slot.props
- [x] **6.3.3** 升级 `agents/executor.py`：
  - 升级 `_generate_block_content()`：使用 `build_block_prompt()` 生成 per-block prompt
  - 对 JSON output_format：解析 LLM JSON 返回值，失败降级为单项包装
  - 升级 `_fill_single_block()`：处理 list/dict 返回值（suggestion_list items, question_generator questions）
  - 删除旧的 `_generate_ai_narrative()` + `_fill_ai_content()`（未部署，直接移除）
- [x] **6.3.4** 编写 Executor 升级测试（`tests/test_executor.py`）：
  - `test_generate_block_content_markdown()` — mock LLM 返回文本，block content 正确
  - `test_generate_block_content_suggestion_list()` — mock LLM 返回 JSON 数组
  - `test_generate_block_content_json_fallback()` — LLM 返回无效 JSON 时降级
  - `test_each_ai_slot_separate_llm_call()` — 每个 ai_content_slot 独立 LLM 调用

> ✅ 验收: per-block AI 生成工作，各 component_type 正确填充。312 项测试通过。

### Step 6.4: Patch 机制 ✅ 已完成

> 追问模式的 refine 引入 Patch 指令，按 scope 分流避免每次微调都整页重建。

#### 6.4.1: Patch 数据模型 + Router 扩展

- [x] **6.4.1.1** 创建 `models/patch.py`：
  - `PatchType` 枚举：update_props, reorder, add_block, remove_block, recompose
  - `RefineScope` 枚举：patch_layout, patch_compose, full_rebuild
  - `PatchInstruction(CamelModel)`：type, target_block_id, changes
  - `PatchPlan(CamelModel)`：scope, instructions, affected_block_ids
- [x] **6.4.1.2** 编写 `tests/test_patch_models.py`：camelCase 序列化测试 + 枚举值测试
- [x] **6.4.1.3** 修改 `models/conversation.py`：
  - `RouterResult` 新增 `refine_scope: str | None = None`
  - `ConversationResponse` 新增 `patch_plan: PatchPlan | None = None`
- [x] **6.4.1.4** 修改 `config/prompts/router.py`：
  - `ROUTER_FOLLOWUP_PROMPT` 新增 refine_scope 输出指导：
    - `patch_layout`：UI 修改（颜色/顺序/标题）
    - `patch_compose`：内容修改（缩写/换措辞）
    - `full_rebuild`：结构修改（增删模块）
- [x] **6.4.1.5** 编写 `tests/test_router.py` 新增测试：
  - `test_followup_refine_scope_in_output()` — RouterResult 含 refine_scope

> ✅ 验收: Patch 模型序列化正确，Router 输出含 refine_scope。

#### 6.4.2: PatchAgent + Executor execute_patch()

- [x] **6.4.2.1** 创建 `agents/patch_agent.py`：
  - `PatchAgent.analyze_refine(message, blueprint, page, refine_scope)` → `PatchPlan`
  - `PATCH_LAYOUT`：确定性 prop 修改（无 LLM）
  - `PATCH_COMPOSE`：识别 ai_content_slot blocks，生成 RECOMPOSE 指令
  - `FULL_REBUILD`：返回空 PatchPlan（调用方走完整 rebuild 路径）
- [x] **6.4.2.2** 修改 `agents/executor.py`：
  - 新增 `execute_patch(old_page, blueprint, patch_plan, data_context, compute_results)` 异步生成器
  - `PATCH_LAYOUT`：修改 block props，yield COMPLETE（无 LLM）
  - `PATCH_COMPOSE`：只对 affected blocks 重新 AI 生成，yield BLOCK 事件
  - 辅助函数：`_deep_copy_page()`, `_apply_prop_patch()`, `_find_slot()`, `_find_block()`
- [x] **6.4.2.3** 创建 `tests/test_patch.py`：
  - `test_patch_layout_skips_ai()` — PATCH_LAYOUT 不调用 LLM
  - `test_patch_compose_regenerates_ai_only()` — 只重新生成 ai_content_slot
  - `test_patch_compose_preserves_data_blocks()` — kpi/chart/table 不变
  - `test_execute_patch_emits_block_events()` — SSE 事件正确

> ✅ 验收: Patch 执行正确，PATCH_LAYOUT 无 LLM 调用，PATCH_COMPOSE 只重生成 AI 块。

#### 6.4.3: Conversation API Patch 集成 + Page Patch 端点

- [x] **6.4.3.1** 修改 `api/conversation.py`：
  - refine 分支：检查 `router_result.refine_scope`
  - `patch_layout` / `patch_compose` → `PatchAgent.analyze_refine()` → 返回 ConversationResponse 含 patch_plan
  - `full_rebuild` / None → 保持现有行为（PlannerAgent 生成新 Blueprint）
- [x] **6.4.3.2** 修改 `models/request.py`：
  - 新增 `PagePatchRequest(CamelModel)`：blueprint, page, patch_plan, context, data_context, compute_results
- [x] **6.4.3.3** 修改 `api/page.py`：
  - 新增 `POST /api/page/patch` 端点：接收 PagePatchRequest → execute_patch() → SSE 流
- [x] **6.4.3.4** 编写 `tests/test_conversation_api.py` 新增测试：
  - `test_refine_patch_layout_returns_patch_plan()` — refine_scope=patch_layout 返回 patch_plan
  - `test_refine_full_rebuild_generates_new_blueprint()` — 无 refine_scope 走旧路径

> ✅ 验收: refine 分支按 scope 分流，`/api/page/patch` 端点可用。312 项测试通过。

### Step 6.5: E2E 测试 ✅ 已完成

> 全链路质量保障，覆盖正常流程、Patch 流程、降级流程。

- [x] **6.5.1** 创建 `tests/test_e2e_phase6.py`：
  - `test_e2e_full_lifecycle_with_block_events()` — prompt → Blueprint → page SSE → 验证 BLOCK 事件
  - `test_e2e_refine_patch_layout()` — 生成 → refine "改颜色" → patch_plan 不含新 blueprint
  - `test_e2e_refine_patch_compose()` — 生成 → refine "缩短分析" → 只重生成 AI blocks
  - `test_e2e_refine_full_rebuild()` — 生成 → rebuild "加板块" → 新 blueprint
  - `test_e2e_java_timeout_with_block_events()` — Java 超时降级 + BLOCK 事件仍正常
  - `test_e2e_llm_failure_error_complete()` — LLM 失败 → error COMPLETE
  - `test_e2e_nonexistent_entity_data_error()` — 实体不存在 → DATA_ERROR
  - `test_e2e_http_page_patch_endpoint()` — HTTP /api/page/patch SSE 端点
- [x] **6.5.2** 全量测试验证：`pytest tests/ -v` 全部通过（320 项测试）

> ✅ 验收: 全部 E2E 测试通过，Phase 6 功能完整可用。

### Phase 6 关键文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `models/sse_events.py` | 新建 ✅ | SSE block/slot 事件模型 |
| `models/patch.py` | 新建 ✅ | PatchInstruction, PatchPlan, RefineScope |
| `config/prompts/block_compose.py` | 新建 ✅ | Per-block AI prompt 构建器 |
| `agents/patch_agent.py` | 新建 ✅ | Patch 分析 agent |
| `docs/integration/nextjs-proxy.md` | 新建 ✅ | 前端 proxy 契约 |
| `agents/executor.py` | 重构 ✅ | Phase C 逐 block 流 + execute_patch() |
| `api/conversation.py` | 修改 ✅ | refine 分支 scope 分流 |
| `api/page.py` | 修改 ✅ | 新增 /api/page/patch 端点 |
| `models/conversation.py` | 修改 ✅ | RouterResult.refine_scope + ConversationResponse.patch_plan |
| `models/request.py` | 修改 ✅ | PagePatchRequest |
| `config/prompts/router.py` | 修改 ✅ | followup prompt 加 refine_scope |
| `tests/test_e2e_phase6.py` | 新建 ✅ | Phase 6 E2E 测试 (8 项) |

### Phase 6 总验收

- [x] `models/sse_events.py` — BlockStartEvent/SlotDeltaEvent/BlockCompleteEvent camelCase 序列化
- [x] `agents/executor.py` — Phase C 逐 block 流式输出 + execute_patch() 增量修改
- [x] `config/prompts/block_compose.py` — Per-block AI prompt 构建 (markdown/suggestion/question)
- [x] `agents/patch_agent.py` — PatchAgent 分析 refine scope + 生成 PatchPlan
- [x] `api/page.py` — POST /api/page/patch SSE 端点
- [x] `api/conversation.py` — refine 分支按 scope 分流 (patch_layout/patch_compose/full_rebuild)
- [x] `tests/test_e2e_phase6.py` — 8 项 E2E 测试全部通过
- [x] `pytest tests/ -v` 全部通过（320 项测试）

---

## 里程碑总览

| 里程碑 | Phase | 核心交付 |
|--------|-------|---------|
| **M0: 原型验证** | 0 ✅ | Flask + LLM 工具调用可运行 |
| **M1: 技术基座** | 1 ✅ | FastAPI + Pydantic Models + FastMCP Tools |
| **M2: 智能规划** | 2 ✅ | 用户 prompt → 结构化 Blueprint |
| **M3: 页面构建** | 3 ✅ | Blueprint → SSE 流式页面 |
| **M4: 会话网关** | 4 ✅ | 统一会话入口 + 意图路由 + 交互式反问，完整交互闭环 |
| **M4.5: 健壮性增强** | 4.5 ✅ | 实体校验 + sourcePrompt 防篡改 + action 规范化 + 错误拦截 |
| **M5: 真实数据** | 5 ✅ | Java 后端对接 + Adapter 抽象层，mock → 真实教务数据 |
| **M6: 产品上线** | 6 ✅ | 前端集成 + Level 2 Per-Block AI + SSE Block 事件流 + Patch 机制 + E2E 测试 |
| **M7: 智能题目生成** | 7 🔄 | RAG 知识库 + 知识点字典 + 题目生成流水线 + 学情分析 |

---

## Phase 7: 智能题目生成与学情分析优化 🔄 进行中

**目标**: 将题目生成从"纯 LLM 猜测"升级为"标准库检索 + 学情驱动 + 结构化输出"，实现可用、可控、可持续迭代的出题能力。

**前置条件**: Phase 6 完成（Per-Block AI 生成 + Patch 机制）。

**计划文档**: [2026-02-03-phase7-question-generation.md](plans/2026-02-03-phase7-question-generation.md)

### P0 任务（必须先做）

- [x] **P0-1:** 题目级数据模型 + 错题数据接入
  - [x] 扩展 `models/data.py`: QuestionItem, QuestionSpec, ErrorPattern, StudentMastery
  - [x] 扩展 `SubmissionRecord`: items[] 题目级明细
  - [x] 新增 `tools/assessment_tools.py`: analyze_student_weakness, get_student_error_patterns

- [x] **P0-2:** Blueprint→Page 结构一致性修复
  - [x] 修复 `tools/stats_tools.py`: calculate_stats 新增 summary 字段
  - [x] 更新 `config/prompts/planner.py`: Rule 11-12 约束

- [x] **P0-3:** Rubric-as-Assets（最小标准库）
  - [x] 新增 `models/rubric.py`: Rubric, RubricCriterion, RubricLevel
  - [x] 新增 `data/rubrics/*.json`: DSE 评分标准
  - [x] 新增 `services/rubric_service.py`: Rubric 加载服务
  - [x] 新增 `tools/rubric_tools.py`: get_rubric 工具

- [x] **P0-4:** 题目生成流水线 Draft→Judge→Repair
  - [x] 新增 `models/question_pipeline.py`: QuestionDraft, JudgeResult, QuestionFinal
  - [x] 新增 `agents/question_pipeline.py`: 三阶段流水线

### P1 任务（重要优化）

- [x] **P1-1:** RAG 基础设施
  - [x] 新增 `services/rag_service.py`: SimpleRAGStore + CurriculumRAG
  - [x] 分库设计: official_corpus, school_assets, question_bank

- [x] **P1-2:** 知识点字典
  - [x] 新增 `data/knowledge_points/*.json`: DSE Math, Chinese, ICT, English
  - [x] 新增 `services/knowledge_service.py`: 知识点注册表服务
  - [x] 错误标签 → 知识点 ID 映射

### P2 任务（中长期）

- [ ] **P2-1:** Teacher-in-the-loop 数据闭环
- [ ] **P2-2:** 混合生成策略（题库检索优先 + LLM 变体）

### Phase 7 关键文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `models/data.py` | 修改 ✅ | 新增 QuestionItem, ErrorPattern, StudentMastery |
| `models/rubric.py` | 新建 ✅ | Rubric, RubricCriterion, RubricLevel |
| `models/question_pipeline.py` | 新建 ✅ | QuestionDraft, JudgeResult, QuestionFinal |
| `data/rubrics/*.json` | 新建 ✅ | 7 个评分标准文件 (English, Math, Chinese, ICT) |
| `data/knowledge_points/*.json` | 新建 ✅ | 4 个知识点文件 (English, Math, Chinese, ICT) |
| `services/rubric_service.py` | 新建 ✅ | Rubric 加载服务 |
| `services/rag_service.py` | 新建 ✅ | RAG 分库服务 |
| `services/knowledge_service.py` | 新建 ✅ | 知识点注册表服务 |
| `agents/question_pipeline.py` | 新建 ✅ | Draft→Judge→Repair 流水线 |
| `tools/stats_tools.py` | 修改 ✅ | 新增 summary 字段 |
| `tools/assessment_tools.py` | 新建 ✅ | 学情分析工具 |
| `tools/rubric_tools.py` | 新建 ✅ | Rubric 检索工具 |
| `tests/test_rag_question_generation.py` | 新建 ✅ | 31 项 RAG + 知识点测试 |

---

## Future: 长期策略（不急于实现，记录备查）

### ComputeGraph 节点分类策略

当前 Phase 3 的 ComputeGraph 中 AI 节点暂跳过（Phase C 统一生成），这是短期高效的做法。长期需要区分三种节点以支持增量更新和缓存：

| 节点类型 | 说明 | 可缓存 | 可复现 |
|----------|------|--------|--------|
| `tool` | 确定性工具调用（当前已有） | 是（输入不变则输出不变） | 是 |
| `deterministic` | 纯计算节点（如统计聚合） | 是 | 是 |
| `llm` | AI 生成节点 | 需结构化输出 + 版本化 | 需 seed + 模型固定 |

**未来收益**:
- 增量更新："只重跑某几个节点"而非全页重建
- 缓存策略：`tool` 和 `deterministic` 节点可直接复用结果
- `llm` 节点输出必须结构化（Pydantic model）并可缓存

### 多 Agent 协作扩展

- Agent 间消息总线（当前通过 conversation.py 串行调度）
- Agent 并行执行（如数据获取和 AI 叙事可并行）
- Agent 结果聚合与冲突解决
