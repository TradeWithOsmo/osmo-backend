"""
LLM Factory
Multi-provider LLM routing. Supports Alibaba Cloud Model Studio and OpenRouter.
Provider is detected from the model_id prefix (e.g. alibaba/qwen-plus).
"""

import os
from typing import Any, Dict, Optional

from langchain_openai import ChatOpenAI

from ..config.models_config import get_model_config
from ..utils.prompts import build_system_prompt

# Provider routing table: prefix -> (base_url, api_key_env, extra_headers)
_PROVIDER_ROUTES: Dict[str, Dict[str, Any]] = {
    "alibaba": {
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "ALIBABA_API_KEY",
        "headers": {},
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "headers": {
            "HTTP-Referer": "https://tradewithosmo.com",
            "X-Title": "Osmo Trading Terminal",
        },
    },
}

# Bare model name prefixes that belong to Alibaba (no provider prefix in ID)
_ALIBABA_BARE_PREFIXES = ("qwen", "qwq", "qvq")


def _parse_model_id(model_id: str) -> tuple[str, str]:
    """
    Detect provider and return (provider, actual_model_id_for_api).

    Examples:
      alibaba/qwen-plus         -> ("alibaba", "qwen-plus")
      alibaba/qwen2.5-72b-inst  -> ("alibaba", "qwen2.5-72b-instruct")
      openrouter/anthropic/...  -> ("openrouter", "anthropic/...")
      anthropic/claude-3.5-...  -> ("openrouter", "anthropic/claude-3.5-...")
      qwen-plus                 -> ("alibaba", "qwen-plus")   # bare Alibaba model
    """
    raw = str(model_id or "").strip()

    for prefix in _PROVIDER_ROUTES:
        if raw.startswith(f"{prefix}/"):
            return prefix, raw[len(prefix) + 1:]

    # Bare Alibaba model names (qwen-*, qwq-*, qvq-*)
    first = raw.split("/")[0].lower()
    if any(first.startswith(p) for p in _ALIBABA_BARE_PREFIXES):
        return "alibaba", raw

    # Default: route through OpenRouter (handles anthropic/, openai/, google/, etc.)
    return "openrouter", raw


class LLMFactory:
    """Factory for creating LLM instances. Routes to the correct provider."""

    @staticmethod
    def get_llm(
        model_id: str,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
    ) -> Any:
        provider, actual_model = _parse_model_id(model_id)
        route = _PROVIDER_ROUTES.get(provider, _PROVIDER_ROUTES["openrouter"])

        api_key = os.getenv(route["api_key_env"], "").strip()
        if not api_key:
            raise ValueError(
                f"Missing required environment variable: {route['api_key_env']} "
                f"(needed for provider '{provider}', model '{actual_model}')"
            )

        print(f"[LLMFactory] {actual_model} via {provider} ({route['base_url']})")

        llm_args: Dict[str, Any] = {
            "model": actual_model,
            "api_key": api_key,
            "base_url": route["base_url"],
            "temperature": temperature,
        }

        if route["headers"]:
            llm_args["default_headers"] = dict(route["headers"])

        try:
            return ChatOpenAI(**llm_args)
        except TypeError:
            # Backward compatibility for older langchain_openai versions
            if "api_key" in llm_args:
                llm_args["openai_api_key"] = llm_args.pop("api_key")
            if "base_url" in llm_args:
                llm_args["openai_api_base"] = llm_args.pop("base_url")
            return ChatOpenAI(**llm_args)

    @staticmethod
    def get_system_prompt(
        model_id: str,
        reasoning_effort: str | None = None,
        tool_states: Dict[str, Any] | None = None,
    ) -> str:
        get_model_config(model_id)  # kept for compat
        return build_system_prompt(
            reasoning_effort=reasoning_effort,
            tool_states=tool_states,
        )
