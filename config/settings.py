"""Pydantic Settings — typed configuration with .env auto-loading."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment / .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Service ──────────────────────────────────────────────
    service_port: int = 5000
    cors_origins: list[str] = ["*"]
    debug: bool = False

    # ── LLM ──────────────────────────────────────────────────
    default_model: str = "dashscope/qwen-max"
    executor_model: str = "dashscope/qwen-max"
    max_tokens: int = 4096

    # Provider API keys (read by LiteLLM automatically via env)
    dashscope_api_key: str = ""
    zai_api_key: str = ""
    zai_api_base: str = "https://open.bigmodel.cn/api/paas/v4/"
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # ── Skills / Tools ───────────────────────────────────────
    brave_api_key: str = ""
    memory_dir: str = "data"

    # ── MCP ──────────────────────────────────────────────────
    mcp_server_name: str = "insight-ai-agent"


@lru_cache
def get_settings() -> Settings:
    """Singleton accessor for application settings."""
    return Settings()
