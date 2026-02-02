"""Pydantic Settings — typed configuration with .env auto-loading."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from config.llm_config import LLMConfig


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

    # ── LLM Generation Defaults (all optional, None = model default) ──
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    seed: int | None = None
    frequency_penalty: float | None = None
    repetition_penalty: float | None = None
    response_format: str | None = None
    stop: list[str] | None = None

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

    # ── Helpers ───────────────────────────────────────────────

    def get_default_llm_config(self) -> LLMConfig:
        """Build an :class:`LLMConfig` from global .env defaults."""
        return LLMConfig(
            model=self.default_model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            top_k=self.top_k,
            seed=self.seed,
            frequency_penalty=self.frequency_penalty,
            repetition_penalty=self.repetition_penalty,
            response_format=self.response_format,
            stop=self.stop,
        )


@lru_cache
def get_settings() -> Settings:
    """Singleton accessor for application settings."""
    return Settings()
