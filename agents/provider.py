"""Agent provider — shared utilities for PydanticAI agents.

Creates LLM model instances and bridges FastMCP tools for in-process execution.
Includes fallback/degradation strategy for provider resilience.
"""

from __future__ import annotations

import inspect
import json
import logging
import uuid
from typing import Any

import httpx
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.alibaba import AlibabaProvider
from pydantic_ai.providers.openai import OpenAIProvider

from config.settings import get_settings
from tools import TOOL_REGISTRY, get_tool_descriptions

logger = logging.getLogger(__name__)


# ── DashScope response patching ──────────────────────────────
# Some models on DashScope (e.g. Kimi-k2.5) return tool_calls with
# id=null, which fails OpenAI client validation.  This transport
# patches null IDs with synthetic values before the client sees them.

class _PatchDashScopeTransport(httpx.AsyncBaseTransport):
    """Wrap an httpx transport to fix DashScope model response quirks.

    Fixes applied:
    1. Null tool_call.id — some models (Kimi) return id=null; we generate synthetic IDs.
    2. Split tool_calls — Kimi sends name and args as separate entries with the same
       index; we merge them into a single tool_call.
    """

    def __init__(self, wrapped: httpx.AsyncBaseTransport):
        self._wrapped = wrapped

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._wrapped.handle_async_request(request)
        await response.aread()
        body = response.content
        if b'"tool_calls"' in body:
            try:
                data = json.loads(body)
                if self._patch_tool_calls(data):
                    patched_body = json.dumps(data).encode("utf-8")
                    # Drop Content-Encoding (patched body is raw JSON, not gzip)
                    headers = {k: v for k, v in response.headers.items()
                               if k.lower() != "content-encoding"}
                    headers["content-length"] = str(len(patched_body))
                    return httpx.Response(
                        status_code=response.status_code,
                        headers=headers,
                        content=patched_body,
                        request=request,
                    )
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        return response

    @staticmethod
    def _patch_tool_calls(data: dict) -> bool:
        """Merge split tool_calls + fix null IDs. Returns True if anything changed."""
        patched = False
        for choice in data.get("choices", []):
            msg = choice.get("message") or {}
            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                continue

            # Phase 1: merge split entries by index
            # Kimi sends: [{name:"foo", args:""}, {name:"", args:"{...}"}]
            # both with the same index — merge into one.
            by_index: dict[int, dict] = {}
            for tc in tool_calls:
                idx = tc.get("index", 0)
                if idx not in by_index:
                    by_index[idx] = tc
                else:
                    existing = by_index[idx]
                    # Merge function fields
                    efn = existing.get("function") or {}
                    nfn = tc.get("function") or {}
                    if not efn.get("name") and nfn.get("name"):
                        efn["name"] = nfn["name"]
                    if not efn.get("arguments") and nfn.get("arguments"):
                        efn["arguments"] = nfn["arguments"]
                    existing["function"] = efn
                    # Take non-null id
                    if existing.get("id") is None and tc.get("id") is not None:
                        existing["id"] = tc["id"]
                    patched = True

            if len(by_index) != len(tool_calls):
                msg["tool_calls"] = list(by_index.values())

            # Phase 2: fix null IDs
            for tc in msg.get("tool_calls") or []:
                if tc.get("id") is None:
                    tc["id"] = f"call_{uuid.uuid4().hex[:24]}"
                    patched = True

        return patched


def _create_dashscope_http_client() -> httpx.AsyncClient:
    """Create an httpx client with DashScope response patching."""
    transport = _PatchDashScopeTransport(httpx.AsyncHTTPTransport())
    return httpx.AsyncClient(transport=transport)

# Provider prefix → (base_url, settings_key_attr)
_PROVIDER_MAP: dict[str, tuple[str, str]] = {
    "dashscope": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "dashscope_api_key"),
    "zai": ("https://open.bigmodel.cn/api/paas/v4/", "zai_api_key"),
    "zai-intl": ("https://api.z.ai/api/paas/v4/", "zai_intl_api_key"),
}


def create_model(model_name: str | None = None):
    """Build a PydanticAI model instance.

    Parses the ``"provider/model"`` format (e.g. ``"dashscope/qwen3-max"``,
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

        # ── DashScope (Alibaba) — use dedicated AlibabaProvider ──
        # AlibabaProvider applies qwen_model_profile() which sets:
        # - InlineDefsJsonSchemaTransformer (correct tool schema format for Qwen)
        # - ignore_streamed_leading_whitespace=True (prevents <think> tags
        #   from being treated as final text output, which would abort tool calls)
        if prefix == "dashscope":
            base_url, key_attr = _PROVIDER_MAP[prefix]
            api_key = getattr(settings, key_attr, "")
            http_client = _create_dashscope_http_client()
            provider = AlibabaProvider(api_key=api_key, base_url=base_url, http_client=http_client)
            return OpenAIChatModel(model_id, provider=provider)

        # ── Google Gemini — use native GoogleProvider ──
        if prefix == "gemini":
            from pydantic_ai.models.google import GoogleModel
            from pydantic_ai.providers.google import GoogleProvider

            provider = GoogleProvider(api_key=settings.gemini_api_key)
            return GoogleModel(model_id, provider=provider)

        # ── Other OpenAI-compatible providers ──
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
    - fast     → router_model   (qwen-flash)
    - standard → agent_model    (qwen3-max)
    - strong   → strong_model   (qwen3-max)
    - code     → code_model     (qwen3-coder-plus)
    - vision   → vision_model   (qwen3-vl-plus)

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
    """Get the names of all registered FastMCP tools.

    .. deprecated:: Step 4
        Use ``tools.registry.get_tool_names()`` directly.
    """
    return list(TOOL_REGISTRY.keys())


def get_mcp_tool_descriptions() -> list[dict[str, str]]:
    """Get name + description for every registered tool.

    .. deprecated:: Step 4
        Use ``tools.registry.get_tool_descriptions()`` directly.
    """
    return get_tool_descriptions()


async def execute_mcp_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Execute a registered tool by name.

    .. deprecated:: Step 4
        Still used by ``agents/executor.py``.  Will be removed when
        that legacy module is migrated to the native tool-calling path.

    Looks up the function in :data:`tools.TOOL_REGISTRY` and calls it
    directly.  Native-registered tools expect ``RunContext[AgentDeps]``
    as their first parameter; this bridge synthesises a minimal context
    from the provided *arguments* dict so legacy callers still work.
    """
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        raise ValueError(f"Tool '{name}' not found in registry")

    # Detect native tools whose first parameter is RunContext[AgentDeps].
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    first_annotation = params[0].annotation if params else None
    needs_ctx = (
        first_annotation is not inspect.Parameter.empty
        and "RunContext" in str(first_annotation)
    )

    if needs_ctx:
        # Synthesise a minimal RunContext so the native wrapper can
        # extract deps.teacher_id etc. without the PydanticAI runtime.
        from pydantic_ai import RunContext
        from pydantic_ai.usage import RunUsage
        from agents.native_agent import AgentDeps

        teacher_id = str(arguments.pop("teacher_id", "") or "")
        ctx = RunContext(
            deps=AgentDeps(
                teacher_id=teacher_id,
                conversation_id="legacy-executor",
            ),
            model=create_model(),
            usage=RunUsage(),
        )
        # Remaining arguments (e.g. class_id) are passed as kwargs.
        if inspect.iscoroutinefunction(fn):
            return await fn(ctx, **arguments)
        return fn(ctx, **arguments)

    if inspect.iscoroutinefunction(fn):
        return await fn(**arguments)
    return fn(**arguments)
