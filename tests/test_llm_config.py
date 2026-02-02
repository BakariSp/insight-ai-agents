"""Tests for config.llm_config — LLMConfig model, merge, and serialization."""

import pytest

from config.llm_config import LLMConfig


# ── Construction & defaults ───────────────────────────────────


def test_default_all_none():
    cfg = LLMConfig()
    assert cfg.model is None
    assert cfg.temperature is None
    assert cfg.top_p is None
    assert cfg.response_format is None


def test_explicit_values():
    cfg = LLMConfig(temperature=0.5, top_p=0.9, seed=42)
    assert cfg.temperature == 0.5
    assert cfg.top_p == 0.9
    assert cfg.seed == 42


def test_validation_temperature_range():
    with pytest.raises(ValueError):
        LLMConfig(temperature=3.0)  # max 2.0


def test_validation_top_p_range():
    with pytest.raises(ValueError):
        LLMConfig(top_p=-0.1)


# ── merge ─────────────────────────────────────────────────────


def test_merge_override_non_none():
    base = LLMConfig(model="dashscope/qwen-max", temperature=0.7, max_tokens=4096)
    override = LLMConfig(temperature=0.2)
    merged = base.merge(override)

    assert merged.model == "dashscope/qwen-max"       # kept from base
    assert merged.temperature == 0.2                    # overridden
    assert merged.max_tokens == 4096                    # kept from base
    assert merged.top_p is None                         # neither set


def test_merge_does_not_mutate():
    base = LLMConfig(temperature=0.7)
    override = LLMConfig(temperature=0.2)
    merged = base.merge(override)

    assert base.temperature == 0.7       # unchanged
    assert override.temperature == 0.2   # unchanged
    assert merged.temperature == 0.2


def test_merge_full_override():
    base = LLMConfig(model="a", temperature=0.5, seed=1)
    override = LLMConfig(model="b", temperature=0.9, seed=2, top_p=0.8)
    merged = base.merge(override)

    assert merged.model == "b"
    assert merged.temperature == 0.9
    assert merged.seed == 2
    assert merged.top_p == 0.8


def test_merge_empty_override():
    base = LLMConfig(model="a", temperature=0.5)
    merged = base.merge(LLMConfig())

    assert merged.model == "a"
    assert merged.temperature == 0.5


# ── to_litellm_kwargs ────────────────────────────────────────


def test_to_litellm_kwargs_basic():
    cfg = LLMConfig(
        model="dashscope/qwen-max",
        max_tokens=2048,
        temperature=0.3,
        top_p=0.9,
    )
    kw = cfg.to_litellm_kwargs()

    assert kw["max_tokens"] == 2048
    assert kw["temperature"] == 0.3
    assert kw["top_p"] == 0.9
    # model is NOT included — it's passed separately by LLMService
    assert "model" not in kw


def test_to_litellm_kwargs_excludes_none():
    cfg = LLMConfig(temperature=0.5)
    kw = cfg.to_litellm_kwargs()

    assert kw == {"temperature": 0.5}


def test_to_litellm_kwargs_response_format():
    cfg = LLMConfig(response_format="json_object")
    kw = cfg.to_litellm_kwargs()

    assert kw["response_format"] == {"type": "json_object"}


def test_to_litellm_kwargs_all_fields():
    cfg = LLMConfig(
        max_tokens=1024,
        temperature=0.2,
        top_p=0.8,
        top_k=40,
        seed=123,
        frequency_penalty=0.5,
        repetition_penalty=1.1,
        stop=["<|end|>"],
        response_format="json_object",
    )
    kw = cfg.to_litellm_kwargs()

    assert kw["max_tokens"] == 1024
    assert kw["temperature"] == 0.2
    assert kw["top_p"] == 0.8
    assert kw["top_k"] == 40
    assert kw["seed"] == 123
    assert kw["frequency_penalty"] == 0.5
    assert kw["repetition_penalty"] == 1.1
    assert kw["stop"] == ["<|end|>"]
    assert kw["response_format"] == {"type": "json_object"}


def test_to_litellm_kwargs_empty():
    cfg = LLMConfig()
    kw = cfg.to_litellm_kwargs()
    assert kw == {}


# ── Settings integration ──────────────────────────────────────


def test_settings_get_default_llm_config():
    from config.settings import Settings

    s = Settings(
        default_model="dashscope/qwen-max",
        max_tokens=2048,
        temperature=0.6,
        top_p=0.9,
    )
    cfg = s.get_default_llm_config()

    assert isinstance(cfg, LLMConfig)
    assert cfg.model == "dashscope/qwen-max"
    assert cfg.max_tokens == 2048
    assert cfg.temperature == 0.6
    assert cfg.top_p == 0.9
    assert cfg.seed is None  # not set


def test_settings_default_llm_config_no_overrides():
    from config.settings import Settings

    s = Settings()
    cfg = s.get_default_llm_config()

    assert cfg.model == "dashscope/qwen-max"
    assert cfg.max_tokens == 4096
    assert cfg.temperature is None
