# 多 Agent 设计

> PlannerAgent / ExecutorAgent / RouterAgent / ChatAgent 的分工、实现与协作。

---

## Agent 分工总览

| Agent | 职责 | 输入 | 输出 |
|-------|------|------|------|
| **PlannerAgent** | 理解用户需求，生成 Blueprint | 用户自然语言 | 结构化分析方案 JSON |
| **ExecutorAgent** | 执行分析计划，调用工具，构建页面 | Blueprint + 数据 | SSE 流式页面 |
| **RouterAgent** | 对追问进行意图分类和路由 | 用户追问 | 意图类型 + 路由目标 |
| **ChatAgent** | 处理页面相关的对话式交互 | 用户消息 + 页面上下文 | 文本回复 |

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

## Agent Provider (`agents/provider.py`)

核心：PydanticAI Agent + LiteLLM model + FastMCP tool 桥接。

```python
from pydantic_ai import Agent
from pydantic_ai.models.litellm import LiteLLMModel
from fastmcp import Client
from tools import mcp
from config.settings import get_settings


def create_model(model_name: str | None = None) -> LiteLLMModel:
    """创建 LiteLLM model 实例。"""
    settings = get_settings()
    return LiteLLMModel(model_name or settings.executor_model)


async def execute_mcp_tool(name: str, arguments: dict) -> str:
    """In-process 调用 FastMCP tool。"""
    async with Client(mcp) as client:
        result = await client.call_tool(name, arguments)
        return "\n".join(
            item.text if hasattr(item, "text") else str(item)
            for item in result
        )


def get_mcp_tool_names() -> list[str]:
    """获取所有注册的 FastMCP tool 名称。"""
    return [tool.name for tool in mcp._tool_manager.list_tools()]
```

---

## PlannerAgent (`agents/planner.py`)

输入 user prompt → 输出 `Blueprint`。PydanticAI 的 `result_type` 确保输出结构合法。

```python
from pydantic_ai import Agent
from models.blueprint import Blueprint
from agents.provider import create_model
from config.prompts.planner import PLANNER_SYSTEM_PROMPT
from config.component_registry import COMPONENT_REGISTRY


planner_agent = Agent(
    model=create_model(),
    result_type=Blueprint,
    system_prompt=PLANNER_SYSTEM_PROMPT,
)


@planner_agent.system_prompt
async def add_component_registry(ctx):
    """动态注入组件注册表到 system prompt。"""
    registry_desc = "\n".join(
        f"- {name}: {info['description']}"
        for name, info in COMPONENT_REGISTRY.items()
    )
    return f"\n## Available UI Components\n{registry_desc}\n"


async def generate_blueprint(user_prompt: str, language: str = "en") -> Blueprint:
    """用户输入 → Blueprint。"""
    result = await planner_agent.run(
        f"User request: {user_prompt}\nLanguage: {language}"
    )
    return result.data
```

---

## ExecutorAgent (`agents/executor.py`)

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

## RouterAgent

意图分类 Agent，判断用户追问走哪个路径：

| Intent | 含义 | 触发操作 |
|--------|------|---------|
| `workflow_rebuild` | 重新生成 Blueprint + page | `generateWorkflow()` → `generatePage()` |
| `page_refine` | 仅重新生成 page | `generatePage()` (带修改指令) |
| `data_chat` | 追问对话 | `chatWithPage()` |

---

## ChatAgent

处理页面相关的对话式交互。接收用户消息 + 页面上下文，返回文本回复。

```python
@router.post("/api/page/chat")
async def page_chat(request: PageChatRequest):
    model = create_model()
    agent = Agent(
        model=model,
        system_prompt=f"你是页面数据分析助手。页面摘要：{request.page_context}",
    )
    result = await agent.run(request.user_message)
    return {"success": True, "chat_response": result.data}
```
