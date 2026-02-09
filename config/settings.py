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
    router_model: str = "dashscope/qwen-turbo-latest"  # Fast router (~200ms)
    vision_model: str = "dashscope/qwen-vl-max"  # Vision-capable model for multimodal
    agent_model: str = "dashscope/qwen-max"  # Agent Path: general content generation
    strong_model: str = "dashscope/qwen3-coder-plus"  # Strong tier: complex tasks (interactive, quiz)
    code_model: str = "dashscope/qwen3-coder-plus"  # Code tier: HTML/CSS/JS generation (interactive pages)
    # Fallback chain: if primary model fails, try these in order
    strong_model_fallback: str = "dashscope/qwen-max"
    agent_model_fallback: str = "dashscope/qwen-max"
    code_model_fallback: str = "dashscope/qwen-max"
    agent_max_iterations: int = 15  # Agent Path: max tool-use loop rounds
    max_tokens: int = 4096
    agent_max_tokens: int = 16384  # Agent Path: higher token budget for content generation (PPT, docs)
    # Agent convergence flags (default off for safe rollout)
    agent_unified_enabled: bool = False
    agent_unified_quiz_enabled: bool = False
    agent_unified_content_enabled: bool = False
    # Use LLM planner to decide required content tools (language-agnostic).
    agent_unified_content_tool_planner_enabled: bool = True
    agent_unified_build_enabled: bool = False
    # Unified quiz grace window before fallback (milliseconds)
    agent_unified_quiz_grace_ms: int = 4000
    # Optional model override for unified quiz tool-calling (e.g. zai/glm-4.7)
    agent_unified_quiz_model: str = ""
    # Unified quiz defaults to deterministic direct tool execution for latency/stability
    agent_unified_quiz_force_tool: bool = True

    # ── PPT Generation ────────────────────────────────────────
    pptx_max_slides: int = 30  # Hard upper limit for any generated PPT

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

    # ── Java Backend ──────────────────────────────────────────
    spring_boot_base_url: str = "https://api.insightai.hk"
    spring_boot_api_prefix: str = "/api"
    spring_boot_access_token: str = ""
    spring_boot_refresh_token: str = ""
    spring_boot_timeout: int = 15  # seconds
    use_mock_data: bool = False  # fallback to mock when True or backend unavailable

    # Service account for auto-login (preferred over static tokens)
    spring_boot_dify_account: str = ""
    spring_boot_dify_password: str = ""
    spring_boot_dify_role: str = "DIFY"
    spring_boot_dify_school_id: int = 1

    # ── Knowledge Base (RAG) ─────────────────────────────────
    pg_uri: str = "postgresql://insight:insight_dev_pass@localhost:5433/insight_agent"
    internal_api_secret: str = ""
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024

    # ── Conversation Memory ──────────────────────────────────
    conversation_store_type: str = "memory"  # "memory" or "redis"
    conversation_ttl: int = 1800  # seconds (30 min)
    redis_url: str = ""  # e.g. redis://:password@host:6379/0

    # ── AI Native Runtime ─────────────────────────────────────
    native_agent_enabled: bool = True  # False = emergency fallback to legacy

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
