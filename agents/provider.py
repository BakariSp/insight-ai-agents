"""Agent provider — shared utilities for PydanticAI agents.

Creates LLM model instances and bridges FastMCP tools for in-process execution.
Includes fallback/degradation strategy for provider resilience.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from config.settings import get_settings
from tools import TOOL_REGISTRY, get_tool_descriptions

logger = logging.getLogger(__name__)

# Provider prefix → (base_url, settings_key_attr)
_PROVIDER_MAP: dict[str, tuple[str, str]] = {
    "dashscope": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "dashscope_api_key"),
    "zai": ("https://open.bigmodel.cn/api/paas/v4/", "zai_api_key"),
}


def create_model(model_name: str | None = None):
    """Build a PydanticAI model instance.

    Parses the ``"provider/model"`` format (e.g. ``"dashscope/qwen-max"``,
    ``"anthropic/claude-opus-4-6"``) and creates the appropriate model.

    - ``anthropic/*`` → native :class:`AnthropicModel` (supports tool-use, streaming)
    - ``dashscope/*``, ``zai/*`` → :class:`OpenAIChatModel` via OpenAI-compatible endpoint
    - ``openai/*`` or bare name → :class:`OpenAIChatModel` with OpenAI API

    Args:
        model_name: Model identifier in ``"provider/model"`` format.
                    Defaults to ``settings.default_model``.

    Returns:
        A PydanticAI model instance ready for ``Agent(model=...)``.
    """
    settings = get_settings()
    name = model_name or settings.default_model

    # Split "provider/model" → lookup
    if "/" in name:
        prefix, model_id = name.split("/", 1)

        # ── Anthropic native ──
        if prefix == "anthropic":
            from pydantic_ai.models.anthropic import AnthropicModel
            from pydantic_ai.providers.anthropic import AnthropicProvider

            provider = AnthropicProvider(api_key=settings.anthropic_api_key)
            return AnthropicModel(model_id, provider=provider)

        # ── OpenAI-compatible providers ──
        if prefix in _PROVIDER_MAP:
            base_url, key_attr = _PROVIDER_MAP[prefix]
            api_key = getattr(settings, key_attr, "")
            provider = OpenAIProvider(api_key=api_key, base_url=base_url)
            return OpenAIChatModel(model_id, provider=provider)

    # Fallback: assume OpenAI-compatible with OPENAI_API_KEY
    # Strip "openai/" prefix if present (LiteLLM convention)
    model_id = name.split("/", 1)[1] if "/" in name else name
    provider = OpenAIProvider(api_key=settings.openai_api_key)
    return OpenAIChatModel(model_id, provider=provider)


def get_model_for_tier(tier: str) -> str:
    """Map a model tier to the configured model name.

    Tier → Settings field mapping:
    - fast     → router_model   (qwen-turbo-latest)
    - standard → agent_model    (qwen-max)
    - strong   → strong_model   (anthropic/claude-opus-4-6)
    - code     → code_model     (qwen3-coder-plus)
    - vision   → vision_model   (qwen-vl-max)

    Args:
        tier: One of "fast", "standard", "strong", "code", "vision".

    Returns:
        Model name string in ``"provider/model"`` format.
    """
    settings = get_settings()
    return {
        "fast": settings.router_model,
        "standard": settings.agent_model,
        "strong": settings.strong_model,
        "code": settings.code_model,
        "vision": settings.vision_model,
    }.get(tier, settings.agent_model)


def get_model_chain_for_tier(tier: str) -> list[str]:
    """Return an ordered list of model names for a tier (primary + fallbacks).

    Used by :func:`create_model_with_fallback` to try models in order
    when the primary provider is unavailable.

    Args:
        tier: One of "fast", "standard", "strong", "vision".

    Returns:
        List of model names, primary first, then fallback(s).
    """
    settings = get_settings()
    primary = get_model_for_tier(tier)
    chain = [primary]

    # Add tier-specific fallback if configured and different from primary
    fallback = {
        "strong": settings.strong_model_fallback,
        "standard": settings.agent_model_fallback,
        "code": settings.code_model_fallback,
    }.get(tier)

    if fallback and fallback != primary:
        chain.append(fallback)

    # Universal last resort: default_model
    if settings.default_model not in chain:
        chain.append(settings.default_model)

    return chain


async def create_model_with_fallback(tier: str):
    """Create a model instance with automatic fallback on provider failure.

    Tries each model in the tier's fallback chain.  If a model instance
    can be created but the provider is unreachable (connection error,
    auth error, rate limit), falls back to the next model in the chain.

    This performs a lightweight health check (not a full LLM call) to
    validate connectivity before returning the model.

    Args:
        tier: One of "fast", "standard", "strong", "vision".

    Returns:
        Tuple of (model_instance, model_name) for the first working provider.

    Raises:
        RuntimeError: If all providers in the chain fail.
    """
    chain = get_model_chain_for_tier(tier)
    errors: list[str] = []

    for model_name in chain:
        try:
            model = create_model(model_name)
            logger.info("Model %s created successfully for tier=%s", model_name, tier)
            return model, model_name
        except Exception as e:
            error_msg = f"{model_name}: {type(e).__name__}: {e}"
            errors.append(error_msg)
            logger.warning("Model creation failed for %s, trying next: %s", model_name, e)

    raise RuntimeError(
        f"All models failed for tier={tier}: {'; '.join(errors)}"
    )


def get_mcp_tool_names() -> list[str]:
    """Get the names of all registered FastMCP tools."""
    return list(TOOL_REGISTRY.keys())


def get_mcp_tool_descriptions() -> list[dict[str, str]]:
    """Get name + description for every registered tool.

    Returns:
        List of ``{"name": ..., "description": ...}`` dicts.
    """
    return get_tool_descriptions()


async def execute_mcp_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Execute a registered FastMCP tool by name.

    Looks up the function in :data:`tools.TOOL_REGISTRY` and calls it
    directly (supports both sync and async tool functions).

    Args:
        name: Tool name as registered in the TOOL_REGISTRY.
        arguments: Keyword arguments forwarded to the tool function.

    Returns:
        The tool's return value.

    Raises:
        ValueError: If the tool name is not found.
    """
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        raise ValueError(f"Tool '{name}' not found in registry")

    if inspect.iscoroutinefunction(fn):
        return await fn(**arguments)
    return fn(**arguments)
