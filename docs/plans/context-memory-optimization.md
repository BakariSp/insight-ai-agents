# AI Agent 上下文记忆优化方案

> Token-Aware Sliding Window + Progressive Summarization
> 创建日期: 2026-02-08
> 状态: 待实施

---

## 1. 问题诊断

### 1.1 当前实现分析

当前上下文管理位于 `services/conversation_store.py`，核心逻辑：

| 维度 | 现状 | 代码位置 |
|------|------|----------|
| Token 计数 | **无** — 完全依赖字符截断 | — |
| 存储截断 | 每轮 `MAX_TURN_CHARS = 6000` 字符硬截断 | `conversation_store.py:28` |
| Router 历史 | 40 轮 x 2000 字符/轮 = 最多 ~80K 字符 | `format_history_for_prompt()` |
| Agent 历史 | 40 轮 x 6000 字符/轮 = 最多 ~240K 字符 | `to_pydantic_messages()` |
| 摘要机制 | **无** — 超出窗口的早期对话直接丢弃 | — |
| turns 列表 | 内存无界增长，仅靠 TTL (30min) 清理 | `InMemoryConversationStore` |

### 1.2 风险评估

```
40 轮 x 6000 字符 = 240,000 字符
中文: ~240K / 2 ≈ 120K tokens
英文: ~240K / 4 ≈ 60K tokens
混合: ~80-120K tokens

qwen-max 上下文窗口 = 128K tokens
系统提示 + 当前消息 + 输出预留 ≈ 8-10K tokens
可用历史空间 ≈ 118K tokens

结论: 中文长对话 (>25轮) 大概率超出上下文窗口
```

### 1.3 关键代码路径

```
api/conversation.py::_load_session()
  ├── session.format_history_for_prompt(max_turns=40)  → 纯文本给 RouterAgent
  └── session.to_pydantic_messages(max_turns=40)       → ModelMessage 给 Chat/PageChat/TeacherAgent

api/conversation.py::_save_session()
  ├── session.add_assistant_turn(response_summary)
  └── store.save(session)
```

消费方：
- **RouterAgent** (`agents/router.py`): 文本注入到 system prompt
- **ChatAgent** (`agents/chat.py`): `agent.run(user_content, message_history=...)`
- **PageChatAgent** (`agents/page_chat.py`): `agent.run(user_content, message_history=...)`
- **TeacherAgent** (`agents/teacher_agent.py`): `agent.run_stream(input, message_history=...)`
- **PlannerAgent / ExecutorAgent**: 不接收对话历史（无需改动）

---

## 2. 优化目标架构

```
┌──────────────────────────────────────────────────────┐
│              Model Context Window (128K)              │
│                                                       │
│  ┌──────────┐  ┌────────────┐  ┌──────────────────┐ │
│  │ System   │  │ 早期对话    │  │ 近期对话          │ │
│  │ Prompt   │  │ 摘要(压缩)  │  │ 原文完整保留      │ │
│  │ (固定)   │  │ (~1K)      │  │ (token预算内)     │ │
│  └──────────┘  └────────────┘  └──────────────────┘ │
│                                                       │
│  总预算 = 128K - 系统提示(~2K) - 输出预留(4K) = 122K  │
│  历史预算 = 122K × 60% ≈ 73K tokens                  │
└──────────────────────────────────────────────────────┘
```

核心策略：
1. **Token-Aware 滑窗** — 从最新轮次向前遍历，完整保留每轮，直到填满 token 预算
2. **渐进式摘要** — 当总 token 达到预算 80% 时，压缩前半部分为摘要
3. **存储保留更多原文** — 截断上限 6000→20000 字符，真正的截断发生在检索时

---

## 3. 实施方案

### 3.1 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `services/token_counter.py` | **新建** | Token 计数工具，3 级 fallback |
| `services/context_summarizer.py` | **新建** | 渐进式摘要逻辑 |
| `services/conversation_store.py` | **修改** | 添加 summary 字段，重构历史格式化方法 |
| `config/settings.py` | **修改** | 添加上下文窗口和摘要配置 |
| `api/conversation.py` | **修改** | 传入 token 预算，hook 摘要到保存流程 |
| `requirements.txt` | **修改** | 添加 `tiktoken>=0.7` |
| `tests/test_token_counter.py` | **新建** | Token 计数测试 |
| `tests/test_context_summarizer.py` | **新建** | 摘要逻辑测试 |
| `tests/test_conversation_store.py` | **修改** | 更新现有测试 + 新增 token 预算测试 |

### 3.2 Step 1 — Token-Aware Sliding Window（优先实施）

#### 3.2.1 新建 `services/token_counter.py`

Token 计数 3 级 fallback：

```python
"""Token counting utilities with caching and multi-provider fallback."""

from __future__ import annotations
import logging
from functools import lru_cache
from pydantic_ai.messages import (
    ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart,
)

logger = logging.getLogger(__name__)
_CHARS_PER_TOKEN_ESTIMATE = 2.5  # 中英混合保守估算


@lru_cache(maxsize=1)
def _get_tiktoken_encoding():
    """Lazily load tiktoken cl100k_base encoding (cached singleton)."""
    try:
        import tiktoken
        return tiktoken.get_encoding("cl100k_base")
    except (ImportError, Exception):
        logger.info("tiktoken unavailable, using char heuristic fallback")
        return None


def count_tokens(text: str, model: str | None = None) -> int:
    """Count tokens in text.

    Priority:
      1. litellm.token_counter() — if model is in registry
      2. tiktoken cl100k_base    — local, fast (~5% error for Qwen)
      3. len(text) / 2.5         — character heuristic fallback
    """
    if not text:
        return 0

    # Strategy 1: LiteLLM (most accurate if model registered)
    if model:
        try:
            import litellm
            return litellm.token_counter(model=model, text=text)
        except Exception:
            pass

    # Strategy 2: tiktoken cl100k_base
    enc = _get_tiktoken_encoding()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass

    # Strategy 3: char heuristic
    return max(1, int(len(text) / _CHARS_PER_TOKEN_ESTIMATE))


def count_turns_tokens(turns: list, model: str | None = None) -> int:
    """Count total tokens across ConversationTurn list."""
    total = 0
    for turn in turns:
        total += 4  # per-message overhead (role + delimiters)
        total += count_tokens(turn.content, model)
    return total


def count_messages_tokens(messages: list[ModelMessage], model: str | None = None) -> int:
    """Count total tokens across PydanticAI ModelMessage list."""
    total = 0
    for msg in messages:
        total += 4
        total += count_tokens(_extract_text(msg), model)
    return total


def _extract_text(msg: ModelMessage) -> str:
    """Extract text from a PydanticAI ModelMessage."""
    if isinstance(msg, ModelRequest):
        return " ".join(
            p.content for p in msg.parts
            if isinstance(p, UserPromptPart) and isinstance(p.content, str)
        )
    if isinstance(msg, ModelResponse):
        return " ".join(p.content for p in msg.parts if isinstance(p, TextPart))
    return ""
```

#### 3.2.2 修改 `config/settings.py` — 新增配置

```python
# ── Context Window Management ─────────────────────────────
context_window_tokens: int = 128000        # qwen-max 上下文窗口
history_token_budget_ratio: float = 0.60   # 60% 给历史
output_token_reserve: int = 4096           # 预留输出
system_prompt_token_estimate: int = 2000   # 系统提示词估算
router_history_token_budget: int = 8000    # Router 专用（小预算）

# ── Summarization ─────────────────────────────────────────
summarization_trigger_ratio: float = 0.80  # 触发阈值
summarization_target_ratio: float = 0.40   # 压缩目标
summarization_model: str = ""              # 空 = 用 router_model (qwen-turbo)
summarization_max_tokens: int = 1024       # 摘要最大 token 数

@property
def history_token_budget(self) -> int:
    """可用于对话历史的 token 预算."""
    available = self.context_window_tokens - self.output_token_reserve - self.system_prompt_token_estimate
    return int(available * self.history_token_budget_ratio)
    # 默认 = (128000 - 4096 - 2000) × 0.6 ≈ 73,142 tokens
```

对应 `.env` 变量（均可选，有默认值）：
```
CONTEXT_WINDOW_TOKENS=128000
HISTORY_TOKEN_BUDGET_RATIO=0.60
OUTPUT_TOKEN_RESERVE=4096
ROUTER_HISTORY_TOKEN_BUDGET=8000
SUMMARIZATION_TRIGGER_RATIO=0.80
SUMMARIZATION_MODEL=
```

#### 3.2.3 修改 `services/conversation_store.py`

**a) 提高存储截断上限：**

```python
MAX_TURN_CHARS = 20000  # 存储层安全上限；真正截断在检索时按 token 做
```

**b) ConversationSession 添加 summary 字段：**

```python
class ConversationSession(BaseModel):
    # ... 现有字段 ...

    # Progressive summarization state
    summary: str | None = None             # 压缩的早期对话摘要
    summary_token_count: int = 0           # 摘要 token 数
    summarized_turn_count: int = 0         # 已摘要轮次数
```

**c) 重构 `format_history_for_prompt()`：**

```python
def format_history_for_prompt(
    self,
    max_turns: int = 40,
    token_budget: int = 8000,
    model: str | None = None,
) -> str:
    """Token-aware 历史格式化（给 Router 用）.

    从最新轮次向前遍历，完整保留每轮，直到填满 token 预算。
    如有 summary 则拼接在前面。
    """
    from services.token_counter import count_tokens

    turns_for_context = self.turns[:-1] if self.turns else []
    recent = turns_for_context[-max_turns:]
    if not recent and not self.summary:
        return ""

    # 预留 summary 空间
    summary_tokens = self.summary_token_count if self.summary else 0
    available = token_budget - summary_tokens

    # 从最新向前填充
    lines: list[str] = []
    used_tokens = 0
    for turn in reversed(recent):
        prefix = "USER" if turn.role == "user" else "ASSISTANT"
        action_tag = f"[{turn.action}] " if turn.action else ""
        line = f"{prefix}: {action_tag}{turn.content}"
        line_tokens = count_tokens(line, model)
        if used_tokens + line_tokens > available:
            break
        lines.append(line)
        used_tokens += line_tokens

    lines.reverse()

    result_parts = []
    if self.summary:
        result_parts.append(
            f"[Earlier conversation summary ({self.summarized_turn_count} turns)]:\n"
            f"{self.summary}\n"
        )
    if lines:
        result_parts.append("\n".join(lines))
    return "\n".join(result_parts)
```

**d) 重构 `to_pydantic_messages()`：**

```python
def to_pydantic_messages(
    self,
    max_turns: int = 40,
    token_budget: int = 0,
    model: str | None = None,
) -> list[ModelMessage]:
    """Token-aware 结构化历史（给 PydanticAI Agent 用）.

    token_budget=0 时从 settings 读取。
    summary 注入为 user+assistant 消息对以保持角色交替。
    """
    from services.token_counter import count_tokens

    if token_budget <= 0:
        from config.settings import get_settings
        token_budget = get_settings().history_token_budget

    turns_for_context = self.turns[:-1] if self.turns else []
    recent = turns_for_context[-max_turns:]
    if not recent and not self.summary:
        return []

    summary_tokens = self.summary_token_count if self.summary else 0
    available = token_budget - summary_tokens

    selected: list[ConversationTurn] = []
    used_tokens = 0
    for turn in reversed(recent):
        turn_tokens = count_tokens(turn.content, model) + 4
        if used_tokens + turn_tokens > available:
            break
        selected.append(turn)
        used_tokens += turn_tokens
    selected.reverse()

    messages: list[ModelMessage] = []

    # Summary 注入为 user+assistant 对
    if self.summary:
        messages.append(ModelRequest(parts=[UserPromptPart(
            content=f"[Context: Summary of earlier conversation "
                    f"({self.summarized_turn_count} turns)]:\n{self.summary}"
        )]))
        messages.append(ModelResponse(parts=[TextPart(
            content="Understood. I have the context from our earlier conversation."
        )]))

    for turn in selected:
        if turn.role == "user":
            messages.append(ModelRequest(parts=[UserPromptPart(content=turn.content)]))
        else:
            messages.append(ModelResponse(parts=[TextPart(content=turn.content)]))
    return messages
```

#### 3.2.4 修改 `api/conversation.py` — `_load_session()` 传入预算

```python
async def _load_session(store, req):
    # ... 现有逻辑 ...

    settings = get_settings()
    history_text = session.format_history_for_prompt(
        max_turns=_ROUTER_HISTORY_MAX_TURNS,
        token_budget=settings.router_history_token_budget,
        model=settings.router_model,
    )
    message_history = session.to_pydantic_messages(
        max_turns=_MESSAGE_HISTORY_MAX_TURNS,
        token_budget=settings.history_token_budget,
        model=settings.default_model,
    )
    return session, history_text, message_history
```

**零 Agent 代码变更** — 返回类型不变，所有下游 Agent 无需修改。

---

### 3.3 Step 2 — Progressive Summarization（长对话 >20 轮）

#### 3.3.1 新建 `services/context_summarizer.py`

```python
"""Progressive conversation summarization.

当对话历史 token 数接近预算时，用快速模型压缩早期对话为摘要。
"""

SUMMARIZE_SYSTEM_PROMPT = """\
You are a conversation summarizer for an educational AI assistant.
Summarize the following conversation turns into a concise summary that preserves:
1. Key user requests and intents
2. Important decisions made (class selected, assignment chosen, etc.)
3. Any data analysis results or generated content descriptions
4. Accumulated context (classId, studentId, etc.)

Write in the same language as the conversation.
Be concise but preserve critical context needed for future turns.
Output ONLY the summary text, no preamble.
"""


async def maybe_summarize(
    session,            # ConversationSession
    token_budget: int,
    trigger_ratio: float = 0.80,
    target_ratio: float = 0.40,
    model: str | None = None,
    summarize_model: str | None = None,
    max_summary_tokens: int = 1024,
) -> bool:
    """如果历史 token 超阈值则触发摘要，返回是否执行了摘要."""
    from services.token_counter import count_tokens, count_turns_tokens

    turns = session.turns
    if len(turns) < 6:
        return False

    total = count_turns_tokens(turns, model) + session.summary_token_count
    if total < token_budget * trigger_ratio:
        return False

    # 从最新向前保留 target_ratio 的 turns
    target_tokens = int(token_budget * target_ratio)
    keep_tokens = 0
    split_idx = len(turns)
    for i in range(len(turns) - 1, -1, -1):
        t = count_tokens(turns[i].content, model) + 4
        if keep_tokens + t > target_tokens:
            split_idx = i + 1
            break
        keep_tokens += t

    if split_idx < 2:
        return False

    older = turns[:split_idx]
    recent = turns[split_idx:]

    # 拼接待摘要文本
    text = ""
    if session.summary:
        text += f"Previous summary:\n{session.summary}\n\n"
    text += "New turns to incorporate:\n"
    for turn in older:
        prefix = "USER" if turn.role == "user" else "ASSISTANT"
        action = f" [{turn.action}]" if turn.action else ""
        text += f"{prefix}{action}: {turn.content}\n"

    # 调用快速模型
    import litellm
    from config.settings import get_settings
    settings = get_settings()
    sum_model = summarize_model or settings.summarization_model or settings.router_model

    try:
        response = await litellm.acompletion(
            model=sum_model,
            messages=[
                {"role": "system", "content": SUMMARIZE_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            max_tokens=max_summary_tokens,
            temperature=0.2,
        )
        new_summary = response.choices[0].message.content.strip()
    except Exception:
        logger.exception("Summarization failed, skipping")
        return False

    # 更新 session
    session.summary = new_summary
    session.summary_token_count = count_tokens(new_summary, model)
    session.summarized_turn_count += len(older)
    session.turns = recent
    return True
```

#### 3.3.2 Hook 到 `_save_session()`

```python
async def _save_session(store, session, req, response, intent):
    # ... 现有逻辑 ...

    # Progressive summarization check
    from services.context_summarizer import maybe_summarize
    settings = get_settings()
    await maybe_summarize(
        session,
        token_budget=settings.history_token_budget,
        trigger_ratio=settings.summarization_trigger_ratio,
        target_ratio=settings.summarization_target_ratio,
        model=settings.default_model,
        summarize_model=settings.summarization_model or settings.router_model,
        max_summary_tokens=settings.summarization_max_tokens,
    )

    await store.save(session)
```

流式端点的 session 保存块同理 hook。

---

## 4. 方案对比

| 方案 | 实现复杂度 | 信息保留 | 成本 | 适用场景 |
|------|-----------|---------|------|---------|
| A. 当前做法（字符截断 + 40轮） | 最低 | 差 | 低 | 短对话 (<10轮) |
| **B. Token-aware 滑窗 (Step 1)** | **低** | **中** | **中** | **多数场景 (优先做)** |
| **C. 滑窗 + 渐进摘要 (Step 1+2)** | **中** | **好** | **中** | **长对话 (>20轮)** |
| D. RAG 检索历史 | 高 | 最好 | 高 | 超长对话 / 跨会话 |

推荐路线：**B → C**，按需启用 D。

---

## 5. 向后兼容与部署策略

### 5.1 向后兼容

- 所有新字段有默认值 — Pydantic V2 自动处理缺失字段
- 旧 session JSON 反序列化不受影响（Redis / Memory）
- 所有新方法参数有默认值 — 现有调用方无需修改
- Agent 接收类型不变 — 零下游改动

### 5.2 分阶段上线

**Phase 1（低风险）：** 部署 Step 1，设 `SUMMARIZATION_TRIGGER_RATIO=1.0` 禁用摘要
- 验证 token 计数正确性
- 验证历史不溢出
- 观察日志中 token 用量

**Phase 2（验证后）：** 设 `SUMMARIZATION_TRIGGER_RATIO=0.80` 启用摘要
- 监控摘要 LLM 调用频率和耗时
- 验证摘要质量

---

## 6. 验证计划

```bash
# 单元测试
pytest tests/test_token_counter.py -v
pytest tests/test_context_summarizer.py -v
pytest tests/test_conversation_store.py -v

# 集成验证
python main.py  # 启动服务
# 进行 30+ 轮对话，检查：
#   - 无 context window overflow 报错
#   - 日志中可见摘要触发
#   - 近期对话上下文完整
#   - 早期关键信息（classId等）通过摘要保留
```

### 测试矩阵

| 测试文件 | 用例 |
|----------|------|
| `test_token_counter.py` | 空文本、英文、中文、混合、fallback |
| `test_context_summarizer.py` | 短对话不触发、阈值触发、保留近期、增量摘要、LLM 失败 |
| `test_conversation_store.py` | 原有测试 + token 预算、summary 注入、JSON 序列化兼容 |
