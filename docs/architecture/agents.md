# 多 Agent 设计

> PlannerAgent / ExecutorAgent / RouterAgent / PageChatAgent 的分工、实现与协作。

---

## Agent 分工总览

| Agent | 职责 | 输入 | 输出 | 对外暴露 |
|-------|------|------|------|---------|
| **PlannerAgent** | 理解用户需求，生成 Blueprint | 用户自然语言 | 结构化分析方案 JSON | `POST /api/workflow/generate` |
| **ExecutorAgent** | 执行分析计划，调用工具，构建页面 | Blueprint + 数据 | SSE 流式页面 | `POST /api/page/generate` |
| **RouterAgent** | 对追问进行意图分类 | 用户追问 + 上下文 | action 类型 | **内部组件** |
| **PageChatAgent** | 处理页面相关的对话式交互 | 用户消息 + 页面上下文 | 文本回复 | **内部组件** |

> **设计原则**: RouterAgent 和 PageChatAgent 不对外暴露独立端点，统一通过 `POST /api/page/followup` 内部调度。前端只调一个端点，根据响应中的 `action` 字段做渲染。

---

## LLM 框架选型

### PydanticAI + LiteLLM model

| 选择理由 | 说明 |
|----------|------|
| 技术栈契合 | 项目已用 Pydantic v2 + CamelModel，PydanticAI 天然集成 |
| 结构化输出 | Blueprint 需要 LLM 输出复杂嵌套 JSON，`result_type=Blueprint` 直接验证 |
| 多 Provider | PydanticAI 原生支持 LiteLLM 作为 model provider，保留 Qwen/GLM/GPT/Claude 切换 |
| Tool Calling | `@agent.tool` + Pydantic 参数验证，与 FastMCP `@mcp.tool` 理念一致 |
| Streaming | `agent.iter()` / `run_stream_events()` 直接产出 SSE 事件 |
| 未来扩展 | Level 3（AI 生成 Python function + 前端 UI）时，类型系统有助于约束和验证 |

### Why FastMCP (purely internal)

FastMCP 不对外暴露，仅作为 **内部 tool 注册和调用框架**：

| vs 自定义 BaseSkill | FastMCP |
|---------------------|---------|
| class + ABC + 手写 JSON Schema | `@mcp.tool` + type hints，schema 自动生成 |
| 无参数验证 | Pydantic 自动验证 |
| ~40 行/tool | ~10 行/tool |
| 自己搭测试 | 内置 `fastmcp dev` 交互测试 |

PydanticAI Agent 通过 `@agent.tool` 桥接 FastMCP tools，in-process 调用，零网络开销。
前端完全不感知 MCP，只与 FastAPI HTTP/SSE 端点交互。

---

## Agent Provider (`agents/provider.py`) ✅ 已实现

核心：PydanticAI Agent + LiteLLM model + FastMCP tool 桥接。

```python
from config.settings import get_settings
from tools import TOOL_REGISTRY, get_tool_descriptions


def create_model(model_name: str | None = None) -> str:
    """构建 PydanticAI 模型标识符 "litellm:<model>"。"""
    settings = get_settings()
    name = model_name or settings.default_model
    return f"litellm:{name}"


def get_mcp_tool_names() -> list[str]:
    """获取所有注册工具名称。"""
    return list(TOOL_REGISTRY.keys())


async def execute_mcp_tool(name: str, arguments: dict) -> Any:
    """In-process 调用 TOOL_REGISTRY 中的函数（支持 sync/async）。"""
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        raise ValueError(f"Tool '{name}' not found")
    if inspect.iscoroutinefunction(fn):
        return await fn(**arguments)
    return fn(**arguments)
```

---

## PlannerAgent (`agents/planner.py`) ✅ 已实现

输入 user prompt → 输出 `Blueprint`。PydanticAI 的 `output_type` 确保输出结构合法。

通过 `PLANNER_LLM_CONFIG` 声明 Agent 级 LLM 参数（低温度 + JSON 输出格式），
并在 `agent.run()` 时通过 `model_settings` 传递给 LiteLLM。

```python
from pydantic_ai import Agent
from models.blueprint import Blueprint
from agents.provider import create_model
from config.llm_config import LLMConfig
from config.prompts.planner import build_planner_prompt

# Agent-level LLM tuning — structured output, low temperature
PLANNER_LLM_CONFIG = LLMConfig(
    temperature=0.2,
    response_format="json_object",
)

_planner_agent = Agent(
    model=create_model(),
    output_type=Blueprint,
    system_prompt=build_planner_prompt(),
    retries=2,
    defer_model_check=True,
)


async def generate_blueprint(
    user_prompt: str, language: str = "en", model: str | None = None,
) -> Blueprint:
    """用户输入 → Blueprint。"""
    result = await _planner_agent.run(
        f"[Language: {language}]\n\nUser request: {user_prompt}",
        model=create_model(model) if model else None,
        model_settings=PLANNER_LLM_CONFIG.to_litellm_kwargs(),
    )
    blueprint = result.output
    # 自动填充 source_prompt, created_at
    return blueprint
```

---

## ExecutorAgent (`agents/executor.py`) ✅ 已实现

执行 Blueprint 三阶段，输出 SSE stream → 前端 `handleSSEStream()` 直接消费，构建结构化页面。

```python
import json
from typing import AsyncGenerator
from pydantic_ai import Agent
from agents.provider import create_model, execute_mcp_tool
from config.settings import get_settings
from models.blueprint import Blueprint, ComputeNodeType


class ExecutorAgent:

    def __init__(self):
        settings = get_settings()
        self.model = create_model(settings.executor_model)

    async def execute_blueprint_stream(
        self, blueprint: Blueprint, context: dict,
    ) -> AsyncGenerator[dict, None]:
        """三阶段执行 Blueprint，流式输出 SSE 事件。"""

        # ── Phase 1: Resolve Data Contract ──
        yield {"type": "PHASE", "phase": "data", "message": "Fetching data..."}
        data_context = await self._resolve_data_contract(blueprint, context)

        # ── Phase 2: Execute Compute Graph ──
        yield {"type": "PHASE", "phase": "compute", "message": "Computing analytics..."}
        compute_results = {}

        tool_nodes = [n for n in blueprint.compute_graph.nodes if n.type == ComputeNodeType.TOOL]
        ai_nodes = [n for n in blueprint.compute_graph.nodes if n.type == ComputeNodeType.AI]

        for node in tool_nodes:
            if node.tool_name:
                resolved_args = self._resolve_refs(node.tool_args or {}, data_context, compute_results)
                yield {"type": "TOOL_CALL", "tool": node.tool_name, "args": resolved_args}
                result = await execute_mcp_tool(node.tool_name, resolved_args)
                yield {"type": "TOOL_RESULT", "tool": node.tool_name, "result": result}
                compute_results[node.output_key] = json.loads(result) if self._is_json(result) else result

        # ── Phase 3: AI Compose ──
        yield {"type": "PHASE", "phase": "compose", "message": "Composing page..."}

        compose_prompt = self._build_compose_prompt(blueprint, data_context, compute_results)
        agent = Agent(model=self.model, system_prompt=blueprint.page_system_prompt or "")

        @agent.tool_plain
        async def call_tool(tool_name: str, arguments: str) -> str:
            """调用数据/统计工具获取额外数据。"""
            args = json.loads(arguments)
            return await execute_mcp_tool(tool_name, args)

        accumulated = ""
        async with agent.iter(compose_prompt) as run:
            async for node in run:
                if hasattr(node, 'data') and isinstance(node.data, str):
                    accumulated += node.data
                    yield {"type": "MESSAGE", "content": node.data}

        yield {
            "type": "COMPLETE", "message": "completed", "progress": 100,
            "result": {"response": accumulated},
        }
```

### Blueprint 执行流程

```
Phase 1: Data    → 解析 DataContract，调用 tools 获取数据
Phase 2: Compute → 执行 ComputeGraph（先 TOOL 节点，后 AI 节点）
Phase 3: Compose → 映射计算结果到 UIComposition，生成 page JSON (PageSpec)
```

---

## RouterAgent (`agents/router.py`) — 内部组件

意图分类 Agent，**不对外暴露端点**，作为 `POST /api/page/followup` 的内部决策器。

```python
# 伪代码 — Phase 4 实现
async def classify_intent(
    message: str, blueprint: Blueprint, page_context: dict | None,
) -> str:
    """返回 action: "chat" | "refine" | "rebuild"。"""
    agent = Agent(
        model=create_model(),
        output_type=IntentResult,
        system_prompt=ROUTER_SYSTEM_PROMPT,
    )
    result = await agent.run(f"Message: {message}\nBlueprint: {blueprint.name}\nContext: {page_context}")
    return result.output.action
```

| action | 含义 | 后端处理 | 前端处理 |
|--------|------|---------|---------|
| `chat` | 数据追问 | PageChatAgent 回答 | 显示 `chatResponse` 文本 |
| `refine` | 页面微调 | PlannerAgent 微调 Blueprint | 自动用新 blueprint 调 `/api/page/generate` |
| `rebuild` | 结构性重建 | PlannerAgent 重新生成 Blueprint | 展示说明，用户确认后调 `/api/page/generate` |

---

## PageChatAgent (`agents/page_chat.py`) — 内部组件

处理页面相关的对话式交互。**不对外暴露端点**，由 followup 端点内部调用。

```python
# 伪代码 — Phase 4 实现
async def page_chat(
    message: str, blueprint: Blueprint, page_context: dict | None,
) -> str:
    """基于页面上下文回答用户追问，返回 Markdown 文本。"""
    agent = Agent(
        model=create_model(),
        system_prompt=f"你是页面数据分析助手。页面: {blueprint.name}。上下文: {page_context}",
    )
    result = await agent.run(message)
    return result.output
```

---

## 统一追问流程 (`POST /api/page/followup`)

```
用户追问
    │
    ▼
POST /api/page/followup
    │
    ├── RouterAgent.classify_intent()
    │       │
    │       ├── "chat"    → PageChatAgent → { action: "chat", chatResponse: "..." }
    │       │
    │       ├── "refine"  → PlannerAgent(微调) → { action: "refine", chatResponse: "...", blueprint: {...} }
    │       │
    │       └── "rebuild" → PlannerAgent(重建) → { action: "rebuild", chatResponse: "...", blueprint: {...} }
    │
    ▼
前端根据 action 字段渲染
    ├── "chat"    → 显示文本回复
    ├── "refine"  → 自动调 /api/page/generate 重新渲染
    └── "rebuild" → 展示说明 → 用户确认 → 调 /api/page/generate
```
