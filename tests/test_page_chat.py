"""Tests for PageChatAgent — follow-up question answering with page context."""

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from agents.page_chat import _summarize_page_context, generate_response
from config.prompts.page_chat import build_page_chat_prompt
from models.blueprint import Blueprint
from tests.test_planner import _sample_blueprint_args


# ── Page context summarization tests ──────────────────────────


def test_summarize_empty_context():
    assert _summarize_page_context(None) == "No page data available."
    assert _summarize_page_context({}) == "No page data available."


def test_summarize_dict_values():
    ctx = {
        "stats": {"mean": 74.2, "median": 72.0},
        "title": "Test Analysis",
    }
    result = _summarize_page_context(ctx)
    assert "stats" in result
    assert "mean" in result
    assert "title" in result
    assert "Test Analysis" in result


def test_summarize_list_values():
    ctx = {"students": [{"name": "A"}, {"name": "B"}]}
    result = _summarize_page_context(ctx)
    assert "students" in result
    assert "2 items" in result


# ── Prompt building tests ─────────────────────────────────────


def test_build_page_chat_prompt_injects_context():
    prompt = build_page_chat_prompt(
        blueprint_name="Test Analysis",
        blueprint_description="Analyze test scores",
        page_summary="Mean: 74.2, Median: 72.0",
    )
    assert "Test Analysis" in prompt
    assert "Analyze test scores" in prompt
    assert "Mean: 74.2" in prompt


def test_build_page_chat_prompt_defaults():
    prompt = build_page_chat_prompt()
    assert "Unknown" in prompt
    assert "No description" in prompt


# ── Agent-level tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_page_chat_agent_response():
    """PageChatAgent returns a text response with page context."""
    bp = Blueprint(**_sample_blueprint_args())

    test_model = TestModel(
        custom_output_text="Based on the data, Wong Ka Ho scored 58 on Unit 5 Test."
    )

    agent = Agent(
        model=test_model,
        system_prompt=build_page_chat_prompt(
            blueprint_name=bp.name,
            blueprint_description=bp.description,
            page_summary="Mean: 74.2, lowest: Wong Ka Ho (58)",
        ),
        retries=1,
        defer_model_check=True,
    )

    result = await agent.run("哪些学生需要关注？")
    response = str(result.output)
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.asyncio
async def test_page_chat_agent_no_json():
    """PageChatAgent should return plain text, not JSON."""
    bp = Blueprint(**_sample_blueprint_args())

    test_model = TestModel(
        custom_output_text="The average score is 74.2."
    )

    agent = Agent(
        model=test_model,
        system_prompt=build_page_chat_prompt(
            blueprint_name=bp.name,
            blueprint_description=bp.description,
        ),
        retries=1,
        defer_model_check=True,
    )

    result = await agent.run("What is the average?")
    response = str(result.output)
    assert not response.startswith("{")
