# NativeAgent 设计

> AI 原生 Tool Calling 架构 — 单 runtime，LLM 自主编排。
> 替代旧的多 Agent 设计（PlannerAgent / ExecutorAgent / RouterAgent / ChatAgent / PatchAgent）。

---

## 架构对比

### 旧架构（已删除）

```
用户消息
  ↓
RouterAgent (if-elif 意图分类 + 置信度阈值 + 关键词正则)
  ↓
conversation.py (12+ handler 函数分发)
  ↓
┌─────────────────────┐
│ chat_response()     │ → ChatAgent
│ _stream_build()     │ → PlannerAgent → ExecutorAgent
│ _stream_quiz_*()    │ → QuizSkill / UnifiedAgent
│ _stream_modify_*()  │ → PatchAgent
│ _stream_followup*() │ → 各种 followup handler
└─────────────────────┘
  ~2500+ 行编排代码
```

### 新架构（AI 原生）

```
用户消息
  ↓
conversation.py (薄网关, ~100 行)
  → 鉴权、会话、限流、SSE 适配
  ↓
NativeAgent (单 runtime)
  → select_toolsets() → 宽松包含式选择 8-12 个 tools
  → Agent(tools=subset).run_stream()
  → LLM 自主决定调哪个 tool → 自动执行 → 自动循环
  ↓
stream_adapter → Data Stream Protocol SSE
  ↓
前端 (契约不变)
```

---

## NativeAgent (`agents/native_agent.py`)

### 职责

- 每轮根据上下文调用 `registry.get_tools(toolsets)` 获取 tool 子集
- 构建 PydanticAI `Agent(tools=subset)` 实例（每轮新建，开销 < 1ms）
- 调用 `agent.run_stream()` 或 `agent.run()`
- LLM 自主决定是否调 tool、调哪个、多少轮

### 核心流程

```python
class NativeAgent:
    async def run_stream(self, message: str, context: AgentContext):
        # 1. 宽松选择 toolset
        toolsets = self.select_toolsets(message, context)

        # 2. 从 registry 获取 tool 子集
        selected_tools = registry.get_tools(toolsets=toolsets)

        # 3. 创建 PydanticAI Agent（每轮新建）
        agent = Agent(
            model=create_model(),
            system_prompt=SYSTEM_PROMPT,
            tools=selected_tools,
        )

        # 4. 加载历史并执行
        history = await conversation_store.load_history(context.conversation_id)
        result = await agent.run_stream(message, message_history=history)

        # 5. 迭代流事件
        async for event in result:
            yield event

        # 6. 保存历史
        await conversation_store.save_history(context.conversation_id, result.messages)
```

### Toolset 选择策略

**宽松包含式选择** — 不是排他分类，误包含代价极低，误排除代价极高。

```python
def select_toolsets(self, message: str, context: AgentContext) -> list[str]:
    sets = ["base_data", "platform"]  # 始终包含

    if _might_generate(message):     # 关键词: 出题/生成/PPT/quiz...
        sets.append("generation")

    if context.has_artifacts or _might_modify(message):  # 关键词: 修改/改/换/删...
        sets.append("artifact_ops")

    if context.class_id or _might_analyze(message):      # 关键词: 成绩/分析/统计...
        sets.append("analysis")

    return sets
```

> **与旧 RouterAgent 的区别**: 旧 Router 做排他分类（"这是 quiz 意图 → 只走 quiz 路径"），新 toolset 选择做宽松包含（"可能需要生成 → 加载 generation 包，LLM 自己决定用不用"）。

### System Prompt 设计

```
你是教育 AI 助手。以下是你的工具使用规则：

1. 你有一组可用工具。对于每个用户请求，自主判断是否需要调用工具。
2. 涉及学生数据、成绩、作业提交等信息时，必须通过数据工具获取，不可编造。
3. 涉及教学文档内容时，必须通过 search_teacher_documents 检索，不可凭记忆回答。
4. 涉及实时信息时，必须通过相应工具获取，不可用训练数据回答。
5. 对于通用知识（语法规则、数学公式等），可以直接回答。
6. 当工具返回 status="error" 时，如实告知用户服务暂不可用，不可编造替代答案。
7. 不确定是否需要工具时，优先调用工具确认，而非猜测回答。
```

---

## Tool Registry (`tools/registry.py`)

### 注册方式

```python
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
```

### 查询

```python
# 按 toolset 获取子集
tools = registry.get_tools(toolsets=["generation", "platform"])

# 获取全部 tool
all_tools = registry.get_all_tools()
```

### 5 个 Toolset

| Toolset | Tools 数 | 注入条件 | 说明 |
|---------|---------|---------|------|
| `base_data` | 5 | 始终注入 | 基础数据获取 + 实体解析 |
| `analysis` | 5 | 涉及数据/成绩 | 统计分析 + 薄弱点 |
| `generation` | 7 | 涉及生成/创建 | Quiz/PPT/文稿/互动 |
| `artifact_ops` | 3 | 有 artifact 或涉及修改 | 获取/修改/重新生成 |
| `platform` | 5 | 始终注入 | 保存/分享/RAG/澄清/报告 |

---

## Artifact 编辑模型

生成用专用工具，编辑用通用 `patch_artifact`，避免工具爆炸。

### 工具分工

| 操作 | 工具 | 说明 |
|------|------|------|
| 首次生成 | `generate_quiz_questions` / `generate_pptx` / ... | 专用工具，按 artifact_type 分发 |
| 结构化修改 | `patch_artifact(artifact_id, operations)` | 通用工具，按 content_format 分发到 patcher |
| 全文重新生成 | `regenerate_from_previous(artifact_id, instruction)` | patch 失败的降级路径 |

### 编辑 vs 重新生成

由 LLM 自主判断，不硬编码规则:
1. LLM 收到修改请求 → 调 `get_artifact` 获取当前内容
2. 根据修改复杂度自主决定:
   - 小改 → `patch_artifact`
   - 大改 → `regenerate_from_previous` 或对应 `generate_xxx`

---

## 会话流程

```
POST /api/conversation/stream
    │
    ▼
conversation.py (薄网关)
    ├── 鉴权: 验证 JWT → teacher_id
    ├── 会话: 加载/创建 conversation_id
    ├── 调用: NativeAgent.run_stream(message, context)
    ├── 适配: stream_adapter → SSE 事件
    └── 校验: 确认 finish 事件已发送
    │
    ▼
前端消费 SSE (Data Stream Protocol 契约不变)
```

### 场景示例

| 场景 | 用户消息 | NativeAgent 行为 |
|------|---------|-----------------|
| 闲聊 | "你好" | LLM 直接回复，不调 tool |
| RAG 问答 | "Unit 5 教学重点" | 自动调 `search_teacher_documents` |
| Quiz 生成 | "出 5 道英语选择题" | 自动调 `generate_quiz_questions` |
| Quiz 修改 | "把第 3 题改成填空题" | 自动调 `get_artifact` → `patch_artifact` |
| 数据分析 | "分析三班成绩" | 自动调 `get_teacher_classes` → `calculate_stats` |
| 跨意图 | 同一对话内 chat→quiz→修改 | conversation_id 上下文连续，LLM 自主切换 |

---

## 与旧 Agent 的对应关系

| 旧 Agent | 新架构替代 | 说明 |
|----------|----------|------|
| **RouterAgent** | 删除 | LLM 自主选 tool，无需意图分类 |
| **PlannerAgent** | 删除 | Blueprint 规划被 tool calling 取代 |
| **ExecutorAgent** | 删除 | 三阶段流水线被 NativeAgent 取代 |
| **ChatAgent** | 删除 | NativeAgent 直接处理对话 |
| **PageChatAgent** | 删除 | NativeAgent 通过 conversation_id 上下文处理追问 |
| **PatchAgent** | `patch_artifact` tool | 正则匹配被结构化 PatchOp 取代 |
| **EntityResolver** | `resolve_entity` tool | 状态机被 tool 取代 |

---

## 工程约束

### 失败分级

| 级别 | 类型 | 处理方式 |
|------|------|---------|
| L1 | Tool 失败 | tool 返回错误信息给 LLM，LLM 自主重试或换策略 |
| L2 | Model 失败 | fallback 到备选 model |
| L3 | Protocol 失败 | stream_adapter 捕获 + 发送 error event |
| L4 | Budget 超限 | 强制停止 + 返回 partial result |
| L5 | System 失败 | 全局异常处理 → 500 + error event |

### 预算约束

| 约束 | 默认值 |
|------|--------|
| max_tool_calls | 10 |
| max_total_tokens | 32k (input) + 8k (output) |
| max_turn_duration | 120s |
| per-tool timeout | 30s |
