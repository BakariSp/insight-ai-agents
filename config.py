import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration."""

    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    # Anthropic
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4096"))

    # MCP
    MCP_SERVER_NAME = os.getenv("MCP_SERVER_NAME", "insight-ai-agent")
