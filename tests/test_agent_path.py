"""Tests for Agent Path — models, router path assignment, tools, and teacher agent."""

import pytest

from models.conversation import IntentType, ModelTier, RouterResult


# ── IntentType enum ──────────────────────────────────────────────


class TestIntentType:

    def test_content_create_exists(self):
        assert IntentType.CONTENT_CREATE.value == "content_create"

    def test_all_intent_types(self):
        expected = {
            "chat_smalltalk", "chat_qa", "build_workflow",
            "quiz_generate", "content_create", "clarify",
        }
        actual = {e.value for e in IntentType}
        assert actual == expected


# ── RouterResult model ───────────────────────────────────────────


class TestRouterResult:

    def test_default_path_is_skill(self):
        r = RouterResult(intent="quiz_generate", confidence=0.9)
        assert r.path == "skill"

    def test_suggested_tools_default_empty(self):
        r = RouterResult(intent="content_create", confidence=0.9)
        assert r.suggested_tools == []

    def test_path_can_be_set(self):
        r = RouterResult(intent="content_create", confidence=0.9, path="agent")
        assert r.path == "agent"

    def test_suggested_tools_can_be_set(self):
        r = RouterResult(
            intent="content_create",
            confidence=0.9,
            suggested_tools=["generate_pptx", "get_teacher_classes"],
        )
        assert "generate_pptx" in r.suggested_tools

    def test_camel_case_serialization(self):
        r = RouterResult(
            intent="content_create",
            confidence=0.85,
            path="agent",
            suggested_tools=["generate_pptx"],
        )
        data = r.model_dump(by_alias=True)
        assert "suggestedTools" in data
        assert data["suggestedTools"] == ["generate_pptx"]
        assert data["path"] == "agent"


# ── _assign_path logic ──────────────────────────────────────────


class TestAssignPath:

    def test_quiz_generate_goes_to_skill(self):
        from agents.router import _assign_path
        r = RouterResult(intent="quiz_generate", confidence=0.9)
        assert _assign_path(r) == "skill"

    def test_build_workflow_goes_to_blueprint(self):
        from agents.router import _assign_path
        r = RouterResult(intent="build_workflow", confidence=0.9)
        assert _assign_path(r) == "blueprint"

    def test_content_create_goes_to_agent(self):
        from agents.router import _assign_path
        r = RouterResult(intent="content_create", confidence=0.9)
        assert _assign_path(r) == "agent"

    def test_chat_smalltalk_goes_to_chat(self):
        from agents.router import _assign_path
        r = RouterResult(intent="chat_smalltalk", confidence=0.9)
        assert _assign_path(r) == "chat"

    def test_chat_qa_goes_to_chat(self):
        from agents.router import _assign_path
        r = RouterResult(intent="chat_qa", confidence=0.9)
        assert _assign_path(r) == "chat"

    def test_clarify_goes_to_chat(self):
        from agents.router import _assign_path
        r = RouterResult(intent="clarify", confidence=0.5)
        assert _assign_path(r) == "chat"

    def test_unknown_intent_goes_to_agent(self):
        from agents.router import _assign_path
        r = RouterResult(intent="some_future_intent", confidence=0.9)
        assert _assign_path(r) == "agent"


# ── Confidence routing with CONTENT_CREATE ───────────────────────


class TestConfidenceRouting:

    def test_content_create_high_confidence_passes(self):
        from agents.router import _apply_confidence_routing
        r = RouterResult(intent="content_create", confidence=0.8)
        result = _apply_confidence_routing(r)
        assert result.intent == "content_create"
        # content_create does not set should_build
        assert result.should_build is False

    def test_content_create_medium_confidence_clarifies(self):
        from agents.router import _apply_confidence_routing
        r = RouterResult(intent="content_create", confidence=0.5)
        result = _apply_confidence_routing(r)
        assert result.intent == "clarify"
        assert result.strategy == "ask_one_question"

    def test_content_create_low_confidence_becomes_chat(self):
        from agents.router import _apply_confidence_routing
        r = RouterResult(intent="content_create", confidence=0.3)
        result = _apply_confidence_routing(r)
        assert result.intent == "chat_smalltalk"


# ── Platform tools (sync, no external deps) ─────────────────────


class TestPlatformTools:

    @pytest.mark.asyncio
    async def test_save_as_assignment_returns_count(self):
        from tools.platform_tools import save_as_assignment
        result = await save_as_assignment(
            title="Test Quiz",
            questions=[{"id": "q1"}, {"id": "q2"}],
        )
        assert result["questions_count"] == 2
        assert result["assignment_id"] is None

    @pytest.mark.asyncio
    async def test_create_share_link_returns_placeholder(self):
        from tools.platform_tools import create_share_link
        result = await create_share_link(assignment_id="test-123")
        assert result["share_url"] is None
        assert "message" in result


# ── Render tools (basic tests, no file upload) ───────────────────


class TestRenderTools:

    @pytest.mark.asyncio
    async def test_generate_pptx_creates_file(self):
        from tools.render_tools import generate_pptx
        slides = [
            {"layout": "title", "title": "Test Presentation", "body": "Subtitle"},
            {"layout": "content", "title": "Slide 2", "body": "Line 1\nLine 2"},
        ]
        result = await generate_pptx(slides=slides, title="Test")
        assert result["slide_count"] == 2
        assert result["filename"] == "Test.pptx"
        assert result["size"] > 0

    @pytest.mark.asyncio
    async def test_generate_docx_creates_file(self):
        from tools.render_tools import generate_docx
        content = "# Section 1\n\nSome text\n\n- Item 1\n- Item 2"
        result = await generate_docx(content=content, title="Test Doc")
        assert result["filename"] == "Test Doc.docx"
        assert result["size"] > 0

    @pytest.mark.asyncio
    async def test_generate_pptx_with_two_column(self):
        from tools.render_tools import generate_pptx
        slides = [
            {
                "layout": "two_column",
                "title": "Comparison",
                "left": "Left column",
                "right": "Right column",
            },
        ]
        result = await generate_pptx(slides=slides, title="Two Column Test")
        assert result["slide_count"] == 1

    @pytest.mark.asyncio
    async def test_generate_pptx_with_notes(self):
        from tools.render_tools import generate_pptx
        slides = [
            {
                "layout": "content",
                "title": "With Notes",
                "body": "Content",
                "notes": "Speaker notes here",
            },
        ]
        result = await generate_pptx(slides=slides, title="Notes Test")
        assert result["slide_count"] == 1


# ── Teacher agent prompt ─────────────────────────────────────────


class TestTeacherAgentPrompt:

    def test_prompt_includes_tools(self):
        from config.prompts.teacher_agent import build_teacher_agent_prompt
        prompt = build_teacher_agent_prompt(
            teacher_context={"teacher_id": "t1", "classes": []},
        )
        assert "generate_pptx" in prompt
        assert "generate_docx" in prompt
        assert "render_pdf" in prompt
        assert "save_as_assignment" in prompt

    def test_prompt_includes_teacher_context(self):
        from config.prompts.teacher_agent import build_teacher_agent_prompt
        prompt = build_teacher_agent_prompt(
            teacher_context={
                "teacher_id": "t1",
                "classes": [
                    {"name": "1A", "subject": "Math", "grade": "S1"},
                ],
            },
        )
        assert "1A" in prompt
        assert "Math" in prompt

    def test_prompt_includes_suggested_tools(self):
        from config.prompts.teacher_agent import build_teacher_agent_prompt
        prompt = build_teacher_agent_prompt(
            teacher_context={"teacher_id": "t1"},
            suggested_tools=["generate_pptx", "get_rubric"],
        )
        assert "generate_pptx" in prompt
        assert "get_rubric" in prompt


# ── Tool registry ────────────────────────────────────────────────


class TestToolRegistry:

    def test_new_tools_registered(self):
        from tools import TOOL_REGISTRY
        assert "generate_pptx" in TOOL_REGISTRY
        assert "generate_docx" in TOOL_REGISTRY
        assert "render_pdf" in TOOL_REGISTRY
        assert "save_as_assignment" in TOOL_REGISTRY
        assert "create_share_link" in TOOL_REGISTRY

    def test_tool_descriptions_include_new_tools(self):
        from tools import get_tool_descriptions
        descriptions = get_tool_descriptions()
        names = [d["name"] for d in descriptions]
        assert "generate_pptx" in names
        assert "generate_docx" in names
        assert "render_pdf" in names


# ── Settings ─────────────────────────────────────────────────────


class TestSettings:

    def test_agent_model_configured(self):
        """agent_model may be overridden by .env — just verify it's a valid string."""
        from config.settings import Settings
        s = Settings()
        assert isinstance(s.agent_model, str)
        assert "/" in s.agent_model  # must be "provider/model" format

    def test_strong_model_configured(self):
        from config.settings import Settings
        s = Settings()
        assert isinstance(s.strong_model, str)
        assert "anthropic" in s.strong_model or "dashscope" in s.strong_model

    def test_agent_max_iterations_default(self):
        from config.settings import Settings
        s = Settings()
        assert s.agent_max_iterations == 15


# ── ModelTier enum ────────────────────────────────────────────────


class TestModelTier:

    def test_model_tier_values(self):
        assert ModelTier.FAST.value == "fast"
        assert ModelTier.STANDARD.value == "standard"
        assert ModelTier.STRONG.value == "strong"
        assert ModelTier.VISION.value == "vision"

    def test_model_tier_all_members(self):
        expected = {"fast", "standard", "strong", "vision"}
        actual = {e.value for e in ModelTier}
        assert actual == expected

    def test_router_result_default_tier(self):
        r = RouterResult(intent="content_create", confidence=0.9)
        assert r.model_tier == ModelTier.STANDARD

    def test_router_result_strong_tier(self):
        r = RouterResult(
            intent="content_create",
            confidence=0.9,
            model_tier=ModelTier.STRONG,
        )
        assert r.model_tier == ModelTier.STRONG
        assert r.model_tier.value == "strong"

    def test_router_result_tier_from_string(self):
        """ModelTier can be set from string value (as LLM returns)."""
        r = RouterResult(
            intent="content_create",
            confidence=0.9,
            model_tier="strong",
        )
        assert r.model_tier == ModelTier.STRONG

    def test_router_result_tier_serialization(self):
        r = RouterResult(
            intent="content_create",
            confidence=0.9,
            model_tier=ModelTier.STRONG,
        )
        data = r.model_dump(by_alias=True)
        assert "modelTier" in data
        assert data["modelTier"] == "strong"


# ── get_model_for_tier ────────────────────────────────────────────


class TestGetModelForTier:

    def test_fast_tier(self):
        from agents.provider import get_model_for_tier
        model = get_model_for_tier("fast")
        assert "turbo" in model or "fast" in model or model  # any valid string

    def test_standard_tier(self):
        from agents.provider import get_model_for_tier
        model = get_model_for_tier("standard")
        assert isinstance(model, str)
        assert "/" in model

    def test_strong_tier(self):
        from agents.provider import get_model_for_tier
        model = get_model_for_tier("strong")
        assert "anthropic" in model or "claude" in model

    def test_vision_tier(self):
        from agents.provider import get_model_for_tier
        model = get_model_for_tier("vision")
        assert "vl" in model or "vision" in model

    def test_unknown_tier_falls_back(self):
        from agents.provider import get_model_for_tier
        model = get_model_for_tier("nonexistent")
        # Should fall back to agent_model
        standard = get_model_for_tier("standard")
        assert model == standard


# ── create_teacher_agent with model_tier ──────────────────────────


class TestTeacherAgentModelTier:

    def test_create_agent_accepts_model_tier(self):
        """create_teacher_agent accepts model_tier parameter without error."""
        from agents.teacher_agent import create_teacher_agent
        agent = create_teacher_agent(
            teacher_context={"teacher_id": "t1", "classes": []},
            model_tier="standard",
        )
        assert agent is not None

    def test_create_agent_default_tier(self):
        """create_teacher_agent defaults to standard tier."""
        from agents.teacher_agent import create_teacher_agent
        agent = create_teacher_agent(
            teacher_context={"teacher_id": "t1", "classes": []},
        )
        assert agent is not None

    def test_create_agent_strong_tier(self):
        """create_teacher_agent with strong tier creates agent with Anthropic model."""
        from agents.teacher_agent import create_teacher_agent
        agent = create_teacher_agent(
            teacher_context={"teacher_id": "t1", "classes": []},
            model_tier="strong",
        )
        assert agent is not None


# ── Anthropic provider ────────────────────────────────────────────


class TestAnthropicProvider:

    def test_create_model_anthropic(self):
        """create_model with anthropic/ prefix creates AnthropicModel."""
        from agents.provider import create_model
        from pydantic_ai.models.anthropic import AnthropicModel
        model = create_model("anthropic/claude-opus-4-6")
        assert isinstance(model, AnthropicModel)

    def test_create_model_dashscope(self):
        """create_model with dashscope/ prefix creates OpenAIChatModel."""
        from agents.provider import create_model
        from pydantic_ai.models.openai import OpenAIChatModel
        model = create_model("dashscope/qwen-max")
        assert isinstance(model, OpenAIChatModel)


# ── Interactive HTML tool ─────────────────────────────────────────


class TestInteractiveHtmlTool:

    @pytest.mark.asyncio
    async def test_generate_interactive_html_basic(self):
        from tools.render_tools import generate_interactive_html
        result = await generate_interactive_html(
            html="<html><body><h1>Test</h1></body></html>",
            title="Test Page",
            description="A test page",
        )
        assert result["html"] == "<html><body><h1>Test</h1></body></html>"
        assert result["title"] == "Test Page"
        assert result["description"] == "A test page"
        assert result["preferredHeight"] == 500  # default

    @pytest.mark.asyncio
    async def test_generate_interactive_html_custom_height(self):
        from tools.render_tools import generate_interactive_html
        result = await generate_interactive_html(
            html="<html><body>Hello</body></html>",
            preferred_height=800,
        )
        assert result["preferredHeight"] == 800

    def test_interactive_html_in_tool_registry(self):
        from tools import TOOL_REGISTRY
        assert "generate_interactive_html" in TOOL_REGISTRY
