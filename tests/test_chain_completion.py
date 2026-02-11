"""Test chain completion — detect when LLM breaks tool chains prematurely.

Problem
-------
PydanticAI's run loop ends when the model returns pure text (no tool calls).
Sometimes the model calls ``search_teacher_documents`` but then emits text
like "已为您找到相关文档" instead of continuing to call ``generate_quiz_questions``.
This is non-deterministic — tests using TestModel (which auto-calls tools)
cannot reproduce the failure.

Approach
--------
1. **FunctionModel**: Simulate exact chain breakage by controlling what the
   model returns at each step.
2. **Chain Validator**: After ``agent.run()`` completes, inspect
   ``result.new_messages()`` to verify expected tools were all called.
3. **Intent → Chain mapping**: Define which user intents require which tool
   chains, so we can detect incomplete chains.

Scenarios
---------
- "根据知识库出题" → search + generate expected → detect break if only search
- "出5道选择题" → generate only → no search required
- "分析班级成绩" → data query chain → detect break if incomplete
"""

from __future__ import annotations

import re
import pytest
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import FunctionModel, AgentInfo

import tools.native_tools  # noqa: F401  populate registry

from agents.native_agent import AgentDeps, NativeAgent


# ── Chain Completion Validator ────────────────────────────────
#
# This logic can be promoted to production code (e.g. a post-turn
# guard in conversation.py) once validated by these tests.


@dataclass
class IntentChain:
    """Expected tool chain for a user intent."""
    name: str
    required_tools: list[str]
    description: str


# Intent patterns → expected tool chains
# Patterns use broad matching: source keyword + action keyword in same message.
# The `.*` between groups handles variable-length content like "出三角函数的题".
_INTENT_CHAINS: list[tuple[re.Pattern, IntentChain]] = [
    (
        re.compile(r"(知识库|文档|资料|上传的).*(出.*?题|生成.*?题|练习|测验)", re.DOTALL),
        IntentChain(
            name="knowledge_quiz",
            required_tools=["search_teacher_documents", "generate_quiz_questions"],
            description="Knowledge-base quiz: must search then generate",
        ),
    ),
    (
        re.compile(r"(知识库|文档|资料|上传的).*(PPT|课件|演示)", re.DOTALL),
        IntentChain(
            name="knowledge_ppt",
            required_tools=["search_teacher_documents", "propose_pptx_outline"],
            description="Knowledge-base PPT: must search then propose outline",
        ),
    ),
    (
        re.compile(r"(知识库|文档|资料|上传的).*(互动.*?网页|互动.*?HTML|网页.*?互动)", re.DOTALL),
        IntentChain(
            name="knowledge_interactive",
            required_tools=["search_teacher_documents", "generate_interactive_html"],
            description="Knowledge-base interactive: must search then generate",
        ),
    ),
]


def detect_intent_chain(user_message: str) -> IntentChain | None:
    """Match user message to an expected tool chain, or None if no chain required."""
    for pattern, chain in _INTENT_CHAINS:
        if pattern.search(user_message):
            return chain
    return None


def extract_called_tools(messages: list[ModelMessage]) -> set[str]:
    """Extract all tool names that were called from PydanticAI message history."""
    tools_called: set[str] = set()
    for msg in messages:
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    tools_called.add(part.tool_name)
    return tools_called


@dataclass
class ChainValidationResult:
    """Result of chain completion validation."""
    complete: bool
    intent: IntentChain | None
    called_tools: set[str]
    missing_tools: set[str]

    @property
    def is_chain_break(self) -> bool:
        """True if an expected chain was detected but not completed."""
        return self.intent is not None and not self.complete


def validate_chain_completion(
    user_message: str,
    result_messages: list[ModelMessage],
) -> ChainValidationResult:
    """Check if the tool chain completed correctly for the given user intent.

    Returns a ChainValidationResult indicating whether:
    - An intent chain was expected (intent is not None)
    - All required tools were called (complete=True)
    - Which tools were called and which are missing
    """
    intent = detect_intent_chain(user_message)
    called = extract_called_tools(result_messages)

    if intent is None:
        return ChainValidationResult(
            complete=True, intent=None, called_tools=called, missing_tools=set()
        )

    required = set(intent.required_tools)
    missing = required - called
    return ChainValidationResult(
        complete=len(missing) == 0,
        intent=intent,
        called_tools=called,
        missing_tools=missing,
    )


# ── Test Helpers ──────────────────────────────────────────────


def _make_deps(**overrides) -> AgentDeps:
    defaults = {
        "teacher_id": "t-chain-001",
        "conversation_id": "conv-chain-001",
        "language": "zh-CN",
    }
    defaults.update(overrides)
    return AgentDeps(**defaults)


# Mock tool return values
_SEARCH_RESULT = {
    "status": "ok",
    "query": "三角函数",
    "results": [
        {"content": "三角函数是数学中的基本函数...", "source": "教案.pdf", "score": 0.92},
        {"content": "正弦函数 sin(x) 的周期为 2π...", "source": "教案.pdf", "score": 0.88},
    ],
    "total": 2,
}

_QUIZ_RESULT = {
    "status": "ok",
    "artifact_type": "quiz",
    "content_format": "json",
    "data": {
        "questions": [
            {"text": "sin(30°) = ?", "answer": "1/2", "type": "choice"},
        ]
    },
}


def _make_chain_breaking_model():
    """FunctionModel that simulates the 'search then stop' bug.

    Step 1: Model returns tool_call(search_teacher_documents)
    Step 2: Model returns text only — chain breaks here!
    (Should have called generate_quiz_questions)
    """
    call_count = 0

    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            # LLM decides to search first (correct)
            return ModelResponse(parts=[
                TextPart(content="好的，让我先查看您的教学文档。"),
                ToolCallPart(
                    tool_name="search_teacher_documents",
                    args={"query": "三角函数"},
                    tool_call_id="tc-search-1",
                ),
            ])
        else:
            # LLM stops with text — BUG! Should have called generate_quiz_questions
            return ModelResponse(parts=[
                TextPart(content="已为您找到相关的三角函数文档。您可以根据这些内容进行教学。"),
            ])

    return FunctionModel(model_fn)


def _make_complete_chain_model():
    """FunctionModel that completes the full search → generate chain.

    Step 1: Model calls search_teacher_documents
    Step 2: Model calls generate_quiz_questions with search context
    Step 3: Model returns summary text
    """
    call_count = 0

    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name="search_teacher_documents",
                    args={"query": "三角函数"},
                    tool_call_id="tc-search-1",
                ),
            ])
        elif call_count == 2:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name="generate_quiz_questions",
                    args={"topic": "三角函数", "count": 5, "context": "三角函数是数学中的基本函数"},
                    tool_call_id="tc-gen-1",
                ),
            ])
        else:
            return ModelResponse(parts=[
                TextPart(content="已为您生成5道三角函数练习题。"),
            ])

    return FunctionModel(model_fn)


def _make_direct_generate_model():
    """FunctionModel that calls generate directly (no search needed).

    For cases like "出5道二次函数选择题" where the topic is explicit.
    """
    call_count = 0

    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name="generate_quiz_questions",
                    args={"topic": "二次函数", "count": 5},
                    tool_call_id="tc-gen-1",
                ),
            ])
        else:
            return ModelResponse(parts=[
                TextPart(content="已为您生成5道二次函数选择题。"),
            ])

    return FunctionModel(model_fn)


def _make_search_error_model():
    """FunctionModel that calls search, gets error result, then stops.

    Simulates the case where search fails and LLM gives up.
    """
    call_count = 0

    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name="search_teacher_documents",
                    args={"query": "三角函数"},
                    tool_call_id="tc-search-1",
                ),
            ])
        else:
            # Search returned error, LLM stops
            return ModelResponse(parts=[
                TextPart(content="抱歉，知识库搜索暂时不可用，请稍后再试。"),
            ])

    return FunctionModel(model_fn)


def _patch_tools():
    """Context manager that mocks the underlying tool implementations."""
    search_mock = patch(
        "tools.document_tools.search_teacher_documents",
        new_callable=AsyncMock,
        return_value=_SEARCH_RESULT,
    )
    quiz_mock = patch(
        "tools.quiz_tools.generate_quiz_questions",
        new_callable=AsyncMock,
        return_value=_QUIZ_RESULT,
    )
    return search_mock, quiz_mock


def _make_agent_with_model(function_model):
    """Create a NativeAgent that uses the given FunctionModel."""
    agent = NativeAgent()
    original_create = agent._create_agent

    def patched_create(toolsets, deps, tracker=None):
        pydantic_agent = original_create(toolsets, deps, tracker=tracker)
        pydantic_agent._model = function_model
        return pydantic_agent

    agent._create_agent = patched_create
    return agent


# ── Test: Intent Detection ────────────────────────────────────


class TestIntentDetection:
    """Verify intent → chain mapping works correctly."""

    def test_knowledge_quiz_detected(self):
        chain = detect_intent_chain("根据知识库帮我出三角函数的题")
        assert chain is not None
        assert chain.name == "knowledge_quiz"
        assert "search_teacher_documents" in chain.required_tools
        assert "generate_quiz_questions" in chain.required_tools

    def test_knowledge_quiz_variant(self):
        chain = detect_intent_chain("用我上传的文档生成练习题")
        assert chain is not None
        assert chain.name == "knowledge_quiz"

    def test_knowledge_ppt_detected(self):
        chain = detect_intent_chain("根据知识库内容生成PPT")
        assert chain is not None
        assert chain.name == "knowledge_ppt"

    def test_direct_quiz_no_chain(self):
        """Explicit topic without knowledge base → no chain required."""
        chain = detect_intent_chain("出5道二次函数选择题")
        assert chain is None

    def test_simple_chat_no_chain(self):
        chain = detect_intent_chain("你好")
        assert chain is None

    def test_knowledge_interactive_detected(self):
        chain = detect_intent_chain("根据知识库做一个互动网页")
        assert chain is not None
        assert chain.name == "knowledge_interactive"


# ── Test: Chain Validation Logic (unit) ───────────────────────


class TestChainValidation:
    """Verify chain validation with synthetic message histories."""

    def test_search_only_is_chain_break(self):
        """Search called but generate NOT called → chain break."""
        messages = [
            ModelResponse(parts=[
                ToolCallPart(
                    tool_name="search_teacher_documents",
                    args={"query": "三角函数"},
                    tool_call_id="tc-1",
                ),
            ]),
            ModelRequest(parts=[
                ToolReturnPart(
                    tool_name="search_teacher_documents",
                    content=_SEARCH_RESULT,
                    tool_call_id="tc-1",
                ),
            ]),
            ModelResponse(parts=[
                TextPart(content="已找到相关文档。"),
            ]),
        ]

        result = validate_chain_completion("根据知识库帮我出三角函数的题", messages)
        assert result.is_chain_break
        assert result.intent.name == "knowledge_quiz"
        assert "generate_quiz_questions" in result.missing_tools
        assert "search_teacher_documents" in result.called_tools

    def test_complete_chain_not_a_break(self):
        """Search + generate both called → complete, no break."""
        messages = [
            ModelResponse(parts=[
                ToolCallPart(
                    tool_name="search_teacher_documents",
                    args={"query": "三角函数"},
                    tool_call_id="tc-1",
                ),
            ]),
            ModelRequest(parts=[
                ToolReturnPart(
                    tool_name="search_teacher_documents",
                    content=_SEARCH_RESULT,
                    tool_call_id="tc-1",
                ),
            ]),
            ModelResponse(parts=[
                ToolCallPart(
                    tool_name="generate_quiz_questions",
                    args={"topic": "三角函数", "count": 5},
                    tool_call_id="tc-2",
                ),
            ]),
            ModelRequest(parts=[
                ToolReturnPart(
                    tool_name="generate_quiz_questions",
                    content=_QUIZ_RESULT,
                    tool_call_id="tc-2",
                ),
            ]),
            ModelResponse(parts=[
                TextPart(content="已为您生成5道三角函数练习题。"),
            ]),
        ]

        result = validate_chain_completion("根据知识库帮我出三角函数的题", messages)
        assert not result.is_chain_break
        assert result.complete
        assert len(result.missing_tools) == 0

    def test_no_chain_expected_always_complete(self):
        """No chain expected → always complete."""
        messages = [
            ModelResponse(parts=[TextPart(content="你好！")]),
        ]
        result = validate_chain_completion("你好", messages)
        assert result.complete
        assert result.intent is None
        assert not result.is_chain_break

    def test_empty_messages_with_chain_expected(self):
        """Chain expected but no tools called at all → break."""
        messages = [
            ModelResponse(parts=[TextPart(content="请告诉我更多信息。")]),
        ]
        result = validate_chain_completion("根据知识库帮我出三角函数的题", messages)
        assert result.is_chain_break
        assert len(result.missing_tools) == 2  # Both search and generate missing


# ── Test: FunctionModel E2E — Chain Breakage ──────────────────


class TestChainBreakageE2E:
    """End-to-end tests using FunctionModel to simulate chain breakage
    through the actual PydanticAI agent loop.
    """

    @pytest.mark.asyncio
    async def test_search_then_stop_detected_as_break(self):
        """Simulate: model searches, then stops with text.

        This is the exact bug from the screenshot — the model says
        "已找到文档" but never calls generate_quiz_questions.
        """
        agent = _make_agent_with_model(_make_chain_breaking_model())
        deps = _make_deps()

        search_mock, quiz_mock = _patch_tools()
        with search_mock, quiz_mock:
            result = await agent.run("根据知识库帮我出三角函数的题", deps=deps)

        # The agent completed — but did it complete the CHAIN?
        new_msgs = result.new_messages()
        validation = validate_chain_completion(
            "根据知识库帮我出三角函数的题", new_msgs
        )

        # This SHOULD be a chain break
        assert validation.is_chain_break, (
            f"Expected chain break but got complete. "
            f"Called: {validation.called_tools}, Missing: {validation.missing_tools}"
        )
        assert "search_teacher_documents" in validation.called_tools
        assert "generate_quiz_questions" in validation.missing_tools

    @pytest.mark.asyncio
    async def test_complete_chain_no_break(self):
        """Simulate: model searches, then generates → complete chain."""
        agent = _make_agent_with_model(_make_complete_chain_model())
        deps = _make_deps()

        search_mock, quiz_mock = _patch_tools()
        with search_mock, quiz_mock:
            result = await agent.run("根据知识库帮我出三角函数的题", deps=deps)

        new_msgs = result.new_messages()
        validation = validate_chain_completion(
            "根据知识库帮我出三角函数的题", new_msgs
        )

        assert not validation.is_chain_break
        assert validation.complete
        assert "search_teacher_documents" in validation.called_tools
        assert "generate_quiz_questions" in validation.called_tools

    @pytest.mark.asyncio
    async def test_direct_generate_no_chain_check(self):
        """Direct quiz request without knowledge base → no chain to validate."""
        agent = _make_agent_with_model(_make_direct_generate_model())
        deps = _make_deps()

        _, quiz_mock = _patch_tools()
        with quiz_mock:
            result = await agent.run("出5道二次函数选择题", deps=deps)

        new_msgs = result.new_messages()
        validation = validate_chain_completion("出5道二次函数选择题", new_msgs)

        # No chain expected, so always complete
        assert validation.complete
        assert validation.intent is None

    @pytest.mark.asyncio
    async def test_search_error_then_stop_is_chain_break(self):
        """Search returns error, model stops → still a chain break.

        Even though search failed, the intent was "知识库出题" so the
        chain validator should flag that generate was never called.
        (In production, this could trigger a retry or fallback.)
        """
        agent = _make_agent_with_model(_make_search_error_model())
        deps = _make_deps()

        error_search = patch(
            "tools.document_tools.search_teacher_documents",
            new_callable=AsyncMock,
            return_value={"status": "error", "query": "三角函数", "results": [], "total": 0},
        )
        with error_search:
            result = await agent.run("根据知识库帮我出三角函数的题", deps=deps)

        new_msgs = result.new_messages()
        validation = validate_chain_completion(
            "根据知识库帮我出三角函数的题", new_msgs
        )

        assert validation.is_chain_break
        assert "generate_quiz_questions" in validation.missing_tools


# ── Test: Output text heuristic — detect "announce without action" ─


class TestAnnounceWithoutAction:
    """Detect the pattern: LLM says "我来帮您查/生成" but doesn't call tools.

    This is the #2 rule from the system prompt:
    "禁止预告不执行: 不要说'我需要先查看'然后停止"
    """

    _ANNOUNCE_PATTERNS = [
        re.compile(r"(我来|让我|我需要|我先).{0,10}(查看|查询|检索|搜索|查一下|找一下)"),
        re.compile(r"(我来|让我|我需要|正在).{0,10}(生成|出题|制作|创建)"),
        re.compile(r"(好的|收到).{0,6}(我来|让我|正在)"),
    ]

    @staticmethod
    def _has_announcement(text: str) -> bool:
        for p in TestAnnounceWithoutAction._ANNOUNCE_PATTERNS:
            if p.search(text):
                return True
        return False

    @staticmethod
    def _extract_final_text(messages: list[ModelMessage]) -> str:
        """Extract the final text output from the agent's messages."""
        for msg in reversed(messages):
            if isinstance(msg, ModelResponse):
                for part in msg.parts:
                    if isinstance(part, TextPart):
                        return part.content
        return ""

    def test_chain_break_has_announcement(self):
        """The chain-breaking model's output contains an announcement."""
        # Simulate the broken chain output
        text = "好的，让我先查看您的教学文档。已为您找到相关的三角函数文档。"
        assert self._has_announcement(text)

    def test_complete_chain_no_false_positive(self):
        """The complete chain's final output is a completion summary, not announcement."""
        text = "已为您生成5道三角函数练习题。"
        assert not self._has_announcement(text)

    def test_detect_announce_then_stop_pattern(self):
        """Combined check: announcement in text + missing tools = definite bug."""
        messages = [
            ModelResponse(parts=[
                TextPart(content="好的，让我先查看您的教学文档。"),
                ToolCallPart(
                    tool_name="search_teacher_documents",
                    args={"query": "三角函数"},
                    tool_call_id="tc-1",
                ),
            ]),
            ModelRequest(parts=[
                ToolReturnPart(
                    tool_name="search_teacher_documents",
                    content=_SEARCH_RESULT,
                    tool_call_id="tc-1",
                ),
            ]),
            ModelResponse(parts=[
                TextPart(content="已为您找到相关的三角函数文档。您可以根据这些内容进行教学。"),
            ]),
        ]

        # Chain validation
        chain_result = validate_chain_completion(
            "根据知识库帮我出三角函数的题", messages
        )
        assert chain_result.is_chain_break

        # Text heuristic: final output doesn't mention generation completion
        final_text = self._extract_final_text(messages)
        assert "生成" not in final_text or "练习题" not in final_text
        # The response talks about "找到文档" not "生成了题目" — incomplete


# ── Test: Extract tools utility ───────────────────────────────


class TestExtractCalledTools:
    """Verify the extract_called_tools helper."""

    def test_extracts_from_model_response(self):
        messages = [
            ModelResponse(parts=[
                ToolCallPart(tool_name="tool_a", args={}, tool_call_id="1"),
                ToolCallPart(tool_name="tool_b", args={}, tool_call_id="2"),
            ]),
        ]
        assert extract_called_tools(messages) == {"tool_a", "tool_b"}

    def test_ignores_text_parts(self):
        messages = [
            ModelResponse(parts=[TextPart(content="hello")]),
        ]
        assert extract_called_tools(messages) == set()

    def test_handles_mixed_messages(self):
        messages = [
            ModelRequest(parts=[
                ToolReturnPart(tool_name="tool_a", content={}, tool_call_id="1"),
            ]),
            ModelResponse(parts=[
                ToolCallPart(tool_name="tool_b", args={}, tool_call_id="2"),
                TextPart(content="done"),
            ]),
        ]
        # Only ToolCallPart from ModelResponse counts
        assert extract_called_tools(messages) == {"tool_b"}

    def test_deduplicates(self):
        messages = [
            ModelResponse(parts=[
                ToolCallPart(tool_name="tool_a", args={}, tool_call_id="1"),
            ]),
            ModelResponse(parts=[
                ToolCallPart(tool_name="tool_a", args={}, tool_call_id="2"),
            ]),
        ]
        assert extract_called_tools(messages) == {"tool_a"}
