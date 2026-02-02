"""Model listing and skills listing endpoints."""

from fastapi import APIRouter

from agents.chat_agent import ChatAgent
from config.settings import get_settings

router = APIRouter()

_chat_agent = ChatAgent()


@router.get("/models")
async def list_models():
    """List supported model examples and the current default."""
    settings = get_settings()
    return {
        "default": settings.default_model,
        "examples": [
            "dashscope/qwen-max",
            "dashscope/qwen-plus",
            "dashscope/qwen-turbo",
            "zai/glm-4.7",
            "openai/gpt-4o",
            "anthropic/claude-sonnet-4-20250514",
        ],
    }


@router.get("/skills")
async def list_skills():
    """List all available skills/tools the agent can use."""
    skills = _chat_agent.list_skills()
    return {"skills": skills}
