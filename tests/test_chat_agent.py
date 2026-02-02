"""Tests for ChatAgent — smalltalk and QA response generation."""

import pytest
from pydantic_ai.models.test import TestModel

from agents.chat import _chat_agent, generate_response


@pytest.mark.asyncio
async def test_chat_smalltalk_response():
    """ChatAgent returns a text response for smalltalk."""
    test_model = TestModel(custom_output_text="你好！有什么可以帮你的吗？")

    result = await _chat_agent.run("你好", model=test_model)
    response = str(result.output)
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.asyncio
async def test_chat_qa_response():
    """ChatAgent returns a text response for QA."""
    test_model = TestModel(
        custom_output_text="KPI 是关键绩效指标的缩写。"
    )

    result = await _chat_agent.run(
        "[Language: zh-CN]\n[Intent: chat_qa]\n\nKPI 是什么意思",
        model=test_model,
    )
    response = str(result.output)
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.asyncio
async def test_chat_does_not_return_json():
    """ChatAgent should return plain text, not JSON structures."""
    test_model = TestModel(
        custom_output_text="I can help you with data analysis!"
    )

    result = await _chat_agent.run("Hello", model=test_model)
    response = str(result.output)
    assert not response.startswith("{")
    assert not response.startswith("[")
