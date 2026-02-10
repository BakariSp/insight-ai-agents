"""NativeAgent — AI native tool-calling runtime.

Step 1.2 of AI native rewrite.  Single runtime that:
1. Selects toolset subset based on context (loose inclusion, not exclusive routing)
2. Creates a PydanticAI Agent with selected tools each turn
3. Runs ``agent.run_stream()`` / ``agent.run()`` — LLM autonomously decides tool usage
4. Emits structured JSON logs for observability

Replaces: RouterAgent + ExecutorAgent + ChatAgent + PatchAgent + hand-coded tool loops.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Sequence

from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.messages import ModelMessage, ModelRequest, UserContent, UserPromptPart
from pydantic_ai.result import StreamedRunResult
from pydantic_ai.settings import ModelSettings

from agents.provider import create_model
from config.prompts.block_schemas import BLOCK_SCHEMA_PROMPT
from config.prompts.native_agent import SYSTEM_PROMPT
from config.settings import get_settings
from services.metrics import get_metrics_collector
from services.tool_tracker import ToolTracker
from tools.registry import (
    ALL_TOOLSETS,
    ALWAYS_TOOLSETS,
    TOOLSET_ANALYSIS,
    TOOLSET_ARTIFACT_OPS,
    TOOLSET_GENERATION,
    get_tools,
    get_tools_raw,
)

logger = logging.getLogger(__name__)

# ── Agent Dependencies ──────────────────────────────────────


@dataclass
class AgentDeps:
    """Dependencies injected into every tool via ``RunContext[AgentDeps]``."""

    teacher_id: str
    conversation_id: str
    language: str = "zh-CN"
    class_id: str | None = None
    has_artifacts: bool = False
    turn_id: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    # Per-turn dedup: prevents the LLM from calling the same generation
    # tool multiple times in a single turn (e.g. generate_quiz_questions x2).
    _called_gen_tools: set[str] = field(default_factory=set, repr=False)


# ── Toolset Selection (loose inclusion) ─────────────────────

# Keywords for loose toolset matching — false positives are cheap,
# false negatives break functionality.
_GENERATE_KEYWORDS = [
    "出题", "选择题", "填空题", "判断题", "题目", "试卷", "测试",
    "生成", "做一个", "创建", "制作", "PPT", "ppt", "文稿",
    "互动", "quiz", "create", "generate", "make", "写", "编写",
    "设计", "prepare", "draft",
    # Step 3 regression: expanded for common education generation patterns.
    # "道" = counter word for questions, "再出"/"重新" = redo/regenerate.
    "道", "再出", "重新",
]

_MODIFY_KEYWORDS = [
    "修改", "改", "换", "删", "移动", "调整", "更新", "替换",
    "加", "添加", "增加", "加上", "去掉", "新增", "加入", "补充",
    # Colloquial / imperative patterns (把X弄上去, 把X改成Y, 优化一下)
    "优化", "改进", "完善", "美化", "简化", "去除", "取消",
    "放大", "缩小", "变", "弄", "缩减", "扩展", "升级", "精简",
    "update", "change", "edit", "revise", "modify", "remove",
    "replace", "fix", "correct", "add", "insert", "tweak", "enhance",
]

_ANALYZE_KEYWORDS = [
    "成绩", "分析", "统计", "对比", "薄弱", "错题", "掌握",
    "report", "数据", "分数", "排名", "平均", "表现",
    "grade", "score", "analyze", "compare", "performance",
]


def _extract_recent_user_text(
    history: Sequence[ModelMessage] | None,
    max_turns: int = 3,
) -> str:
    """Extract recent user message text from PydanticAI message history.

    Used for toolset selection so that clarification follow-ups (e.g. "引力系统")
    inherit the intent from the original request (e.g. "生成一个粒子模拟网站").
    """
    if not history:
        return ""
    parts: list[str] = []
    for msg in reversed(history):
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    # Skip system context notes injected by conversation_store
                    if part.content.startswith("[系统备注"):
                        continue
                    parts.append(part.content)
                    if len(parts) >= max_turns:
                        return " ".join(reversed(parts))
    return " ".join(reversed(parts))


def _select_toolsets_keyword(
    message: str,
    deps: AgentDeps,
    recent_context: str = "",
) -> list[str]:
    """Select toolsets via keyword heuristics (fallback path).

    Uses LOOSE inclusion — it's better to include extra tools (small context cost)
    than to miss needed tools (functionality broken).

    Checks both the current *message* and *recent_context* (previous user
    messages) so that clarification follow-ups inherit the original intent.
    """
    combined = f"{message} {recent_context}"
    sets = list(ALWAYS_TOOLSETS)  # base_data + platform always included

    if _might_generate(combined):
        sets.append(TOOLSET_GENERATION)

    if deps.has_artifacts or _might_modify(combined):
        sets.append(TOOLSET_ARTIFACT_OPS)

    if deps.class_id or _might_analyze(combined):
        sets.append(TOOLSET_ANALYSIS)

    return sets


async def select_toolsets(
    message: str,
    deps: AgentDeps,
    message_history: Sequence[ModelMessage] | None = None,
) -> list[str]:
    """Select toolsets — LLM planner with keyword fallback.

    When ``TOOLSET_PLANNER_ENABLED`` is true, calls a fast LLM to decide
    which optional toolsets to include.  Falls back to keyword heuristics
    on timeout, low confidence, or any error.

    *message_history* provides conversation context so that follow-up
    messages (e.g. clarification responses) inherit the toolsets needed
    by the original request.
    """
    settings = get_settings()
    recent_context = _extract_recent_user_text(message_history)

    if not settings.toolset_planner_enabled:
        result = _select_toolsets_keyword(message, deps, recent_context)
        _log_toolset_selection(deps, message, result, source="keyword")
        return result

    try:
        from agents.toolset_planner import plan_toolsets

        # Include recent context so the planner sees the original intent
        planner_message = message
        if recent_context:
            planner_message = f"{message}\n[Previous context: {recent_context}]"

        planner_result = await asyncio.wait_for(
            plan_toolsets(
                planner_message,
                has_artifacts=deps.has_artifacts,
                has_class_id=bool(deps.class_id),
            ),
            timeout=settings.toolset_planner_timeout_s,
        )

        if planner_result.confidence >= settings.toolset_planner_confidence_threshold:
            sets = list(ALWAYS_TOOLSETS) + list(planner_result.toolsets)
            # Hard constraints — planner may omit these, enforce in code.
            # Keyword safety-net: even when planner is confident, keyword
            # signals override omissions (false positives are cheap).
            if (deps.has_artifacts or _might_modify(message)) and TOOLSET_ARTIFACT_OPS not in sets:
                sets.append(TOOLSET_ARTIFACT_OPS)
            if (deps.class_id or _might_analyze(message)) and TOOLSET_ANALYSIS not in sets:
                sets.append(TOOLSET_ANALYSIS)
            if _might_generate(message) and TOOLSET_GENERATION not in sets:
                sets.append(TOOLSET_GENERATION)
            _log_toolset_selection(
                deps, message, sets,
                source="planner",
                confidence=planner_result.confidence,
            )
            return sets

        # Low confidence — fall back to keywords
        keyword_sets = _select_toolsets_keyword(message, deps, recent_context)
        _log_toolset_selection(
            deps, message, keyword_sets,
            source="keyword_fallback",
            confidence=planner_result.confidence,
        )
        return keyword_sets

    except Exception as exc:
        keyword_sets = _select_toolsets_keyword(message, deps, recent_context)
        _log_toolset_selection(
            deps, message, keyword_sets,
            source="error_fallback",
            error=str(exc),
        )
        return keyword_sets


def _might_generate(message: str) -> bool:
    return any(kw in message for kw in _GENERATE_KEYWORDS)


def _might_modify(message: str) -> bool:
    return any(kw in message for kw in _MODIFY_KEYWORDS)


def _might_analyze(message: str) -> bool:
    return any(kw in message for kw in _ANALYZE_KEYWORDS)


# ── NativeAgent ─────────────────────────────────────────────

# Budget limits
MAX_TOOL_CALLS = 10
MAX_TURN_DURATION_S = 120


class NativeAgent:
    """AI native runtime — LLM autonomously selects and executes tools.

    Usage::

        agent = NativeAgent()
        async with agent.run_stream(
            message="帮我出 5 道选择题",
            deps=AgentDeps(teacher_id="t-001", conversation_id="conv-xxx"),
        ) as stream:
            async for response, is_last in stream.stream_responses():
                ...
    """

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name

    def _create_agent(
        self,
        toolsets: list[str],
        deps: AgentDeps,
        tracker: ToolTracker | None = None,
    ) -> Agent[AgentDeps, str]:
        """Create a PydanticAI Agent with selected toolset for this turn.

        When *tracker* is provided, each tool function is wrapped with
        ``tracker.wrap()`` so the tracker can emit running/done/error and
        stream-item events that the SSE layer converts to ``data-*`` events.
        """
        if tracker is not None:
            from pydantic_ai import Tool
            from pydantic_ai.toolsets import FunctionToolset

            raw_tools = get_tools_raw(toolsets)
            wrapped = [
                Tool(tracker.wrap(rt.func), name=rt.name, max_retries=2)
                for rt in raw_tools
            ]
            toolset = FunctionToolset(wrapped)
        else:
            toolset = get_tools(toolsets)

        # Build system prompt with optional context injection
        system_prompt = self._build_system_prompt(deps.context)

        model = create_model(self._model_name)

        # Qwen-specific tuning: low temperature improves tool-calling
        # reliability (high temp causes Qwen to prefer text over tools),
        # and enable_thinking must be disabled to avoid stop-word issues.
        # Other providers (OpenAI, Gemini, etc.) work fine with defaults
        # and would reject the extra_body parameter.
        settings_kwargs: dict[str, Any] = {"max_tokens": 8192}
        resolved_name = self._model_name or get_settings().default_model
        if resolved_name.startswith("dashscope/") or resolved_name.startswith("qwen"):
            settings_kwargs["temperature"] = 0.3
            settings_kwargs["extra_body"] = {"enable_thinking": False}

        return Agent(
            model=model,
            instructions=system_prompt,
            deps_type=AgentDeps,
            toolsets=[toolset],
            model_settings=ModelSettings(**settings_kwargs),
            output_retries=3,
        )

    def _build_system_prompt(self, context: dict[str, Any]) -> str:
        """Build system prompt with optional context injection.

        Args:
            context: Context dict from AgentDeps (may contain resolved_entities, blueprint_hints)

        Returns:
            System prompt string with injected context
        """
        prompt = SYSTEM_PROMPT

        # Inject resolved entities from blueprint execution
        if "resolved_entities" in context:
            resolved_entities = context["resolved_entities"]
            if resolved_entities:
                entity_lines = []
                for key, entity in resolved_entities.items():
                    entity_lines.append(f"- {key} = {entity['id']} ({entity['displayName']})")

                prompt += "\n\n## 当前上下文实体\n"
                prompt += "\n".join(entity_lines)
                prompt += "\n调用工具时请使用上述 ID。"

        # Inject output hints from blueprint
        if "blueprint_hints" in context:
            hints = context["blueprint_hints"]
            if hints and hints.get("expectedArtifacts"):
                artifacts = hints["expectedArtifacts"]

                # If "report" in artifacts, inject tab structure + block schemas
                if "report" in artifacts and hints.get("tabs"):
                    tabs = hints["tabs"]
                    prompt += "\n\n## 输出结构要求 (Blueprint 报告模式)\n"
                    prompt += "这是一个 Blueprint 模板执行，你正在生成一份**专业分析报告**。\n"
                    prompt += "请按以下 tab 结构组织输出，每个 tab 用 `## [TAB:{key}] {label}` 标记开头:\n\n"
                    for tab in tabs:
                        desc = tab.get("description", "")
                        prompt += f"### {tab['label']} (key: {tab['key']})\n{desc}\n\n"

                    # Inject block schemas — LLM uses ```block:type fences
                    prompt += BLOCK_SCHEMA_PROMPT

                    prompt += "\n根据实际数据灵活调整，如数据不支持某个 tab 可跳过。"

        return prompt

    async def run_stream(
        self,
        message: str,
        deps: AgentDeps,
        message_history: Sequence[ModelMessage] | None = None,
        tracker: ToolTracker | None = None,
        user_prompt: str | Sequence[UserContent] | None = None,
    ) -> AsyncIterator[StreamedRunResult[AgentDeps, str]]:
        """Run the agent with streaming output.

        Returns an async context manager yielding a StreamedRunResult.
        Caller should use ``async with`` to consume the stream.

        This is an async generator that yields exactly one StreamedRunResult.

        Args:
            tracker: Optional ToolTracker for real-time tool progress events.
            user_prompt: Enriched prompt (multimodal or document-augmented).
                         When provided, this is sent to the LLM instead of
                         *message*.  *message* is still used for toolset
                         selection and logging.
        """
        selected = await select_toolsets(message, deps, message_history)
        if not deps.turn_id:
            deps.turn_id = f"turn-{uuid.uuid4().hex[:10]}"
        agent = self._create_agent(selected, deps, tracker=tracker)

        _log_turn_start(deps, message, selected)
        start_time = time.monotonic()

        async with agent.run_stream(
            user_prompt or message,
            deps=deps,
            message_history=list(message_history) if message_history else None,
            usage_limits=UsageLimits(request_limit=MAX_TOOL_CALLS),
        ) as stream:
            yield stream

        elapsed_ms = (time.monotonic() - start_time) * 1000
        _log_turn_end(deps, stream, elapsed_ms, selected)

    async def run(
        self,
        message: str,
        deps: AgentDeps,
        message_history: Sequence[ModelMessage] | None = None,
        user_prompt: str | Sequence[UserContent] | None = None,
    ):
        """Run the agent and return complete result (non-streaming).

        Args:
            user_prompt: Enriched prompt (multimodal or document-augmented).
                         When provided, this is sent to the LLM instead of
                         *message*.
        """
        selected = await select_toolsets(message, deps, message_history)
        if not deps.turn_id:
            deps.turn_id = f"turn-{uuid.uuid4().hex[:10]}"
        agent = self._create_agent(selected, deps)

        _log_turn_start(deps, message, selected)
        start_time = time.monotonic()

        result = await agent.run(
            user_prompt or message,
            deps=deps,
            message_history=list(message_history) if message_history else None,
            usage_limits=UsageLimits(request_limit=MAX_TOOL_CALLS),
        )

        elapsed_ms = (time.monotonic() - start_time) * 1000
        _log_turn_end_sync(deps, result, elapsed_ms, selected)
        return result


# ── Structured Logging (Step 1.5) ───────────────────────────


def _log_toolset_selection(
    deps: AgentDeps,
    message: str,
    toolsets: list[str],
    *,
    source: str,
    confidence: float = 0.0,
    error: str = "",
) -> None:
    """Emit structured JSON log for toolset selection decision."""
    logger.info(json.dumps({
        "event": "toolset_selection",
        "conversation_id": deps.conversation_id,
        "turn_id": deps.turn_id,
        "teacher_id": deps.teacher_id,
        "source": source,
        "toolsets": toolsets,
        "confidence": confidence,
        "error": error,
        "message_preview": message[:100],
    }, ensure_ascii=False))


def _log_turn_start(deps: AgentDeps, message: str, toolsets: list[str]) -> None:
    """Emit structured JSON log at turn start."""
    logger.info(json.dumps({
        "event": "turn_start",
        "conversation_id": deps.conversation_id,
        "turn_id": deps.turn_id,
        "teacher_id": deps.teacher_id,
        "toolsets": toolsets,
        "message_preview": message[:100],
    }, ensure_ascii=False))


def _log_turn_end(
    deps: AgentDeps,
    stream: StreamedRunResult,
    elapsed_ms: float,
    toolsets: list[str],
) -> None:
    """Emit structured JSON log at turn end (streaming mode)."""
    usage = stream.usage()
    metrics = get_metrics_collector().get_turn_summary(deps.turn_id)
    logger.info(json.dumps({
        "event": "turn_end",
        "conversation_id": deps.conversation_id,
        "turn_id": deps.turn_id,
        "teacher_id": deps.teacher_id,
        "toolsets": toolsets,
        "tool_call_count": metrics.get("tool_call_count", 0),
        "tool_error_count": metrics.get("tool_error_count", 0),
        "tool_latency_ms": round(metrics.get("total_latency_ms", 0.0), 1),
        "total_latency_ms": round(elapsed_ms, 1),
        "token_usage_input": getattr(usage, "request_tokens", None),
        "token_usage_output": getattr(usage, "response_tokens", None),
    }, ensure_ascii=False))


def _log_turn_end_sync(
    deps: AgentDeps,
    result: Any,
    elapsed_ms: float,
    toolsets: list[str],
) -> None:
    """Emit structured JSON log at turn end (non-streaming mode)."""
    usage = result.usage() if hasattr(result, "usage") else None
    metrics = get_metrics_collector().get_turn_summary(deps.turn_id)
    logger.info(json.dumps({
        "event": "turn_end",
        "conversation_id": deps.conversation_id,
        "turn_id": deps.turn_id,
        "teacher_id": deps.teacher_id,
        "toolsets": toolsets,
        "tool_call_count": metrics.get("tool_call_count", 0),
        "tool_error_count": metrics.get("tool_error_count", 0),
        "tool_latency_ms": round(metrics.get("total_latency_ms", 0.0), 1),
        "total_latency_ms": round(elapsed_ms, 1),
        "token_usage_input": getattr(usage, "request_tokens", None) if usage else None,
        "token_usage_output": getattr(usage, "response_tokens", None) if usage else None,
    }, ensure_ascii=False))
