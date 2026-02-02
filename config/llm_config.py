"""Reusable LLM generation parameters.

LLMConfig is a standalone Pydantic model that can be:
- embedded in Settings as the global default,
- declared per-agent for task-specific tuning,
- passed per-call for one-off overrides.

Priority chain (low → high):
    .env global defaults  →  Agent-level LLMConfig  →  per-call overrides
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """LLM generation parameters — reusable across agents.

    All fields are optional.  ``None`` means "use the model's default".
    """

    model: str | None = Field(default=None, description="LiteLLM model identifier")
    max_tokens: int | None = Field(default=None, description="Max tokens to generate")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k: int | None = Field(
        default=None, ge=0, description="Qwen/Dashscope supported; ignored by OpenAI"
    )
    seed: int | None = Field(default=None, description="Random seed for reproducibility")
    frequency_penalty: float | None = Field(
        default=None, ge=-2.0, le=2.0, description="OpenAI-style frequency penalty"
    )
    repetition_penalty: float | None = Field(
        default=None, description="Qwen/Dashscope repetition penalty"
    )
    response_format: str | None = Field(
        default=None, description="'json_object' for structured output"
    )
    stop: list[str] | None = Field(default=None, description="Stop sequences")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def merge(self, overrides: LLMConfig) -> LLMConfig:
        """Return a new LLMConfig: *self* as base, *overrides* wins on non-None fields."""
        base = self.model_dump(exclude_none=True)
        over = overrides.model_dump(exclude_none=True)
        base.update(over)
        return LLMConfig(**base)

    def to_litellm_kwargs(self) -> dict:
        """Convert to ``litellm.completion()``-compatible keyword arguments."""
        kw: dict = {}
        for field in (
            "max_tokens",
            "temperature",
            "top_p",
            "top_k",
            "seed",
            "frequency_penalty",
            "repetition_penalty",
            "stop",
        ):
            val = getattr(self, field)
            if val is not None:
                kw[field] = val
        if self.response_format:
            kw["response_format"] = {"type": self.response_format}
        return kw
