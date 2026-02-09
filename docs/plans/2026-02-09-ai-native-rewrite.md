# Plan: AI 原生单栈重构 — 从硬编码编排到 Tool Calling 原生架构

**Date:** 2026-02-09

**Goal:** 将 AI Agent 从"代码控制 AI"重构为"AI 控制代码"。删除所有硬编码路由/阈值/正则/DSL/手工 tool loop，改用 LLM 原生 tool calling 自主编排。

**Scope:** `insight-ai-agent/` 模块内部重构，原地替换 `conversation.py`（不上线、不需前向兼容）。前端仅端点切换，SSE 协议不变。

**前置条件:** Convergence Phase 1 (Quiz) PASS，Phase 2 进行中。本次重构等同于 Phase 3 + Phase 4 合并执行。

**迁移策略:** 直接原地替换，不做长期双轨维护。仅保留单入口环境开关 (`NATIVE_AGENT_ENABLED`) 用于紧急回退，无并行代码维护。

---

## 0. 架构对比：现状 vs 目标

### 现状（硬编码编排）

```
用户消息
  ↓
RouterAgent (if-elif 意图分类 + 置信度阈值 + 关键词正则)
  ↓
conversation.py (12+ handler 函数分发)
  ↓
┌─────────────────────┐
│ chat_response()     │ → ChatAgent (手工 tool loop)
│ _stream_build()     │ → PlannerAgent → ExecutorAgent (三阶段流水线 + $ref DSL)
│ _stream_quiz_*()    │ → Skill Path / Unified Agent (双路并存)
│ _stream_content_*() │ → Teacher Agent
│ _stream_modify_*()  │ → PatchAgent (正则匹配)
│ _stream_followup*() │ → 各种 followup handler
└─────────────────────┘
  ↓
DataStreamEncoder (手工 SSE 编码)
  ↓
前端
```

**问题:** ~2500+ 行编排代码，每新增功能需改 3-5 个文件，路由规则脆弱。

### 目标（AI 原生）

```
用户消息
  ↓
conversation.py (薄网关，~100 行，原地替换)
  → 职责：鉴权、会话、限流、SSE 适配、终态校验
  → 禁止：意图路由、阈值改写、关键词补丁
  → 入口开关：NATIVE_AGENT_ENABLED=true/false（紧急回退）
  ↓
NativeAgent (单 runtime)
  → 每轮根据上下文选择 toolset 子集（8-12 个 tools/轮）
  → PydanticAI Agent(tools=selected_subset).run_stream()
  → LLM 自主决定是否调用 tool → 自动执行 → 自动循环
  ↓
tools/registry.py (单一工具注册源 + toolset 分包)
  → base_data: get_teacher_classes, get_class_detail, ...
  → analysis: calculate_stats, compare_performance, ...
  → generation: generate_quiz, generate_pptx, ...
  → artifact_ops: get_artifact, patch_artifact, regenerate_from_previous
  → platform: save_as_assignment, search_teacher_documents, ...
  ↓
SSE 事件适配器 (native stream → Data Stream Protocol)
  ↓
前端 (契约不变)
```

**收益:** ~400 行核心代码，新增功能只需加一个 tool 定义 + 归入对应 toolset。

---

## 1. 重写目标（5 个"单一"+ 2 个"零"）

| 原则 | 说明 |
|------|------|
| **单入口** | 原地替换 `conversation.py`，stream + non-stream 共用同一 runtime |
| **单编排** | 只用 `Agent.run_stream()` / `run()`，不再手写 tool loop |
| **单状态** | 只用 `conversation_id` + 持久化 store，不再区分 initial/followup handler |
| **单工具源** | 工具只注册一次（schema + function），无双 registry |
| **单模型入口** | `create_model()` 保留，删除 `router_model` / `executor_model` 分离；保留 `fast_model` 作为统一 Agent 的可选 tier（如首次调用降低延迟） |
| **零路由规则** | 删除 intent if-elif、confidence threshold、keyword regex、patch regex |
| **零 DSL** | 删除 `$data.xxx` 解析器，tool 输出直接入 LLM context |

---

## 1.5 薄网关职责定义 — `conversation.py` 重写后的边界

重写后的 `conversation.py` 是一层**薄网关**（thin gateway），不做任何业务决策。

### 网关 **做** 的事

| 职责 | 说明 |
|------|------|
| 鉴权 | 验证 JWT，提取 `teacher_id`，注入 `AgentDeps` |
| 会话管理 | 生成/校验 `conversation_id`，加载/保存 `message_history` |
| SSE 适配 | 调用 `NativeAgent.run_stream()`，通过 `stream_adapter` 将事件转为 Data Stream Protocol |
| 限流 | 请求级限流（如 per-teacher QPS），防止滥用 |
| 终态校验 | 确认 stream 正常结束（`finish` 事件已发送），异常时补发 `error` 事件 |
| 入参校验 | 校验 `ConversationRequest` 结构，拒绝非法请求 |

### 网关 **不做** 的事

| 禁止行为 | 说明 |
|----------|------|
| **意图分流** | 不做 if-elif 路由，不判断 intent |
| **业务逻辑** | 不解析消息内容，不检测关键词 |
| **Tool 选择** | 不决定调哪个 tool，交给 LLM |
| **状态机** | 不维护 entity resolution 等对话状态机 |
| **模型选择** | 不根据场景切换模型（统一由 `NativeAgent` 内部决定 tier） |

> 判断标准：如果某段逻辑需要理解"用户在说什么"，它就不属于网关，应该由 LLM + tool 处理。

---

## 2. 需要删除/下线的模块

| 模块 | 文件 | 行数(估) | 删除原因 |
|------|------|---------|---------|
| RouterAgent | `agents/router.py` | ~315 | LLM 自主选 tool，无需手工意图分类 |
| ExecutorAgent | `agents/executor.py` | ~500+ | 三阶段流水线被 tool calling 自动编排取代 |
| Resolver DSL | `agents/resolver.py` | ~100 | `$prefix.path` 自定义 DSL 被 tool 上下文取代 |
| PatchAgent | `agents/patch_agent.py` | ~150 | 正则匹配被 `modify_*` tool 取代 |
| ChatAgent | `agents/chat_agent.py` | ~90 | 手工 tool loop 被 native agent 取代 |
| 旧 conversation 分发 | `api/conversation.py` (12+ handlers) | ~2200 | 原地重写为 ~100 行薄 API 层 |
| 双重工具注册 | `tools/__init__.py` (TOOL_REGISTRY) | ~60 | 改为单一注册 |
| 关键词提示 | `config/prompts/router.py` | ~200 | 路由 prompt 不再需要 |
| Entity Resolver | `services/entity_resolver.py` | ~200 | 改为 `resolve_entity` tool |

**保留的模块:**

| 模块 | 文件 | 说明 |
|------|------|------|
| 工具实现 | `tools/data_tools.py`, `stats_tools.py`, etc. | 业务逻辑不变，只改注册方式 |
| Blueprint 模型 | `models/blueprint.py` | 数据结构保留（tool 输出类型） |
| SSE 编码器 | `services/datastream.py` | 保留，作为 native stream → 前端协议的适配层 |
| Provider | `agents/provider.py` | 保留 `create_model()`，删除 `execute_mcp_tool()` |
| Session Store | `services/conversation_store.py` | 保留，升级为 conversation_id 主键 |
| 系统 Prompt | `config/prompts/native_agent.py` (新建) | 替代旧 `planner.py`，精简为角色定义 + 能力列表，不含硬编码 schema |

---

## 3. 新增/重写文件清单

| 文件 | 操作 | 职责 | 行数(估) |
|------|------|------|---------|
| `agents/native_agent.py` | NEW | 核心 runtime：按需创建 PydanticAI Agent(tools=subset) + run_stream | ~180 |
| `tools/registry.py` | NEW | 单一工具注册源 + toolset 分包（base_data / analysis / generation / artifact_ops / platform） | ~140 |
| `api/conversation.py` | REWRITE | 原地替换为薄网关（含 `NATIVE_AGENT_ENABLED` 入口开关） | ~110 |
| `services/stream_adapter.py` | NEW | native agent 事件 → Data Stream Protocol 适配（基于 Step 0.5 校准结果） | ~80 |
| `services/metrics.py` | NEW | Step 1: 结构化日志；Step 2+: MetricsCollector 聚合（可选 `/api/metrics`） | ~60 |

**总新增:** ~470 行新文件 + ~110 行重写（对比删除 ~3800 行）

---

## 4. 实施计划

### Step 0.5: PydanticAI Stream API 校准

> 目标: 锁定 PydanticAI 版本，验证实际流事件类型，为 stream_adapter.py 提供准确映射依据。

- [ ] **0.5.1** 锁定当前 `pydantic-ai` 版本（`pip show pydantic-ai`），写入 `requirements.txt`
- [ ] **0.5.2** 编写最小 stream demo 脚本 `scripts/pydantic_ai_stream_demo.py`
  - 创建一个带 1 个 tool 的 Agent
  - 调用 `agent.run_stream()`，打印所有事件类型 + 字段
  - 记录实际事件名（`TextPart` / `ToolCallPart` / `ToolReturnPart` / 其他）
- [ ] **0.5.3** 输出事件映射表文档 `docs/plans/stream-event-mapping.md`
  - 左列: PydanticAI 实际事件类型
  - 右列: Data Stream Protocol SSE 事件
  - 此表作为 Step 1.3 `stream_adapter.py` 的实现依据
- [ ] **0.5.4** 确认 `agent.run_stream()` 对 `message_history` 参数的序列化格式

#### 🔒 冻结点 1: 协议冻结（Step 0.5 出口条件）

> Step 0.5 完成后，以下协议冻结，后续 Step 不得回改：

| 冻结项 | 冻结内容 | 文档位置 |
|--------|---------|---------|
| **Stream 事件映射** | PydanticAI 事件 → Data Stream Protocol SSE 的完整映射表 | `docs/plans/stream-event-mapping.md` |
| **Artifact 数据模型** | `Artifact` 结构：`artifact_type` + `content_format` + `content` + `resources` + `version` | Section 5.7.0 |
| **Artifact 字段命名** | 业务类型用 `artifact_type`（不改名为 kind），技术格式用 `content_format` | Section 5.7.0 |
| **ContentFormat 枚举** | `json` / `markdown` / `html`（仅当前支持的值） | Section 5.7.0 |

- [ ] **0.5.5** 将以上冻结项写入 `docs/plans/protocol-freeze-v1.md` 并存档

> 验收: 事件映射表已确认，Artifact 数据模型已冻结，stream_adapter.py 设计基于实测而非假定。

---

### Step 1: 搭建 Runtime 骨架 + 最小场景验证

> 目标: 跑通 quiz_generate 场景，native agent 自主调 tool，SSE 流式返回到前端。

#### 1.0 契约模板前置 — 工具从第一天起遵循统一契约

> **原则:** 先定契约模板，再写工具。所有工具从 Step 1.1 第一个迁移起就按统一契约返回，不等 Step 2.6 再回改。

以下 4 个契约模板必须在 Step 1.1 迁移工具**之前**定义完成：

- [ ] **1.0.1** 定义 `ToolResult` envelope 模板（6.5）
  - `ToolResult(data, artifact_type, content_format, action, status)` — 生成/RAG/写操作/澄清 tool 使用
  - 数据类 tool 直接返回 `{"status": "ok", ...}`
  - **Step 1.1 迁移的第一个 tool 就必须遵循此契约**
- [ ] **1.0.2** 定义 history 消息类型模板（6.6）
  - 4 种消息类型：`user` / `assistant` / `tool_call` / `tool_return`
  - `tool_call_id` 配对规则
  - conversation_store 接口契约
- [ ] **1.0.3** 定义 RAG 失败语义模板（6.7）
  - `status: "ok" | "no_result" | "error" | "degraded"`
  - Step 1.1.4 迁移 `search_teacher_documents` 时直接按此契约实现
- [ ] **1.0.4** 定义 mock 禁用规则模板（6.9）
  - 无 teacher_id → `{"status": "error"}`，不回退 mock
  - Step 1.1.3 迁移 `generate_quiz_questions` 时直接按此规则实现

> 验收: 4 个契约模板代码已定义（BaseModel / 接口签名 / 常量），后续所有 tool 迁移直接 import 使用。

#### 1.1 创建 `tools/registry.py` — 单一工具注册 + Toolset 分包

```python
# 设计思路：
# - 工具函数在 registry.py 中注册（@register_tool 装饰器收集）
# - 按职责分为 5 个 toolset：base_data / analysis / generation / artifact_ops / platform
# - NativeAgent 每轮按上下文选择 toolset 子集，通过 Agent(tools=subset) 注入
# - 废弃 TOOL_REGISTRY dict + FastMCP 双注册

# 重要：不使用 @agent.tool 绑定式装饰器（那会把 tool 绑死到单一 Agent 实例）
# 而是 registry 收集 → Agent constructor 注入，支持每轮动态选择 toolset
```

- [ ] **1.1.1** 定义 `@register_tool(toolset="generation")` 装饰器，从函数签名 + docstring 自动提取 schema，并标记所属 toolset
- [ ] **1.1.2** 实现 `registry.get_tools(toolsets=["generation"])` — 按 toolset 名返回 tool 子集
- [ ] **1.1.3** 迁移 `generate_quiz_questions` 为第一个 native tool（toolset=`generation`）
- [ ] **1.1.4** 迁移 `search_teacher_documents` (RAG tool, toolset=`platform`)
- [ ] **1.1.5** 编写 registry 单元测试：验证 schema 生成、toolset 过滤、tool 调用

> 验收: `registry.get_tools(toolsets=["generation", "platform"])` 返回 PydanticAI 兼容的 tool 子集。

#### 1.2 创建 `agents/native_agent.py` — 核心 Runtime

```python
# 设计思路：
# - 每轮根据上下文调用 registry.get_tools(toolsets) 获取 tool 子集
# - PydanticAI Agent(tools=subset) 构建（每轮新建，开销 < 1ms）
# - system prompt 只描述角色 + 能力范围 + tool 使用规则（参考 5.6）
# - 支持 run() (JSON) 和 run_stream() (SSE)
# - conversation_id 自动管理上下文
```

- [ ] **1.2.1** 实现 `NativeAgent` 类，含 `select_toolsets()` 宽松选择逻辑（参考 5.5）
- [ ] **1.2.2** 实现 `run_stream()` 方法：选择 toolset → 创建 Agent → `agent.run_stream()` + 事件迭代
- [ ] **1.2.3** 实现 `run()` 方法：选择 toolset → 创建 Agent → `agent.run()` 返回完整结果
- [ ] **1.2.4** 系统 prompt：角色定义 + 能力列表 + tool 使用规则（参考 5.6，含"高时效信息必须走工具"约束）
- [ ] **1.2.5** 上下文传递：`message_history` 从 conversation store 加载（成对截断，参考 6.6）
- [ ] **1.2.6** per-tool 超时：用 `asyncio.wait_for()` 包装 tool 执行（参考 6.2）

> 验收: `NativeAgent.run_stream("帮我出 5 道选择题")` 自动选择 generation toolset + 调用 `generate_quiz_questions` tool。

#### 1.3 创建 `services/stream_adapter.py` — 事件适配

```python
# 设计思路：
# - 将 PydanticAI 的 stream events 转为 DataStreamEncoder 格式
# - tool_call → tool-input-start / tool-input-available / tool-output-available
# - text_delta → text-delta
# - 保持前端 SSE 协议完全兼容
```

- [ ] **1.3.1** 基于 Step 0.5 校准结果实现 `adapt_stream()` 异步生成器：native event → SSE line
- [ ] **1.3.2** 处理 tool 调用事件映射
- [ ] **1.3.3** 处理文本流事件映射
- [ ] **1.3.4** 处理 artifact 输出事件映射（quiz JSON → artifact data event）

> 验收: 前端接收到的 SSE 事件格式与旧系统完全一致。

#### 1.4 原地重写 `api/conversation.py` — 薄网关

- [ ] **1.4.1** 将旧 `conversation.py` 重命名为 `conversation_legacy.py`（冻结副本，不再修改）
- [ ] **1.4.2** 新建 `conversation.py`，实现入口开关 `NATIVE_AGENT_ENABLED` 环境变量
  - `true`（默认）: 走 NativeAgent 新路径
  - `false`: `from api.conversation_legacy import router as legacy_router`，分流到冻结副本
  - 放在 `conversation.py` 顶层 if/else，不是装饰器、不是中间件
  - 同时保留 git 分支 `pre-native-rewrite` 作为完全回退点
- [ ] **1.4.3** 重写 `POST /api/conversation/stream` — SSE 流式端点，调用 NativeAgent
- [ ] **1.4.4** 重写 `POST /api/conversation` — JSON 端点，调用 NativeAgent
- [ ] **1.4.5** 请求模型复用 `ConversationRequest`（保持前端契约）
- [ ] **1.4.6** conversation_id 生命周期管理（含历史序列化，参考 6.6）

> 验收: `curl` 调用原端点，quiz_generate 场景端到端通过。端点路径不变，前端零改动。设置 `NATIVE_AGENT_ENABLED=false` 后可回退到旧逻辑。

#### 1.5 结构化日志 — 可观测性 Phase 1（6.10）

> Step 1 只做结构化日志（`logger.info(json.dumps({...}))`），不做聚合类。MetricsCollector 聚合 + `/api/metrics` 端点推迟到 Step 2+。

- [ ] **1.5.1** 在 `NativeAgent` 中每次 tool 调用/完成时输出结构化 JSON log
  - 字段: `tool_name`, `tool_status`, `latency_ms`, `turn_id`, `conversation_id`
- [ ] **1.5.2** 在每轮结束时输出 turn-level 汇总 log
  - 字段: `tool_call_count`, `total_latency_ms`, `token_usage_input`, `token_usage_output`
- [ ] **1.5.3** 日志格式统一为 JSON，便于后续接 Prometheus/Grafana

> 验收: 每次 conversation turn 结束后，日志中可看到 tool_call_count、latency_ms、token_usage（结构化 JSON 格式）。

#### 1.6 最小场景 E2E 验证

- [ ] **1.6.1** 验证场景 1: Quiz 生成 — "帮我出 5 道英语选择题"
- [ ] **1.6.2** 验证场景 2: Chat — "你好，你是谁"
- [ ] **1.6.3** 验证场景 3: RAG 问答 — "Unit 5 的教学重点是什么"
- [ ] **1.6.4** 对比旧系统输出，确保 SSE 协议兼容
- [ ] **1.6.5** 编写 `scripts/native_smoke_test.py` 自动化验证脚本

> 验收: 3 个场景全部通过，SSE 事件格式与旧系统一致。

#### 🔒 冻结点 2: History 序列化冻结（Step 1 出口条件）

> Step 1 完成后，history 序列化格式冻结，后续 Step 不得回改 store 接口。

- [ ] **1.7.1** `tool_call` / `tool_return` 成对序列化测试通过
  - 写入 10 条含 tool 调用的历史 → 读出 → 验证 `tool_call_id` 配对完整
  - 截断测试：截断后无孤立 `tool_call`（无对应 `tool_return`）
- [ ] **1.7.2** token 上限截断测试通过
  - 注入超过 `max_history_tokens`(16k) 的历史 → 截断 → 验证最近生成类 tool 对被保护
- [ ] **1.7.3** 多轮连续性测试通过
  - 3 轮对话（quiz 生成 → 修改 → 闲聊）→ 历史正确加载 → NativeAgent 上下文连续

| 冻结项 | 冻结内容 |
|--------|---------|
| **消息类型** | `user` / `assistant` / `tool_call` / `tool_return` 四种，不新增 |
| **配对规则** | `tool_call_id` 唯一标识，截断时原子保留或原子丢弃 |
| **store 接口** | `load_history(conversation_id)` / `save_history(conversation_id, messages)` 签名冻结 |

> 验收: history 序列化 + 截断 + 多轮连续性 3 组测试全部通过。后续 Step 2-4 不得修改 store 接口签名。

---

### Step 2: 工具全面收口

> 目标: 把所有业务动作做成 native tools，覆盖旧系统全部路径。

#### 2.1 数据类 Tools（对应旧 DataContract Phase A）

| Tool | 函数 | 说明 |
|------|------|------|
| `get_teacher_classes` | 已有 | 获取班级列表 |
| `get_class_detail` | 已有 | 获取班级详情 |
| `get_assignment_submissions` | 已有 | 获取作业提交记录 |
| `get_student_grades` | 已有 | 获取学生成绩 |

- [ ] **2.1.1** 将 4 个数据 tool 迁移到 `registry.py` 注册方式
- [ ] **2.1.2** 验证 LLM 能自主选择调用（给自然语言 → 自动选 tool）

#### 2.2 分析类 Tools（对应旧 ComputeGraph Phase B）

| Tool | 函数 | 说明 |
|------|------|------|
| `calculate_stats` | 已有 | 统计分析 |
| `compare_performance` | 已有 | 成绩对比 |
| `analyze_student_weakness` | 已有 | 薄弱点分析 |
| `get_student_error_patterns` | 已有 | 错题模式 |
| `calculate_class_mastery` | 已有 | 班级掌握度 |

- [ ] **2.2.1** 将 5 个分析 tool 迁移到 `registry.py`
- [ ] **2.2.2** 验证 LLM 能串联数据 + 分析（先 get_submissions → 再 calculate_stats）

#### 2.3 生成类 Tools（对应旧 Agent Path）

| Tool | 函数 | 说明 |
|------|------|------|
| `generate_quiz_questions` | 已有 | Quiz 首次生成 |
| `propose_pptx_outline` | 已有 | PPT 大纲 |
| `generate_pptx` | 已有 | PPT 生成 |
| `generate_docx` | 已有 | 文稿生成 |
| `render_pdf` | 已有 | PDF 渲染 |
| `generate_interactive_html` | 已有 | 互动内容 |
| `request_interactive_content` | 已有 | 互动请求 |

> **注意:** `refine_quiz_questions` 已删除，quiz 修改统一由 `artifact_ops` toolset 的 `patch_artifact` 处理（参考 5.7.5）。

- [ ] **2.3.1** 将 7 个生成 tool 迁移到 `registry.py`
- [ ] **2.3.2** 验证 content_create 场景（"帮我做一个 PPT"）

#### 2.4 平台操作类 Tools

| Tool | 函数 | 说明 |
|------|------|------|
| `save_as_assignment` | 已有 | 保存为作业 |
| `create_share_link` | 已有 | 创建分享链接 |
| `search_teacher_documents` | 已有 | RAG 文档检索 |

- [ ] **2.4.1** 迁移 3 个平台 tool
- [ ] **2.4.2** 验证 RAG 检索 → 问答链路

#### 2.5 新增：替代硬编码的 Tools

> 这些 tool 替代旧系统中硬编码的路由/解析/修改逻辑。

| Tool | 说明 | 替代的硬编码 |
|------|------|------------|
| `resolve_entity` | 实体解析（班级/学生/作业名 → ID） | `entity_resolver.py` 状态机 |
| `ask_clarification` | 向用户提出澄清问题 | confidence 阈值 + clarify handler |
| `build_report_page` | 构建数据分析报告页面 | Blueprint 三阶段流水线 |

**Artifact 编辑工具（`artifact_ops` toolset，参考 5.7）:**

| Tool | 说明 | 替代的硬编码 |
|------|------|------------|
| `get_artifact` | 获取当前 artifact 全文供 LLM 上下文理解 | 无（新能力） |
| `patch_artifact` | 对 artifact 执行结构化 patch 操作列表 | `patch_agent.py` 正则匹配 + `refine_quiz_questions` |
| `regenerate_from_previous` | patch 失败时带全文重新生成（降级路径） | 无（新能力） |

- [ ] **2.5.1** 实现 `resolve_entity` tool（封装现有 entity resolver 逻辑）
- [ ] **2.5.2** 实现 `ask_clarification` tool — 返回结构化 `ClarifyEvent`，不依赖文本推断（6.5）
- [ ] **2.5.3** 实现 `get_artifact` tool — 从 conversation store 获取 artifact 全文
- [ ] **2.5.4** 实现 `patch_artifact` tool — 接收 `PatchOp[]`，按 `content_format` 分发到对应 patcher adapter（5.7.2）
- [ ] **2.5.5** 实现 `regenerate_from_previous` tool — 携带前一版全文 + 用户指令，调对应 `generate_xxx` 重新生成
- [ ] **2.5.6** 实现 `build_report_page` tool（封装数据获取 + 分析 + 页面组装）
- [ ] **2.5.7** 全部 tool 注册到 `registry.py`，验证 schema 正确

> 验收: `registry.get_all_tools()` 返回完整的 25 个 tool（分属 5 个 toolset：base_data / analysis / generation / artifact_ops / platform），`registry.get_tools(toolsets=["generation", "artifact_ops"])` 正确返回子集。LLM 能根据自然语言自主选择 tool。

#### 2.6 Guardrail 验证：确认所有 tool 遵循 Step 1.0 契约

> 契约模板已在 Step 1.0 前置定义。此步骤**验证** Step 2 新增的全部 tool 是否遵循契约，非重新定义。

- [ ] **2.6.1** 验证结构化状态传递（6.5）
  - 全量扫描：所有 tool 返回值均携带 `status` 字段（生成类含 `artifact_type` + `content_format`）
  - 确认 0 处文本启发式状态判断代码残留
  - `stream_adapter.py` 从结构化字段生成 SSE 事件（不再扫描文本）

- [ ] **2.6.2** 验证 RAG 失败语义（6.7）
  - `search_teacher_documents` 返回 `status: "ok" | "no_result" | "error" | "degraded"`
  - LLM system prompt 明确：`status=error` 时不编造回答
  - 单元测试覆盖：engine 不可用、搜索无结果、部分降级 3 种场景

- [ ] **2.6.3** RAG 租户隔离（6.8）
  - `include_public` 默认改为 `False`
  - public 结果标注 `source: "public"`
  - tool docstring 写明跨库检索语义

- [ ] **2.6.4** 验证禁止生产 mock（6.9）
  - 全量扫描：所有数据 tool 无 teacher_id → `{"status": "error"}`（非 mock）
  - `_should_use_mock()` 仅在 `DEBUG=true` 时返回 True
  - 单元测试：`DEBUG=false` 时确认 0 处 mock 输出

- [ ] **2.6.5** Metrics 断言（6.10）
  - 每个 tool 迁移完成后，验证 metrics 可采集
  - Golden conversations 增加 metrics 断言（tool_call_count 范围、无 error status）

> 验收:
> - `grep -r "clarify.*in.*lower\|_detect_artifact_type_from_intent" agents/ api/ tools/` 返回 0 结果（无文本启发式）
> - `_should_use_mock()` / `_mock_*()` 函数仅存在于 `if settings.debug:` 分支内，生产路径 (`DEBUG=false`) 不可触达 mock — 通过单元测试验证，非 grep 计数

#### 🔒 冻结点 3: Toolset 策略冻结（Step 2 出口条件）

> Step 2 完成后，toolset 选择策略冻结，禁止引入排他分类路由。

| 冻结项 | 冻结内容 |
|--------|---------|
| **选择策略** | 宽松包含式（5.5），误包含代价低于误排除 |
| **5 个 toolset** | `base_data` / `analysis` / `generation` / `artifact_ops` / `platform` — 不新增不合并 |
| **始终注入** | `base_data` + `platform` 始终注入，不可条件化 |
| **禁止排他** | `select_toolsets()` 不得包含 `if intent == X: return [only_Y]` 式排他逻辑 |

- [ ] **2.7.1** Code review 验证 `select_toolsets()` 无排他分支
- [ ] **2.7.2** 单元测试：任何消息输入至少返回 `["base_data", "platform"]`（2 个始终 toolset）
- [ ] **2.7.3** 25 个 tool 全部注册到正确的 toolset，`registry.get_all_tools()` 通过

> 验收: toolset 策略锁定。Step 3 如果出现场景失败，只允许调整 `_might_generate()` / `_might_modify()` 关键词列表（宽松方向），不允许引入排他 router。

---

### Step 3: 全场景回归 + 行为级验证

> 目标: 所有场景通过新 runtime 运行。`NATIVE_AGENT_ENABLED=true` 为默认状态。

#### 3.1 场景回归测试

| 场景 | 描述 | 验收标准 |
|------|------|---------|
| S1 | Chat 闲聊 | 正常回复，LLM 自主决定是否调 tool（不硬编码"闲聊=禁用工具"） |
| S2 | Chat QA (RAG) | 自动调 `search_teacher_documents` |
| S3 | Quiz 生成 | 自动调 `generate_quiz_questions`，artifact 协议正确 |
| S4 | Quiz 修改 | 自动调 `get_artifact` → `patch_artifact`，在已有产物上结构化修改（5.7） |
| S5 | PPT 生成 | 自动调 `propose_pptx_outline` → `generate_pptx` |
| S6 | 文稿生成 | 自动调 `generate_docx` |
| S7 | 互动内容 | 自动调 `request_interactive_content` |
| S8 | 数据分析报告 | 自动调 `build_report_page` (内部串联 data + compute) |
| S9 | 实体解析 | 自动调 `resolve_entity`，缺信息时调 `ask_clarification` |
| S10 | 多轮对话 | conversation_id 上下文连续 |
| S11 | 跨意图切换 | 同一对话内从 chat → quiz → 修改，无错乱 |

- [ ] **3.1.1** 编写 `scripts/native_full_regression.py` 自动化回归脚本
- [ ] **3.1.2** S1-S11 全部通过
- [ ] **3.1.3** 对比旧系统指标：成功率 >= 旧系统
- [ ] **3.1.4** P95 latency <= 旧系统 * 1.2（20% 容差）

#### 3.2 Golden Conversations 行为级回归

> 不只看通过率，要验证**行为正确性**：调了哪些 tool、顺序是否合理、事件是否完整。

- [ ] **3.2.1** 整理 20-30 条 golden conversations 固定测试集
  - 覆盖：单轮、多轮、澄清链路、修改链路、跨意图切换
  - 格式：`tests/golden/gc_001_quiz_basic.json` ... `gc_030_cross_intent.json`
- [ ] **3.2.2** 每条 golden conversation 记录预期行为断言：
  - `expected_tools`: 应调用的 tool 列表（有序）
  - `expected_tool_count`: tool 调用次数范围
  - `expected_events`: 必须出现的 SSE 事件类型
  - `expected_artifact_type`: 最终产物业务类型（quiz / ppt / doc / interactive / none）— 来自结构化字段（6.5）
  - `expected_content_format`: 最终产物技术格式（json / markdown / html / none）— 与 `artifact_type` 配对验证（5.7.0）
  - `forbidden_events`: 不应出现的事件（如意外 clarify）
  - `expected_tool_status`: 所有 tool 返回 `status != "error"`（6.7/6.9）
  - `metrics_bounds`: tool_call_count 范围、total_latency 上限（6.10）
- [ ] **3.2.3** 编写 `scripts/golden_conversation_runner.py` 自动化执行 + 断言
- [ ] **3.2.4** 全部 golden conversations 通过

> 验收: 20-30 条 golden conversations 100% 通过，行为断言全部命中。

**示例 golden conversation:**
```json
{
  "id": "gc_003_quiz_then_modify",
  "name": "Quiz 生成 + 修改",
  "context": {"teacherId": "t-001", "classId": "c-001"},
  "turns": [
    {"role": "user", "message": "帮我出 5 道英语语法选择题"},
    {"role": "user", "message": "把第 3 题改成填空题"}
  ],
  "assertions": {
    "turn_0": {
      "expected_tools": ["generate_quiz_questions"],
      "expected_artifact_type": "quiz",
      "expected_content_format": "json",
      "expected_events": ["tool-input-start", "tool-output-available", "artifact"],
      "expected_tool_status": "ok",
      "metrics_bounds": {"tool_call_count": [1, 3], "total_latency_ms": [0, 60000]}
    },
    "turn_1": {
      "expected_tools": ["get_artifact", "patch_artifact"],
      "expected_artifact_type": "quiz",
      "expected_content_format": "json",
      "forbidden_events": ["clarify"],
      "expected_tool_status": "ok"
    }
  }
}
```

---

### Step 4: 删除旧代码 + 清理

> 目标: 一次性移除所有旧编排代码，代码库瘦身。Step 1 已在 git 创建 `pre-native-rewrite` 分支作为紧急回退。

#### 4.1 删除文件清单

| 操作 | 文件 |
|------|------|
| DELETE | `agents/router.py` |
| DELETE | `agents/executor.py` |
| DELETE | `agents/resolver.py` |
| DELETE | `agents/patch_agent.py` |
| DELETE | `agents/chat_agent.py` |
| DELETE | `config/prompts/router.py` |
| DELETE | `services/entity_resolver.py` |
| DELETE | `api/conversation_legacy.py`（Step 1.4 的冻结副本，回退开关不再需要） |
| DELETE | `skills/quiz_skill.py` (**前提:** Step 2.3 已将核心逻辑迁移到 `tools/quiz_tools.py`，确认 `generate_quiz_questions` tool 不再调用 skill 路径后方可删除) |
| REWRITE | `tools/__init__.py` → 仅 re-export `registry.py` |
| REWRITE | `agents/provider.py` → 删除 `execute_mcp_tool()`，保留 `create_model()` |

- [ ] **4.1.1** 删除上述文件
- [ ] **4.1.2** 清理所有 import 引用
- [ ] **4.1.3** 删除 `config/prompts/planner.py` + `config/prompts/router.py`（已被 `config/prompts/native_agent.py` 取代）

#### 4.2 清理配置

- [ ] **4.2.1** 删除 `router_model` + `executor_model` 配置（不再有独立的路由/执行模型）
- [ ] **4.2.2** 保留 `fast_model` tier 配置（用于统一 Agent 首次调用或低延迟场景，不叫 router_model）
- [ ] **4.2.3** 删除 convergence feature flags（`agent_unified_enabled` 等）
- [ ] **4.2.4** 更新 `.env.example`

#### 4.3 文档更新

- [ ] **4.3.1** 更新 `docs/architecture/overview.md`
- [ ] **4.3.2** 更新 `docs/architecture/agents.md`
- [ ] **4.3.3** 更新 `docs/api/current-api.md`
- [ ] **4.3.4** 更新 `docs/convergence/README.md` (标记 Phase 3+4 完成)
- [ ] **4.3.5** 更新 `CLAUDE.md` 项目指令

#### 4.4 最终验收

- [ ] **4.4.1** S1-S11 回归通过
- [ ] **4.4.2** Golden conversations 100% 通过
- [ ] **4.4.3** 代码无 dead import / unused code
- [ ] **4.4.4** `pytest tests/ -v` 全部通过

> 验收: 旧代码完全移除，测试通过。紧急回退：`git checkout pre-native-rewrite`。

---

## 5. 关键技术决策

### 5.1 PydanticAI vs Mistral Conversations API

| 方案 | 优势 | 劣势 |
|------|------|------|
| **PydanticAI Agent (推荐)** | 已在用、multi-provider、类型安全、tool 装饰器原生支持 | 无 conversation_id 持久化 |
| Mistral Conversations API | 原生 conversation_id、run_stream_async 自动循环 | 锁定 Mistral 单一 provider |

**决策:** 使用 **PydanticAI Agent** 作为 runtime，因为：
1. 项目已使用 PydanticAI，迁移成本低
2. 支持 Anthropic/OpenAI/Dashscope 多 provider
3. PydanticAI 原生支持 `Agent(tools=[...])` 构造注入和 `agent.run_stream()`
4. conversation 持久化由我们的 `conversation_store.py` 管理（已有）

Mistral Conversations API 作为备选，如果未来需要锁定 Mistral 专用能力。

### 5.2 Tool 注册方式：Registry 收集 + Agent Constructor 注入

**方案:** 工具在 `registry.py` 中注册，按需子集注入 `Agent(tools=[...])`。

**不使用** `@agent.tool` 绑定式装饰器 — 该方式把 tool 绑死到单一 Agent 实例，无法支持每轮动态选择 toolset。

```python
# tools/registry.py — 工具注册
from tools.registry import register_tool

@register_tool(toolset="generation")
async def generate_quiz_questions(
    ctx: RunContext[AgentContext],
    subject: str,
    count: int = 5,
    difficulty: str = "medium",
) -> QuizOutput:
    """Generate quiz questions for a given subject."""
    return await _generate_quiz_impl(subject, count, difficulty)

# agents/native_agent.py — 每轮动态创建 Agent
selected_tools = registry.get_tools(toolsets=selected_toolsets)
agent = Agent(
    model=create_model(),
    system_prompt=SYSTEM_PROMPT,
    tools=selected_tools,  # 注入 toolset 子集
)
result = await agent.run_stream(user_message, message_history=history)
```

> **性能说明:** 每轮 `Agent(tools=subset)` 新建实例。PydanticAI 中这是纯 Python 对象构建，开销极小（< 1ms），不影响延迟。

不再需要 FastMCP + TOOL_REGISTRY 双注册。一处定义即可。

### 5.3 Build Report 场景的处理

旧系统用 Blueprint 三阶段流水线（DataContract → ComputeGraph → UIComposition），这是最复杂的路径。

**策略:** 将整个流水线封装为一个 `build_report_page` tool：
- LLM 决定"需要生成报告"时调用此 tool
- tool 内部仍可使用 data_tools + stats_tools（但由 tool 自身编排，非 LLM）
- 返回完整的 page JSON
- 如果需要更细粒度的控制，可后续拆分为多个子 tool

这是一个"渐进式"策略：先封装为粗粒度 tool 保证功能，后续再拆分让 LLM 自主编排。

**拆分触发条件（明确量化，避免"以后再说"）:**
- Golden conversation S8（数据分析报告）通过率 < 90%
- 或报告生成 P95 latency > 45s（当前流水线太慢）
- 触发时拆分为：`fetch_report_data` → `compute_report_stats` → `compose_report_page` 三个子 tool

**RAG tool 拆分触发条件:**
- Golden conversation S2/S9 通过率 < 90%
- 或 top-k 结果噪声高（> 30% 无关结果）
- 触发时拆分为：`search_private_documents` / `search_public_documents` / `rerank_results`

### 5.4 前端协议兼容

前端消费的 SSE 协议 (Data Stream Protocol) **不变**。`stream_adapter.py` 负责事件映射。

> **重要:** 下表中的 PydanticAI 事件名是**占位符**。实际事件类型以 Step 0.5 校准结果为准。
> PydanticAI `StreamedRunResult` 实际可能产出 `TextPart` / `ToolCallPart` / `ToolReturnPart` 等类型，
> 与下表名称不同。**Step 0.5 完成后必须更新此表。**

```
PydanticAI stream event (待校准)  →  Data Stream Protocol SSE line
─────────────────────────────────────────────────────────────────
TextPart(content)                 →  {"type":"text-delta","delta":"..."}
ToolCallPart(name, args)          →  {"type":"tool-input-start",...}
ToolReturnPart(result)            →  {"type":"tool-output-available",...}
FinalResult / stream end          →  {"type":"finish","finishReason":"stop"}
```

### 5.5 Toolset 子集注入策略

**问题:** 全量 24 个 tool 注入单一 Agent 会导致 context 压力（tool schema 消耗 3k-5k tokens）和选择精度下降。

**策略:** 按职责分为 5 个 toolset，每轮根据上下文选择子集注入，控制在 8-12 个 tools/轮。

| Toolset | 包含的 Tools | 注入条件 |
|---------|-------------|---------|
| `base_data` | `get_teacher_classes`, `get_class_detail`, `get_assignment_submissions`, `get_student_grades`, `resolve_entity` | **始终注入** — 基础数据能力 |
| `analysis` | `calculate_stats`, `compare_performance`, `analyze_student_weakness`, `get_student_error_patterns`, `calculate_class_mastery` | `context.class_id` 存在，或消息涉及数据/成绩/分析 |
| `generation` | `generate_quiz_questions`, `propose_pptx_outline`, `generate_pptx`, `generate_docx`, `render_pdf`, `generate_interactive_html`, `request_interactive_content` | 消息涉及生成/创建 |
| `artifact_ops` | `get_artifact`, `patch_artifact`, `regenerate_from_previous` | 会话中有已生成 artifact，或消息涉及修改/编辑（参考 5.7） |
| `platform` | `save_as_assignment`, `create_share_link`, `search_teacher_documents`, `ask_clarification`, `build_report_page` | **始终注入** — 平台操作 + RAG + 澄清 |

**关键约束：宽松包含式选择，非排他分类式**

toolset 选择逻辑**必须是宽松包含式**，不是排他分类。误包含（多带几个 tool）的代价极低（仅多占少量 context），误排除（漏掉用户需要的 tool）的代价极高（功能不可用）。

```python
# agents/native_agent.py — toolset 选择逻辑
def select_toolsets(message: str, context: AgentContext) -> list[str]:
    """宽松包含式 toolset 选择。默认多包含，只排除明确无关的包。"""
    sets = ["base_data", "platform"]  # 始终包含

    # 宽松判断：可能需要生成 → 带上 generation
    if _might_generate(message):
        sets.append("generation")

    # 宽松判断：有已生成 artifact 或可能涉及修改 → 带上 artifact_ops
    if context.has_artifacts or _might_modify(message):
        sets.append("artifact_ops")

    # 宽松判断：有 class_id 或可能涉及数据 → 带上 analysis
    if context.class_id or _might_analyze(message):
        sets.append("analysis")

    return sets

def _might_generate(message: str) -> bool:
    """宽松判断是否可能需要生成类工具。误判为 True 代价低。"""
    keywords = ["出题", "生成", "做一个", "PPT", "文稿", "互动", "quiz", "create", "generate"]
    return any(kw in message for kw in keywords)

def _might_modify(message: str) -> bool:
    """宽松判断是否可能需要修改已有 artifact。"""
    keywords = ["修改", "改", "换", "删", "移动", "调整", "update", "change", "edit", "revise"]
    return any(kw in message for kw in keywords)

def _might_analyze(message: str) -> bool:
    """宽松判断是否可能需要分析类工具。"""
    keywords = ["成绩", "分析", "统计", "对比", "薄弱", "错题", "掌握", "report", "数据"]
    return any(kw in message for kw in keywords)
```

> **与"零路由规则"的区别:** 旧 RouterAgent 做排他分类（"这是 quiz_generate 意图 → 只走 quiz 路径"）。
> 新的 toolset 选择做宽松包含（"可能需要生成 → 加载 generation 包，LLM 自己决定用不用"）。
> 路由规则决定**唯一路径**，toolset 选择决定**可用能力范围** — 最终选哪个 tool 仍由 LLM 自主决定。

### 5.6 Tool 调用策略：LLM 自主决定，禁止按意图分类抑制

**核心原则:** 所有请求先由 LLM（作为 Principal Agent）判断是否需要调用工具。不按 chat/quiz/report 分类启用或禁用工具，而是按"是否需要外部事实或执行动作"由 LLM 自主决定。

#### 5.6.1 删除"闲聊模式 = 不调工具"的语义

**硬约束:** 文档和代码中禁止出现"chat 场景不调用 tool"的语义。

| 旧方式（禁止） | 新方式（必须） |
|---------------|---------------|
| S1 Chat 闲聊 → 验收标准"无 tool 调用" | S1 Chat 闲聊 → LLM 自主决定是否调 tool |
| `if intent == "chat": skip_tools()` | 不存在此分支，LLM 有完整 toolset 可用 |
| 闲聊时硬编码跳过 tool loop | LLM 判断不需要外部信息时自然不调 tool |

**原因:**
- 用户说"你好"→ 不需要 tool，LLM 自然直接回复（这是 LLM 的能力，不需要代码强制）
- 用户说"今天天气怎么样"→ 看似闲聊，但需要外部信息，应调 tool
- 用户说"帮我看看三班最近成绩"→ 看似 chat，但需要数据 tool
- **不应该由代码分类"这是闲聊"来决定是否禁用工具**

#### 5.6.2 高时效信息必须走外部工具

**硬约束:** 对于需要实时/外部事实的问题（天气、新闻、价格、时间敏感数据等），LLM **必须** 调用相应工具获取信息，不允许纯凭训练数据回答。

| 问题类型 | 要求 | 说明 |
|---------|------|------|
| 实时信息（天气、新闻、股价） | **必须调 tool** | system prompt 明确：对时效性问题不要用训练数据回答 |
| 学生数据（成绩、提交记录） | **必须调 tool** | 这些数据只存在于后端 API，不可能在训练数据中 |
| 教学文档内容 | **必须调 RAG tool** | 文档内容在向量库中，需通过 `search_teacher_documents` 获取 |
| 通用知识（英语语法规则、数学公式） | 可直接回答 | 训练数据中有充分覆盖的知识 |
| 平台操作（保存、分享） | **必须调 tool** | 需要执行后端写操作 |

**System prompt 中的规则（写入 `config/prompts/native_agent.py`）:**

```
你是教育 AI 助手。以下是你的工具使用规则：

1. 你有一组可用工具。对于每个用户请求，自主判断是否需要调用工具。
2. 涉及学生数据、成绩、作业提交等信息时，必须通过数据工具获取，不可编造。
3. 涉及教学文档内容时，必须通过 search_teacher_documents 检索，不可凭记忆回答。
4. 涉及实时信息（天气、新闻等当前事实）时，必须通过相应工具获取，不可用训练数据回答。
5. 对于通用知识（语法规则、数学公式等），可以直接回答。
6. 当工具返回 status="error" 时，如实告知用户服务暂不可用，不可编造替代答案。
7. 不确定是否需要工具时，优先调用工具确认，而非猜测回答。
```

> **与 toolset 选择的关系:** Section 5.5 决定"Agent 有哪些工具可用"，Section 5.6 决定"Agent 在什么情况下应该使用工具"。前者是能力范围，后者是行为规则。两者互补，不冲突。

### 5.7 统一 Artifact 模型：生成专用、编辑通用、渲染适配

**核心原则:** 生成用专用工具（`generate_quiz_questions`, `generate_pptx`, ...），编辑用通用 `patch_artifact`，渲染/导出用适配器。避免为每种 artifact 类型拆出 `revise_xxx` 工具导致工具爆炸。

#### 5.7.0 Artifact 数据模型

用 `artifact_type` 表达业务对象，用 `content_format` 表达技术载体，资源用 `resources` 做索引而不是强制拆文件。

```python
class Artifact(BaseModel):
    artifact_id: str                          # 唯一标识
    artifact_type: str                        # 业务对象类型（见下方枚举）
    content_format: ContentFormat             # 技术载体格式（见下方枚举）
    content: Any                              # 主体内容（格式由 content_format 决定）
    resources: list[ArtifactResource] = []    # 关联资源索引（可选）
    version: int = 1                          # 版本号（一轮对话 = 一个版本）

class ContentFormat(str, Enum):
    """当前支持的内容格式。仅声明已实现的格式，新增时扩展此枚举。"""
    JSON = "json"           # 结构化数据（quiz 题目、PPT slide 数组等）
    MARKDOWN = "markdown"   # 文本文档
    HTML = "html"           # 互动内容、Web Canvas

class ArtifactResource(BaseModel):
    """Artifact 关联资源。避免强制拆文件，资源挂索引即可。"""
    id: str                                                # 在 content 中的引用 key
    storage: Literal["inline", "attached", "external"]     # 存储方式
    mime_type: str | None = None                           # "image/png", "application/javascript"
    url: str | None = None                                 # attached/external 时的地址
    data: str | None = None                                # inline 时的 base64 内容
```

**分发逻辑：**

```
生成时：dispatch on artifact_type → generate_quiz / generate_pptx / ...
编辑时：dispatch on content_format → json_patcher / markdown_patcher / html_patcher
展示时：dispatch on artifact_type → quiz_renderer / ppt_renderer / ...
```

> **关键解耦:** `artifact_type` 决定业务语义（生成工具选择、UI 展示、可编辑性查表），`content_format` 决定技术操作（patch 适配器分发、序列化策略）。两个维度独立变化。

**各 artifact_type 对应的 content_format:**

| artifact_type | content_format | content 示例 | 说明 |
|--------------|----------------|-------------|------|
| `quiz` | `json` | `{questions: [{type, stem, options, answer}]}` | 教育域专用 kind |
| `ppt` | `json` | `[{layout, title, body, notes}]` | JSON slide 数组，导出时由 python-pptx 转 .pptx |
| `doc` | `markdown` | `"# Unit 5\n..."` | Markdown 文稿 |
| `interactive` | `html` | `"<div class='game'>...</div>"` | 互动内容 |
| `web_canvas` | `html` | 富内容 HTML | v1 不开放，标记 future |
| `image` | — | 无 working content | 仅 regen-only，不存 content |

**resources 使用场景举例:**

| 场景 | resources |
|------|-----------|
| Quiz 带图片 | `[{id: "img-1", storage: "attached", url: "oss://...", mime_type: "image/png"}]` |
| PPT 带图表 | `[{id: "chart-1", storage: "inline", data: "base64...", mime_type: "image/svg+xml"}]` |
| 互动引用外部 JS | `[{id: "lib-1", storage: "external", url: "https://cdn.../lib.js"}]` |
| 纯文本 quiz | `[]`（空） |

#### 5.7.1 可编辑性矩阵

| artifact_type | content_format | 编辑能力 | 说明 |
|--------------|----------------|---------|------|
| `quiz` | `json` | **Full** | 替换题目文本、插入/删除/移动题目、改题型、改选项 — 全部通过 `patch_artifact` |
| `ppt` | `json` | **Partial** | 替换文本、改标题、改配色 → patch；重新排版 → regenerate |
| `interactive` | `html` | **Full** | HTML 互动内容，支持结构化 patch |
| `web_canvas` | `html` | **Full（v1 不开放）** | 架构支持，v1 暂不暴露给用户 |
| `doc` | `markdown` | **Regen-only（v1）** | v1 仅重新生成，不支持局部 patch |
| `image` | — | **Regen-only** | 无 working content，修改 = 重新生成 |

#### 5.7.2 `artifact_ops` Toolset — 新增工具

| Tool | 签名 | 说明 |
|------|------|------|
| `get_artifact` | `(artifact_id: str) -> ArtifactData` | 获取当前 artifact 全文（供 LLM 理解上下文后决定操作） |
| `patch_artifact` | `(artifact_id: str, operations: list[PatchOp]) -> PatchResult` | 对 artifact 执行结构化 patch 操作列表（按 `content_format` 分发到对应 patcher） |
| `regenerate_from_previous` | `(artifact_id: str, instruction: str) -> ArtifactData` | patch 失败或不可 patch 时的降级路径，带上前一版全文重新生成 |

**`PatchOp` 操作类型:**

```python
class PatchOp(BaseModel):
    """LLM 生成的结构化 patch 操作。"""
    op: Literal[
        "replace_text",        # 替换指定位置的文本
        "insert_block",        # 在指定位置插入新块（题目、段落、幻灯片等）
        "delete_block",        # 删除指定位置的块
        "move_block",          # 移动块到新位置
        "set_style",           # 设置样式属性（颜色、字体大小等）
        "replace_media",       # 替换媒体资源（图片、音频）
        "transform_structure", # 结构变换（如选择题 → 填空题）
    ]
    target: str               # 目标定位（如 "questions[2]", "slides[0].title"）
    value: Any = None         # 操作值（op 类型决定 schema）
```

#### 5.7.3 编辑 vs 重新生成决策

**由 LLM 自主判断**，不硬编码规则：

- LLM 收到修改请求后，先调 `get_artifact` 获取当前内容
- 根据可编辑性矩阵（写入 system prompt）和修改复杂度，自主决定：
  - **小改**（改文本、换题目、调顺序）→ 调 `patch_artifact`
  - **大改**（改题型、改整体结构、不可 patch 类型）→ 调对应 `generate_xxx` 重新生成
- 如果 `patch_artifact` 执行失败（操作冲突、结构不兼容）→ 自动 fallback 到 `regenerate_from_previous`

#### 5.7.4 版本管理

| 规则 | 说明 |
|------|------|
| **一轮 = 一版** | 一轮对话中多次 `patch_artifact` 调用合并为一个版本快照 |
| **无 undo** | 不提供撤回功能。用户想改回去 → 再发一条修改请求 |
| **Publish / Preview** | v1 不做，artifact 生成后即为最终态 |
| **Fallback 带全文** | `regenerate_from_previous` 携带前一版 artifact 全文作为 context，确保 LLM 不丢失已有内容 |

#### 5.7.5 与现有工具的关系

| 旧工具 | 处理方式 |
|--------|---------|
| `refine_quiz_questions` | **删除** — 被 `patch_artifact(artifact_id, ops)` 取代 |
| `modify_artifact`（Step 2.5 原计划） | **取消** — 不再需要，被 `patch_artifact` 统一取代 |
| `generate_quiz_questions` | **保留** — 首次生成仍用专用工具 |
| `generate_pptx` / `generate_docx` / ... | **保留** — 首次生成 + regen-only 场景复用 |

> **设计目标:** 避免为每种 artifact 做特例。新增 artifact 类型时，只需：
> 1. 新增一个 `generate_xxx` 工具
> 2. 在可编辑性矩阵中声明 patch 能力等级
> 3. `patch_artifact` 内部增加一个 adapter — 无需新增 `revise_xxx` 工具

---

## 6. 工程硬约束

### 6.1 Tool 权限边界

每个 tool 必须在 `RunContext` 中校验权限，防止越权访问。

| 约束 | 实现方式 |
|------|---------|
| **teacher 隔离** | `ctx.deps.teacher_id` 必传，tool 内部过滤数据范围 |
| **session 绑定** | `ctx.deps.conversation_id` 标识会话，防止跨会话数据泄漏 |
| **只读 vs 写入** | 数据类 tool 只读；`save_as_assignment`, `create_share_link` 需写入确认 |

```python
@register_tool(toolset="base_data")
async def get_assignment_submissions(
    ctx: RunContext[AgentDeps],
    class_id: str,
    assignment_id: str,
) -> dict:
    """Fetch submissions for a specific assignment."""
    # 硬约束：必须校验 teacher 权限
    return {"status": "ok", "submissions": await data_api.get_submissions(
        teacher_id=ctx.deps.teacher_id,  # 不可省略
        class_id=class_id,
        assignment_id=assignment_id,
    )}
```

### 6.2 超时 / 重试 / 幂等

| 约束 | 默认值 | 说明 |
|------|--------|------|
| **单次 tool 超时** | 30s | 超时后返回 `ToolTimeoutError`，LLM 可重试或换策略 |
| **tool 重试次数** | 2 | 仅对可重试错误（网络超时、5xx），4xx 不重试 |
| **幂等性** | 读 tool 天然幂等；写 tool 需幂等 key | `save_as_assignment` 用 `(teacher_id, content_hash)` 去重 |
| **总请求超时** | 120s | 整个 conversation turn 的硬上限 |

> **实现说明:** PydanticAI 不原生提供 per-tool timeout。需在 `native_agent.py` 中用 `asyncio.wait_for(tool_func(...), timeout=30)` 包装每次 tool 执行。超时时捕获 `asyncio.TimeoutError` 并转为 `ToolTimeoutError` 返回给 LLM context。

### 6.3 Token / 调用预算

| 约束 | 默认值 | 超限行为 |
|------|--------|---------|
| **max_tool_calls** | 10 | 超限后强制停止 tool loop，返回当前已有结果 + 提示 |
| **max_total_tokens** | 32k (input) + 8k (output) | 触发时截断历史，保留最近 N 轮 |
| **max_turn_duration** | 120s | 超时返回 partial result + error event |
| **max_retries** (agent) | 2 | PydanticAI Agent 级别的结构化输出重试 |

### 6.4 失败分级

| 级别 | 类型 | 处理方式 | 用户体验 |
|------|------|---------|---------|
| **L1 - Tool Fail** | 单个 tool 调用失败（数据 API 不可达、参数错误） | tool 返回错误信息给 LLM，LLM 自主决定重试或换策略 | 用户可能看到"正在重试" |
| **L2 - Model Fail** | LLM 调用失败（provider 超时、rate limit） | fallback 到备选 model（`create_model_with_fallback`） | 用户无感或略有延迟 |
| **L3 - Protocol Fail** | SSE 事件格式错误、stream 中断 | stream_adapter 捕获 + 发送 error event + 关闭连接 | 前端显示错误提示 |
| **L4 - Budget Exceeded** | max_tool_calls / max_tokens / timeout 超限 | 强制停止 + 返回 partial result | 前端显示"结果可能不完整" |
| **L5 - System Fail** | 未捕获异常、OOM | 全局异常处理 → 500 + error event | 前端显示系统错误 |

```python
# stream_adapter.py 中的失败处理
async def adapt_stream(native_stream, enc: DataStreamEncoder):
    try:
        async for event in native_stream:
            yield _map_event(event, enc)
    except ToolTimeoutError as e:
        yield enc.error(f"Tool timeout: {e.tool_name}")
    except BudgetExceededError as e:
        yield enc.text_delta(tid, f"\n\n[结果可能不完整：{e.reason}]")
    except Exception as e:
        logger.exception("Unexpected error in stream")
        yield enc.error(str(e))
    finally:
        yield enc.finish("error" if error_occurred else "stop")
```

### 6.5 状态判断：结构化事件，禁止文本启发式

**现状问题:** 旧代码用字符串匹配推断会话状态（`conversation.py:365-368`）：

```python
# 危险：用文本包含判断 clarify 状态
lower_text = streamed_text.lower()[:300]
if "clarify_needed" in lower_text or "clarify" in lower_text:
    effective_action = "clarify_needed"
```

以及用关键词推断产物类型（`conversation.py:1838-1857`）：

```python
# 危险：用文本关键词推断 artifact type
if "互动" in lower or "interactive" in lower:
    return "interactive"
if "ppt" in lower or "演示" in lower:
    return "pptx"
```

**硬约束:** 新架构禁止文本启发式状态判断。所有状态通过**结构化返回**传递：

| 状态 | 旧方式（禁止） | 新方式（必须） |
|------|---------------|---------------|
| Clarify | 文本包含 `"clarify"` | `ask_clarification` tool 返回结构化 `ClarifyEvent` |
| Artifact type | 关键词匹配 `"ppt"/"互动"` | tool 返回值携带 `artifact_type` 字段 |
| Action | 字符串赋值 `"clarify_needed"` | `AgentDeps.current_action` 枚举值 |

**ToolResult 分层约定 — 不是所有 tool 都需要包 envelope:**

| Tool 类型 | 返回方式 | 示例 |
|----------|---------|------|
| **数据类 tool** | 直接返回业务数据（dict/list） | `get_teacher_classes` → `{"status": "ok", "classes": [...]}` |
| **分析类 tool** | 直接返回分析结果 | `calculate_stats` → `{"status": "ok", "stats": {...}}` |
| **生成/修改类 tool** | 必须返回 ToolResult envelope | `generate_quiz` → `ToolResult(data=quiz, artifact_type="quiz", content_format="json")` |
| **RAG tool** | 必须返回带 status 的 envelope | `search_teacher_documents` → `{"status": "ok\|no_result\|error", ...}` |
| **写操作 tool** | 必须返回 ToolResult envelope | `save_as_assignment` → `ToolResult(data=result, action="complete")` |
| **澄清 tool** | 必须返回结构化 ClarifyEvent | `ask_clarification` → `ClarifyEvent(question=..., options=[...])` |

```python
# 仅生成/RAG/写操作/澄清 tool 使用 envelope
class ToolResult(BaseModel):
    data: Any
    artifact_type: str | None = None     # "quiz" / "ppt" / "doc" / "interactive" / None（5.7.0）
    content_format: str | None = None    # "json" / "markdown" / "html" / None（5.7.0）
    action: str = "complete"             # "complete" / "clarify" / "partial"
    status: str = "ok"                   # "ok" / "error" / "partial"

# 数据类 tool 可直接返回（仍需携带 status 字段）
async def get_teacher_classes(...) -> dict:
    return {"status": "ok", "classes": [...]}
```

> **判断规则:** 如果 tool 的返回需要触发 SSE 特殊事件（artifact、clarify）或需要 stream_adapter 做状态判断，就必须用 ToolResult envelope。纯数据查询直接返回 dict。

### 6.6 会话历史序列化与截断

**存储格式:** `conversation_store.py` 存储 4 种消息类型：

| 类型 | 说明 | 序列化字段 |
|------|------|-----------|
| `user` | 用户消息 | `role`, `content`, `timestamp` |
| `assistant` | LLM 文本回复 | `role`, `content`, `timestamp` |
| `tool_call` | LLM 发起的 tool 调用 | `role`, `tool_call_id`, `tool_name`, `arguments`, `timestamp` |
| `tool_return` | tool 执行结果 | `role`, `tool_call_id`, `tool_name`, `result`, `status`, `timestamp` |

**成对截断规则 — tool_call 和 tool_return 原子保留:**

| 约束 | 说明 |
|------|------|
| **原子对** | `tool_call` 和对应的 `tool_return` 必须通过 `tool_call_id` 配对，截断时整对保留或整对丢弃 |
| **禁止残缺** | 不允许出现只有 `tool_call` 没有 `tool_return` 的历史（LLM 会困惑于未完成的调用） |
| **截断方向** | 从最早的轮次开始丢弃，保留最近 N 轮 |
| **最大轮数** | 默认保留最近 20 轮（可配置） |
| **token 上限** | 历史 token 总量超过 `max_history_tokens`（默认 16k）时触发截断 |
| **关键 tool 对保护** | 最近一次生成类 tool 调用对（如 `generate_quiz_questions`）始终保留，即使超出轮数限制 |

```python
# services/conversation_store.py — 截断逻辑示例
def truncate_history(messages: list[Message], max_turns: int = 20, max_tokens: int = 16000) -> list[Message]:
    # 1. 按 tool_call_id 分组，确保 call/return 成对
    # 2. 从最早轮次开始丢弃，直到满足 max_turns 和 max_tokens
    # 3. 保护最近一次生成类 tool 对
    ...
```

### 6.7 RAG 失败语义：区分"无结果"与"系统故障"

**现状问题:** `document_tools.py:58-60` 把异常降级为空结果：

```python
except Exception as exc:
    return {"query": query, "results": [], "total": 0, "error": str(exc)}
    # LLM 无法区分"确实没资料"与"系统故障"
```

**硬约束:** Tool 返回必须携带 `status` 字段，LLM 可据此决定行为：

| status | 含义 | LLM 行为 |
|--------|------|---------|
| `"ok"` | 正常返回（可能 0 条结果） | 基于结果回答 |
| `"no_result"` | 检索正常但无匹配 | 告知用户"未找到相关资料" |
| `"error"` | 系统故障（RAG 引擎不可用、网络超时） | 告知用户"知识库暂不可用"，不编造回答 |
| `"degraded"` | 部分能力不可用（如 public 库不可达，仅返回 private） | 标注来源受限 |

```python
# 新方式
async def search_teacher_documents(...) -> dict:
    try:
        engine = get_rag_engine()
    except RuntimeError:
        return {"status": "error", "reason": "RAG engine not initialized", "results": []}

    results = await engine.search(...)
    if not results:
        return {"status": "no_result", "query": query, "results": []}
    return {"status": "ok", "query": query, "results": results, "total": len(results)}
```

### 6.8 租户隔离：RAG include_public 默认策略

**现状问题:** `document_tools.py:19` 默认 `include_public=True`，若 public 库治理不严会混入非预期内容。

**硬约束:**

| 规则 | 说明 |
|------|------|
| 默认 `include_public=False` | 新系统默认只搜 private，LLM 可选择传 `True` 扩大范围 |
| public 结果必须标注来源 | 返回值中 `source: "public"` / `source: "private"` 区分 |
| tool 描述明确语义 | docstring 写明：`include_public=True` 会搜公共库，结果可能含非本校内容 |

### 6.9 Mock 回退：生产环境禁止静默 mock

**现状问题:** `data_tools.py:92,121,151,181` 在 `teacher_id` 为空或 API 失败时静默回退到 mock 数据：

```python
if _should_use_mock() or not teacher_id:
    return _mock_teacher_classes(teacher_id)  # 生产环境看到"假数据"
```

**硬约束:**

| 环境 | mock 行为 |
|------|----------|
| **开发/测试** (`DEBUG=true`) | 允许 mock，日志 WARNING |
| **生产** (`DEBUG=false`) | **禁止 mock**，缺 teacher_id 直接返回 `{"status": "error", "reason": "teacher_id required"}` |
| **API 失败** | 返回 `{"status": "error"}` 而非 mock，LLM 可告知用户"数据服务暂不可用" |

```python
# 新方式
async def get_teacher_classes(ctx: RunContext[AgentDeps], ...) -> dict:
    teacher_id = ctx.deps.teacher_id
    if not teacher_id:
        return {"status": "error", "reason": "teacher_id is required"}
    try:
        classes = await data_api.list_classes(teacher_id)
        return {"status": "ok", "classes": classes}
    except Exception as e:
        if settings.debug:
            return _mock_teacher_classes(teacher_id)  # 仅开发环境
        return {"status": "error", "reason": str(e)}
```

### 6.10 可观测性：分阶段 metrics 落地

| 指标 | 采集点 | 用途 |
|------|--------|------|
| `tool_call_count` | per tool, per turn | 检测 tool loop 是否收敛 |
| `tool_success_rate` | per tool | 发现不稳定的 tool |
| `tool_latency_p50/p95` | per tool | 性能基线 |
| `clarify_rate` | per conversation | 检测是否过度 clarify |
| `model_fallback_count` | per turn | 监控 provider 健康度 |
| `budget_exceeded_count` | per turn | 检测预算是否设得太紧 |
| `artifact_type_distribution` | per conversation | 使用模式分析 |
| `token_usage` | per turn (input + output) | 成本追踪 |
| `toolset_selection` | per turn | 追踪每轮选择了哪些 toolset |

**分阶段落地:**

| 阶段 | 交付物 | 说明 |
|------|--------|------|
| **Step 1** | 结构化 JSON log | `logger.info(json.dumps({tool_name, status, latency_ms, ...}))` — 最小可行 |
| **Step 2** | MetricsCollector 聚合类 | 内存聚合 P50/P95、成功率，支持 turn-level 汇总 |
| **Step 2+（可选）** | `GET /api/metrics` 端点 | 调试用 HTTP 端点，后续可接 Prometheus |

**硬约束:**
- Step 1 完成时 metrics 必须可通过结构化日志采集
- Step 2 MetricsCollector 是 guardrail 2.6.5 的前置依赖
- Step 3 Golden conversations 必须断言关键 metrics（如 tool_call_count 在预期范围内）

---

## 6.11 风险与回退

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM 选错 tool | 用户体验降级 | tool 描述精准 + golden conversations 行为回归 |
| Tool calling latency 增加 | P95 劣化 | 使用 `fast_model` tier 做首次调用（`get_model_for_tier("fast")`） + max_tool_calls 上限 |
| 多轮 tool 循环不收敛 | 超时 | max_tool_calls=10 + max_turn_duration=120s 双保险 |
| 前端 SSE 不兼容 | 前端报错 | stream_adapter 单元测试 + golden conversations 事件断言 |

**回退策略:**
- **快速回退:** 设置 `NATIVE_AGENT_ENABLED=false`，入口开关分流到 `conversation_legacy.py` 冻结副本（秒级生效，无需重启部署）
- **完全回退:** `git checkout pre-native-rewrite` 分支（仅在入口开关不足以解决问题时使用）
- **不做长期双轨维护** — 入口开关仅用于紧急回退，不做 A/B 测试或灰度发布

---

## 7. 验收标准

### 功能验收

| 指标 | 标准 | 测量方式 |
|------|------|---------|
| 场景通过率 | >= 旧系统（目标 100%） | S1-S11 自动化回归 |
| **Golden conversations** | **100% 通过**（20-30 条） | `scripts/golden_conversation_runner.py` |
| **行为正确性** | tool 调用列表 + 顺序 + 事件完整性全部命中 | golden conversation 断言 |

### 代码质量验收

| 指标 | 标准 | 测量方式 |
|------|------|---------|
| 无手工 tool 循环 | 代码中 0 处 `while`+`tool_calls` 模式 | `grep -r "tool_calls" agents/` |
| 无 intent 阈值/关键词 | 代码中 0 处 confidence/regex 路由 | `grep -r "confidence\|_QUIZ.*KEYWORDS" agents/` |
| 无文本启发式状态判断 | 代码中 0 处文本扫描推断 action/artifact | `grep -r "clarify.*in.*lower\|_detect_artifact_type_from_intent" api/ agents/` |
| 无生产 mock 回退 | `DEBUG=false` 时 0 处 mock 输出 | 单元测试 `test_no_mock_in_production()`：`DEBUG=false` 场景断言无 mock 返回值 |
| conversation.py 大小 | < 150 行（仅 API 适配） | `wc -l api/conversation.py` |
| 单元测试通过 | `pytest tests/ -v` 全部通过 | CI |

### 性能验收

| 指标 | 标准 | 测量方式 |
|------|------|---------|
| P95 latency | <= 旧系统 * 1.2 | metrics.py |
| Tool success rate | >= 95% | metrics.py |
| Model fallback rate | < 5% | metrics.py |
| max_tool_calls 超限率 | < 2% | metrics.py |

---

## 8. 与 Convergence 路线图的关系

```
Convergence Phase 1 (Quiz)          ✅ DONE
Convergence Phase 2 (对话收敛)       🔄 IN PROGRESS
  ↓
本次重构 = Phase 3 + Phase 4 合并
  = AI 原生重构 Step 0.5-4
  ↓
Convergence Phase 3 (Router 轻量化)  → 被本次 Step 1-2 取代（直接删除 Router）
Convergence Phase 4 (清理旧路径)     → 被本次 Step 3-4 取代（一次性切换 + 清理）
```

Phase 2 的进行中工作（content_create 退场、clarify 修复）将在 Step 2.5 中自然完成。

---

## 附录 A: 代码量变化预估

| 目录 | 重构前 | 重构后 | 变化 |
|------|--------|--------|------|
| `agents/` | ~1200 行 (5 文件) | ~230 行 (2 文件: native_agent + provider) | -81% |
| `api/` | ~2500 行 | ~110 行 (原地重写 + 入口开关) | -96% |
| `tools/` | ~700 行 | ~790 行 (+registry.py ~140 行) | +13% |
| `services/` | ~800 行 | ~740 行 (+stream_adapter, +metrics) | -8% |
| `config/prompts/` | ~600 行 | ~200 行 | -67% |
| **合计** | **~5800 行** | **~2050 行** | **-65%** |

## 附录 B: API 契约（原地替换，端点不变）

```
# 端点不变（原地替换实现）
POST /api/conversation          → JSON
POST /api/conversation/stream   → SSE

# 请求体不变
{
  "message": "帮我出 5 道选择题",
  "teacherId": "t-001",
  "conversationId": "conv-xxx",  // 可选，续接对话
  "context": { "classId": "c-001" },
  "language": "zh-CN"
}

# SSE 事件格式不变 (Data Stream Protocol) — 先兼容，稳定后再优化
data: {"type":"start","messageId":"msg-xxx"}
data: {"type":"tool-input-start","toolCallId":"tc-1","toolName":"generate_quiz_questions"}
data: {"type":"tool-output-available","toolCallId":"tc-1","output":{...}}
data: {"type":"text-start","id":"t-1"}
data: {"type":"text-delta","id":"t-1","delta":"已为您生成..."}
data: {"type":"text-end","id":"t-1"}
data: {"type":"finish","finishReason":"stop"}
data: [DONE]
```

> **协议演进策略:** 第一版保持 SSE 事件格式完全不变，前端零改动。稳定后如需优化协议（如简化事件类型、增加进度百分比），另起独立 plan 处理，不与后端重写混在一批。
