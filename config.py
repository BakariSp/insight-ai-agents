import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration."""

    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    # LLM - model name includes provider prefix, e.g.:
    #   anthropic/claude-sonnet-4-20250514
    #   openai/gpt-4o
    #   dashscope/qwen-max
    #   zai/glm-4
    LLM_MODEL = os.getenv("LLM_MODEL", "dashscope/qwen-max")
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4096"))

    # MCP
    MCP_SERVER_NAME = os.getenv("MCP_SERVER_NAME", "insight-ai-agent")
