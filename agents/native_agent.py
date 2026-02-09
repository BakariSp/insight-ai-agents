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
from pydantic_ai.messages import ModelMessage
from pydantic_ai.result import StreamedRunResult
from pydantic_ai.settings import ModelSettings

from agents.provider import create_model
from config.prompts.native_agent import SYSTEM_PROMPT
from config.settings import get_settings
from services.metrics import get_metrics_collector
from tools.registry import (
    ALL_TOOLSETS,
    ALWAYS_TOOLSETS,
    TOOLSET_ANALYSIS,
    TOOLSET_ARTIFACT_OPS,
    TOOLSET_GENERATION,
    get_tools,
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
    "update", "change", "edit", "revise", "modify", "remove",
    "replace", "fix", "correct",
]

_ANALYZE_KEYWORDS = [
    "成绩", "分析", "统计", "对比", "薄弱", "错题", "掌握",
    "report", "数据", "分数", "排名", "平均", "表现",
    "grade", "score", "analyze", "compare", "performance",
]


def _select_toolsets_keyword(message: str, deps: AgentDeps) -> list[str]:
    """Select toolsets via keyword heuristics (fallback path).

    Uses LOOSE inclusion — it's better to include extra tools (small context cost)
    than to miss needed tools (functionality broken).
    """
    sets = list(ALWAYS_TOOLSETS)  # base_data + platform always included

    if _might_generate(message):
        sets.append(TOOLSET_GENERATION)

    if deps.has_artifacts or _might_modify(message):
        sets.append(TOOLSET_ARTIFACT_OPS)

    if deps.class_id or _might_analyze(message):
        sets.append(TOOLSET_ANALYSIS)

    return sets


async def select_toolsets(message: str, deps: AgentDeps) -> list[str]:
    """Select toolsets — LLM planner with keyword fallback.

    When ``TOOLSET_PLANNER_ENABLED`` is true, calls a fast LLM to decide
    which optional toolsets to include.  Falls back to keyword heuristics
    on timeout, low confidence, or any error.
    """
    settings = get_settings()

    if not settings.toolset_planner_enabled:
        result = _select_toolsets_keyword(message, deps)
        _log_toolset_selection(deps, message, result, source="keyword")
        return result

    try:
        from agents.toolset_planner import plan_toolsets

        planner_result = await asyncio.wait_for(
            plan_toolsets(
                message,
                has_artifacts=deps.has_artifacts,
                has_class_id=bool(deps.class_id),
            ),
            timeout=settings.toolset_planner_timeout_s,
        )

        if planner_result.confidence >= settings.toolset_planner_confidence_threshold:
            sets = list(ALWAYS_TOOLSETS) + list(planner_result.toolsets)
            _log_toolset_selection(
                deps, message, sets,
                source="planner",
                confidence=planner_result.confidence,
            )
            return sets

        # Low confidence — fall back to keywords
        keyword_sets = _select_toolsets_keyword(message, deps)
        _log_toolset_selection(
            deps, message, keyword_sets,
            source="keyword_fallback",
            confidence=planner_result.confidence,
        )
        return keyword_sets

    except Exception as exc:
        keyword_sets = _select_toolsets_keyword(message, deps)
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
    ) -> Agent[AgentDeps, str]:
        """Create a PydanticAI Agent with selected toolset for this turn."""
        toolset = get_tools(toolsets)
        model = create_model(self._model_name)
        return Agent(
            model=model,
            instructions=SYSTEM_PROMPT,
            deps_type=AgentDeps,
            toolsets=[toolset],
            model_settings=ModelSettings(
                max_tokens=4096,
            ),
        )

    async def run_stream(
        self,
        message: str,
        deps: AgentDeps,
        message_history: Sequence[ModelMessage] | None = None,
    ) -> AsyncIterator[StreamedRunResult[AgentDeps, str]]:
        """Run the agent with streaming output.

        Returns an async context manager yielding a StreamedRunResult.
        Caller should use ``async with`` to consume the stream.

        This is an async generator that yields exactly one StreamedRunResult.
        """
        selected = await select_toolsets(message, deps)
        if not deps.turn_id:
            deps.turn_id = f"turn-{uuid.uuid4().hex[:10]}"
        agent = self._create_agent(selected, deps)

        _log_turn_start(deps, message, selected)
        start_time = time.monotonic()

        async with agent.run_stream(
            message,
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
    ):
        """Run the agent and return complete result (non-streaming)."""
        selected = await select_toolsets(message, deps)
        if not deps.turn_id:
            deps.turn_id = f"turn-{uuid.uuid4().hex[:10]}"
        agent = self._create_agent(selected, deps)

        _log_turn_start(deps, message, selected)
        start_time = time.monotonic()

        result = await agent.run(
            message,
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
