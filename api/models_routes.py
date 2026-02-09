"""Model listing and skills listing endpoints."""

from fastapi import APIRouter

from config.settings import get_settings
from tools.registry import get_tool_descriptions

router = APIRouter()


@router.get("/models")
async def list_models():
    """List supported model examples and the current default."""
    settings = get_settings()
    return {
        "default": settings.default_model,
        "examples": [
            "dashscope/qwen3-max",
            "dashscope/qwen3-plus",
            "dashscope/qwen3-coder-plus",
            "zai/glm-4.7",
            "openai/gpt-4o",
            "anthropic/claude-sonnet-4-20250514",
        ],
    }


@router.get("/skills")
async def list_skills():
    """List all available skills/tools the agent can use."""
    return {"skills": get_tool_descriptions()}
