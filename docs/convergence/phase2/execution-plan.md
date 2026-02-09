# Phase 2 执行说明 — Unified Agent 收敛

对齐文档：`docs/studio-v1/architecture/07-agent-convergence-plan.md`

本文是 **Agent 对话收敛** 的 Phase 2 落地说明。
Build compile/execute/save-as-app 已独立为单独的工程模块，见 `docs/build-runtime/README.md`。

---

## 1. 核心结论

1. **Build 不收敛到 Agent 对话流**
   Build 是按钮触发的流水线，不属于自然语言对话的自动工具调用。
   AI Agent 只负责对话理解与生成（quiz / ppt / docx / 互动网页等）。
   Build compile/execute 由独立 API 和 pipeline 执行。

2. **`content_create` 分支应逐步消失**
   最终统一到 Unified Agent 主干：
   - Phase 2：先实现能力收敛，`content_create` 仍可作为兼容入口。
   - Phase 3/4：路由收敛与分支清理，统一入口接管并移除业务分叉。

3. **PPT / 文稿 / 互动网页统一到 Agent 工具层**
   - PPT：`propose_pptx_outline` → `generate_pptx`
   - 文稿：`generate_docx`（必要时 `render_pdf`）
   - 互动网页：优先 `request_interactive_content`，简单场景 `generate_interactive_html`

---

## 2. Phase 2 目标边界

Phase 2 的核心是把 **对话生成能力** 往 Unified Agent 主干内聚：

- Quiz、PPT、文稿、互动网页统一走 Agent 工具调用
- 旧 `_stream_quiz_generate` / `content_create` 降级为 fallback
- `_stream_build` 保留为独立路径（按钮触发），不纳入 Agent 统一入口
- 前端事件协议保持不变

---

## 3. 路径演进（建议实现顺序）

### 3.1 入口层（`api/conversation.py`）

- 新增统一入口处理器 `_stream_unified_agent_mode`
- 将 quiz / content_create 分支改为"统一入口优先，旧分支 fallback callable"
- Build 路径保持独立，不合入统一处理器

### 3.2 Agent 层（`agents/teacher_agent.py`）

- 降低场景硬编码提示，改为策略型提示（以工具调用目标为中心）
- PPT / 文稿 / 互动网页工具已注册，确保 Agent 可自由选择
- 不注册 build_blueprint / execute_blueprint 为 Agent 工具（这些由独立 API 触发）

### 3.3 Router 层（`agents/router.py`）

Phase 2 可先不大改 Router 结构，但要避免继续加"路径级硬分流"：

- 保留 `model_tier` / `clarify` / `safety`
- 将关键词纠偏从"改 intent"改为"给工具 hint"（已在 quiz 里实践）
- Build 意图仍可识别，但走独立路径而非 Agent 工具

---

## 4. content_create 退场策略（避免一次性硬切）

三阶段：

1. **别名阶段**（Phase 2）
   `content_create` 仍可被识别，但内部统一映射到 Unified Agent 主处理函数。

2. **收敛阶段**（Phase 3）
   Router 输出收敛为轻路由字段（`clarify_needed` / `model_tier` / `safety_flags`），不再承担业务路径决策。

3. **清理阶段**（Phase 4）
   删除 `content_create` 业务分支代码，只保留统一 Agent 主干和紧急回退开关。

---

## 5. 生成类工具在 Unified Agent 下的标准流程

### 5.1 PPT

- 用户自然语言请求
- Unified Agent 判断是否先提纲：`propose_pptx_outline`
- 用户确认后：`generate_pptx`
- 输出 `data-pptx-outline` / `data-file-ready`

### 5.2 文稿（教案/讲稿/作业）

- Unified Agent 直接 `generate_docx`
- 需要 PDF 时 `render_pdf`
- 输出 `data-file-ready`

### 5.3 互动网页

- 非简单页面优先 `request_interactive_content`（分流式产出）
- 简单页面可 `generate_interactive_html`
- 输出 `data-interactive-*` 事件

### 5.4 Quiz

- Unified Agent 调用 `generate_quiz_questions`
- 输出 `data-quiz-question` / `data-quiz-complete`
- 详细优化指标见 `docs/convergence/phase2/quiz-optimization-input.md`

---

## 6. Phase 2 验收口径（对话收敛）

- Quiz 成功率 >= 基线，P50 劣化 <= 20%
- PPT / 文稿 / 互动网页走 Agent 工具调用成功率 >= 基线
- clarify 回合数不增加
- 跨场景连续对话可稳定切换（quiz -> ppt -> 互动网页）
- 前端事件协议零破坏
- Build 路径不受影响（独立验收，见 `docs/build-runtime/`）

---

## 7. 执行方案（v2 修订，统一协议）

本节覆盖本轮共识：不再依赖关键词硬编码分流，而是统一为 **Router 工具集规划 + Agent 工具编排 + 终态校验**。

> **v2 修订说明**（基于 PydanticAI 实验结论）
>
> - 取消独立 `TaskPlan` LLM 调用，合入 Router 输出
> - 取消"首轮 required / 后续 auto"策略（PydanticAI 不支持轮间切换）
> - 增加 `called_tools` 交叉验证（不单纯依赖 LLM 返回的 status 字段）
> - 增加重试时传入 `message_history` 避免工具重复执行
> - 增加 `stream_output()` 增量提取方案

### 7.1 设计目标

- **生成类单入口**：quiz / content_create 统一进入同一 Unified Agent Loop（Phase 2 范围；chat 路径保持现状，Phase 3 再收敛）
- 单终态：每轮必须落到结构化 `FinalResult`
- 工具可选：生成类请求可调多种工具；chat 路径独立
- 无关键词硬编码：不靠正则决定"该不该生成"
- 防止"说了不做"：`output_type` 约束 + 真实 SSE 事件交叉验证

### 7.2 核心模型

```python
class ClarifyPayload(BaseModel):
    question: str
    options: list[str] | None = None
    hint: str | None = None               # 前端提示 (needClassId 等)

class FinalResult(BaseModel):
    """Agent 唯一出口 — 通过调用这个结构化输出来结束循环"""
    status: Literal["answer_ready", "artifact_ready", "clarify_needed"]
    message: str                           # 给老师看的文字
    artifacts: list[str] = []              # 产物事件引用 (file-ready:pptx 等)
    clarify: ClarifyPayload | None = None  # status=clarify_needed 时必填
```

**不再单独定义 `TaskPlan` 模型。** 原 `TaskPlan` 的职责（`candidate_tools` + `model_tier`）
合入 `RouterResult`，Router 的 `suggested_tools` 升级为 `candidate_tools` 语义：

```python
class RouterResult(CamelModel):
    intent: str
    confidence: float
    candidate_tools: list[str]  # 原 suggested_tools，升级为候选工具集（优先集，非硬白名单）
    model_tier: str
    expected_mode: str          # "answer" | "artifact" | "clarify"
    strategy: str
    # ...
```

**candidate_tools 是优先集，不是硬白名单。** Agent 创建时的工具注册分两层：

```
常驻基座（始终注册，不受 candidate_tools 影响）:
├─ get_teacher_classes
├─ get_class_detail
├─ get_student_grades
├─ get_assignment_submissions
├─ search_teacher_documents
├─ get_rubric / list_available_rubrics
└─ analyze_student_weakness / get_student_error_patterns

优先集（来自 Router candidate_tools，按场景动态注册）:
├─ generate_quiz_questions
├─ propose_pptx_outline / generate_pptx
├─ generate_docx / render_pdf
└─ request_interactive_content / generate_interactive_html
```

这样即使 Router 给了窄工具集（如只有 `generate_pptx`），Agent 仍可调数据查询工具获取上下文后再生成，不会卡死多步链。

### 7.3 执行协议

```
用户消息
    |
    v
Step 1: Router（已有，增强 candidate_tools 输出）
    |  输入: 用户消息 + 会话历史
    |  输出: intent + candidate_tools + model_tier + expected_mode
    |
    v
Step 2: 路径分流
    |  chat_smalltalk / chat_qa  → Chat Agent（无 output_type，保持现状）
    |  build_workflow            → Blueprint Path（保持现状）
    |  clarify                   → _emit_clarify（保持现状）
    |  quiz_generate / content_create → Unified Agent Loop（下面详述）
    |
    v  (quiz / content 路径)
Step 3: 创建 Agent
    |  agent = Agent(
    |      model      = 按 model_tier 选择,
    |      output_type = FinalResult,
    |  )
    |  注册工具: 常驻基座(数据/知识/评估) + candidate_tools(生成类优先集)
    |
    v
Step 4: Agent Loop（PydanticAI 驱动）
    |  不设 tool_choice — 依靠 output_type=FinalResult 约束结构化退出
    |  output_type 保证: LLM 必须通过 FinalResult 结束，不能输出纯文字
    |  output_type 不保证: LLM 必先调用业务工具（可能直接调 FinalResult 跳过）
    |  兜底: validate_terminal_state 校验产物是否真实存在（§7.3.1）
    |
    |  流式消费:
    |    stream_output()  → FinalResult.message 增量提取
    |    ToolTracker      → 中间 data-tool-progress 事件
    |
    v
Step 5: validate_terminal_state()
    |  输入: FinalResult + emitted_events + called_tools + expected_mode
    |  事件优先、工具记录次之（见 §7.3.1）
    |
    v
Step 6: SSE 事件发送
    data-tool-progress  (循环中实时，ToolTracker)
    data-file-ready / data-quiz-* / data-interactive-*  (工具产物)
    text-delta          (FinalResult.message 增量)
    finish
```

#### 7.3.1 终态校验规则（`validate_terminal_state`）

校验分三层：**SSE 事件真实性（最终裁判）** → **FinalResult 自身一致性** → **与 Router 预期的弱约束**。

```python
# 真实 SSE 事件类型（由工具执行后实际 emit）
ARTIFACT_EVENT_TYPES = {
    "data-file-ready",          # generate_pptx / generate_docx / render_pdf
    "data-quiz-complete",       # generate_quiz_questions
    "data-interactive-content", # request_interactive_content / generate_interactive_html
    "data-pptx-outline",        # propose_pptx_outline
}

# 工具名（辅助判断，但工具调用可能失败，以事件为准）
ARTIFACT_TOOL_SET = {
    "generate_pptx", "propose_pptx_outline", "generate_docx",
    "render_pdf", "generate_quiz_questions",
    "request_interactive_content", "generate_interactive_html",
}

def validate_terminal_state(
    result: FinalResult,
    emitted_events: set[str],   # 本次请求、本次 loop 内实际 emit 的 SSE data-* 事件类型
                                # 注意：只统计当前 loop 迭代产出的事件，不含历史回放或上一次重试的事件
    called_tools: set[str],     # 本次 loop 内的工具调用记录（含失败的）
    expected_mode: str,         # 来自 RouterResult.expected_mode
) -> None:
    """校验失败时 raise RetryNeeded 或 SoftRetryNeeded。"""

    # ── 硬规则（raise RetryNeeded）──────────────────────

    # 规则 1: artifact_ready 必须有真实产物事件
    #   事件优先：工具可能被调用但执行失败，called_tools 有记录但没有事件
    if result.status == "artifact_ready":
        has_event = bool(emitted_events & ARTIFACT_EVENT_TYPES)
        has_tool = bool(called_tools & ARTIFACT_TOOL_SET)
        if not has_event and not has_tool:
            raise RetryNeeded("artifact_ready 但无产物事件和工具调用记录")
        if has_tool and not has_event:
            raise RetryNeeded("产物工具被调用但未产出事件（工具可能执行失败）")

    # 规则 2: clarify_needed 必须有 clarify payload
    if result.status == "clarify_needed":
        if not result.clarify or not result.clarify.question:
            raise RetryNeeded("clarify_needed 但 clarify payload 为空")

    # ── 软规则（warning + 一次软重试，不硬 fail）─────────

    # 规则 3: Router 预期 artifact 但 LLM 返回 answer_ready
    #   Router 可能误判（如用户问"PPT是什么"被判为 artifact），降级为 warning
    if expected_mode == "artifact" and result.status == "answer_ready":
        has_event = bool(emitted_events & ARTIFACT_EVENT_TYPES)
        has_tool = bool(called_tools & ARTIFACT_TOOL_SET)
        if not has_event and not has_tool:
            logger.warning(
                "Router expected artifact but Agent returned answer_ready "
                "with no tool calls — soft retry"
            )
            raise SoftRetryNeeded("Router 预期产物但 Agent 跳过工具直接回答")
        # 工具被调了或事件存在 → 尊重 LLM 决策，不重试
```

> **设计原则**：`emitted_events`（真实 SSE 事件）是终判依据，`called_tools`（工具调用记录）是辅助，`expected_mode`（Router 预期）只做弱约束。这避免了 Router 误判放大为硬失败。

#### 7.3.2 重试策略

校验失败后自动重试。重试契约：

| 异常类型 | 含义 | 重试次数 | 仍失败时 |
|---------|------|---------|---------|
| `RetryNeeded` | 硬规则违反（artifact 无事件、clarify 无 payload） | 1 次 | 走 fallback（legacy 路径或 error） |
| `SoftRetryNeeded` | 软规则违反（Router 预期与 Agent 判断不一致） | 1 次 | 接受 Agent 结果、记 warning |

**总重试上限 = 1 次。** 硬软规则共享配额——一个请求内最多重跑一次 Agent Loop，不会叠加。

重试时传入上一轮的 `agent_messages` 作为 `message_history`：

- 如果上一轮**已调工具但 FinalResult 不正确**：LLM 看到工具结果在历史中，直接产出正确的 FinalResult，不会重复调用工具
- 如果上一轮**完全没调工具**：重试时才真正调用，无副作用
- **重试时 `emitted_events` 和 `called_tools` 重新初始化**——只统计重试这一轮的产出，不累加上一轮的

#### 7.3.2.1 两种历史的区分

> **重要**：`message_history` 的传入范围取决于上下文，不可混淆。

| 场景 | 传入内容 | 原因 |
|------|---------|------|
| **同请求重试** | 本轮完整 `agent_messages`（含 tool calls + tool results） | LLM 需要看到已执行的工具，避免重复调用 |
| **跨场景连续对话** | 文字摘要（`format_history_for_prompt()`），不含原始 tool call messages | 避免上一场景的工具调用干扰当前生成 |

代码层面：重试在 `_stream_agent_mode` 内部循环中完成（同一个函数调用），天然持有本轮 `agent_messages`。跨场景历史由外层 `_conversation_stream_generator` 通过 `session.format_history_for_prompt()` 生成，两者不会混淆。

#### 7.3.3 `stream_output()` 增量提取

`output_type=FinalResult` 后 `stream_text()` 不可用，改用 `stream_output()` 提取 `message` 字段增量：

```python
last_message = ""
async for partial in stream_result.stream_output(debounce_by="text"):
    current = partial.message or ""
    if current.startswith(last_message) and len(current) > len(last_message):
        delta = current[len(last_message):]
        await merged_queue.put(("text-delta", delta))
        last_message = current
    elif current != last_message:
        # message 被回退重写（极少见），整体替换
        last_message = current
```

用户体验从"看自由文字流"变为"看进度条 + 最终总结"：

```
现在（无 output_type）:
  text-delta: "好的，我来为您生成PPT..."   ← 自由文字（可能没产物）
  [可能没有任何 data-file-ready]           ← "说了不做"

新方案（有 output_type）:
  data-tool-progress: "正在获取班级数据..."  ← ToolTracker 实时
  data-tool-progress: "正在生成PPT文件..."   ← ToolTracker 实时
  data-file-ready: {type:"pptx", url:...}   ← 真实产物
  text-delta: "已为您生成牛顿第一定律PPT"     ← FinalResult.message
  finish
```

### 7.4 重要实现约束

1. **不新增关键词正则路由逻辑** — 所有场景判断由 Router AI 完成
2. **`content_create` 仅保留兼容 intent 名称**，不再代表独立执行分支
3. **Build Runtime 继续独立**，不纳入 Unified Agent 工具箱
4. **Anthropic 模型限制**：`thinking` 与 `tool_choice=required` 冲突；artifact 路径关闭 thinking
5. **不设 `tool_choice`**：PydanticAI `run_stream()` 的 `model_settings` 是一次性传入的，无法在 agent 内部多轮间切换。依靠 `output_type=FinalResult` 本身约束退出
6. **不做"说话"类工具**（`ask_teacher` 等）：所有向用户传递信息的行为统一走 `FinalResult`，工具集保持纯执行
7. **会话历史分层传入**（见 §7.3.2.1）：跨场景传文字摘要；同请求重试传完整 tool history
8. **Agent loop 最大轮数**：`retries=5` 防止无限循环
9. **Chat 路径 Phase 2 不动**：Chat Agent 保持现有 `stream_text()` + 无 `output_type` 实现；Phase 3 再评估是否收敛到 FinalResult 协议

### 7.5 代码改动点（落地清单）

#### 新增

| 文件 | 内容 |
|------|------|
| `models/agent_output.py` | `FinalResult` + `ClarifyPayload` 模型 |
| `services/agent_validation.py` | `validate_terminal_state()` 含 `called_tools` 交叉验证 |

#### 修改

| 文件 | 改动 |
|------|------|
| `models/conversation.py` | `RouterResult` 增加 `candidate_tools` + `expected_mode` 字段 |
| `agents/router.py` | Router prompt 增加候选工具集输出；`suggested_tools` → `candidate_tools`；增加 `expected_mode` |
| `config/prompts/router.py` | 更新 Router initial prompt，增加工具选择规则 |
| `agents/teacher_agent.py` | `create_teacher_agent()` 新增 `output_type` 参数支持 |
| `config/prompts/teacher_agent.py` | 删除场景硬编码执行指令；增加 FinalResult 使用说明 |
| `api/conversation.py` | `_stream_agent_mode` 核心循环从 `stream_text()` 切换到 `stream_output()`；增加 `validate_terminal_state()` 调用；重试传入 `message_history` |

#### 删除

| 函数 / 类 | 所在文件 | 替代 |
|-----------|---------|------|
| `_apply_ppt_execution_directive()` | `api/conversation.py` | `output_type` 约束 |
| `_resolve_content_tool_enforcement()` | `api/conversation.py` | Router `candidate_tools` |
| `_ContentToolPlan` | `api/conversation.py` | Router `expected_mode` |
| `_build_fallback_ppt_outline()` + `_outline_to_fallback_slides()` + PPT fallback 逻辑块 | `api/conversation.py` `_stream_agent_mode` 内 | `validate_terminal_state()` |
| `required_tool_calls` 参数 + 事后断言 | `_stream_agent_mode()` 签名及尾部 | FinalResult 交叉验证 |
| `_is_ppt_request()` / `_is_ppt_confirmation()` | `api/conversation.py` | 不再需要关键词检测 |
| `_looks_like_outline_promise()` | `api/conversation.py` | 不再需要事后文本检测 |

### 7.6 PydanticAI 实验结论

以下结论来自四组对照实验（无 output_type / stream_output / Agent.iter / stream_structured）：

| 结论 | 详细 |
|------|------|
| `stream_text()` 与 `output_type` **不兼容** | 设了 `output_type=FinalResult` 后，`stream_text(delta=True)` 抛 `UserError` |
| `stream_output()` **可流式推** FinalResult | `message` 字段可增量获取，但只在最后一步（Agent 调 FinalResult 时）才开始流 |
| 工具执行期间**无文字流** | 中间 5-30 秒内用户看不到文字；由 ToolTracker `data-tool-progress` 事件填补 |
| `output_type` 成功阻止"只说不做" | 所有实验确认 LLM 必须先调工具，再调 FinalResult 退出 |
| `Agent.iter()` 给最细粒度控制 | 能看到每个节点（ModelRequest/CallTools/End），但无中间文字流式 |

### 7.7 风险与缓解

| 风险 | 严重度 | 缓解措施 |
|------|--------|---------|
| LLM 跳过工具直接调 FinalResult(answer_ready) | 中 | `validate_terminal_state` 规则 3（软约束）：Router 预期 artifact 但无工具调用 → 软重试一次；仍失败接受结果 |
| Router `expected_mode` 误判放大重试 | 中 | 规则 3 只做 warning + 软重试（`SoftRetryNeeded`），不硬 fail；误判代价 = 一次额外 LLM 调用 |
| `candidate_tools` 过窄卡死多步链 | 中 | candidate_tools 是优先集，常驻基座（数据/知识工具）始终可用；Agent 不会因缺数据查询工具而卡住 |
| 重试导致工具重复执行（如生成两份 PPT） | 中 | 同请求重试传完整 `agent_messages`，LLM 看到已有工具结果不会重复调用 |
| 工具调用成功但执行失败（called_tools 有记录但无事件） | 中 | 校验以 `emitted_events` 为终判，called_tools 为辅；工具调了但事件不存在 → 重试 |
| 不同 provider 对 structured output 支持差异 | 中 | Model fallback chain 中每个模型需独立验证 FinalResult 兼容性 |
| `stream_output()` message 字段回退重写 | 低 | 增量提取逻辑加 `startswith` 保护，回退时整体替换 |
| 跨场景会话中历史 tool calls 干扰新生成 | 低 | 跨场景只传文字摘要；同请求重试传完整 tool history（§7.3.2.1） |
| Anthropic thinking 与 output_type 冲突 | 已确认 | artifact 路径关闭 thinking；chat 路径可保留 |

### 7.8 分阶段发布

1. **阶段 A — Phase 2 灰度**（本轮）
   - 仅 `artifact` 场景（quiz / content_create）启用新协议（feature flag: `agent_unified_v2_enabled`）
   - Chat 路径保持现状，不受影响
   - 观察指标：假承诺率、工具调用成功率、validate 重试率、P50 延迟

2. **阶段 B — Phase 2 扩展**
   - 工具调用问答（如班级查询 + 文字回答）纳入同一 loop
   - 验证 FinalResult(answer_ready) 路径稳定性

3. **阶段 C — Phase 3 清理**
   - 删除 legacy `content_create` 分支执行代码
   - 删除 `_apply_ppt_execution_directive` / `_resolve_content_tool_enforcement` / PPT fallback
   - 保留紧急回退开关

4. **阶段 D — Phase 3 chat 收敛**（评估后决定）
   - 评估 Chat Agent 是否也迁移到 FinalResult 协议
   - 如迁移：chat 获得工具调用能力（如查询班级后回答）
   - 如保留：chat 继续用 `stream_text()`，两条路径长期并存

---

## 8. 配套文档

| 文档 | 职责 |
|------|------|
| 本文 | Agent 对话收敛执行说明 |
| `docs/convergence/phase2/quiz-optimization-input.md` | Quiz 专项优化 |
| `docs/build-runtime/README.md` | Build compile/execute/save-as-app（独立模块） |
| `docs/testing/phase2-live-content-quality-report.md` | Live 内容产出与质量报告 |

---

## 9. 架构边界小结

```
┌─────────────────────────────────────────────┐
│  Unified Agent（对话收敛 — 本文范围）         │
│  ┌─────────┐ ┌─────┐ ┌──────┐ ┌───────────┐ │
│  │  Quiz   │ │ PPT │ │ Docx │ │ 互动网页  │ │
│  └─────────┘ └─────┘ └──────┘ └───────────┘ │
│  入口: 自然语言对话                           │
│  触发: AI Agent 自动工具调用                  │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│  Build Runtime（独立模块 — 另见 build-runtime）│
│  ┌──────────┐ ┌───────────┐ ┌─────────────┐ │
│  │ Compile  │ │  Execute  │ │ Save as App │ │
│  └──────────┘ └───────────┘ └─────────────┘ │
│  入口: 前端按钮触发                           │
│  触发: 独立 API 调用，pipeline 执行           │
└─────────────────────────────────────────────┘
```
