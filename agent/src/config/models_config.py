"""
Models Configuration
Multi-provider model catalog. Fetches from OpenRouter (if key present)
and includes static Alibaba Cloud Model Studio models.
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# Cache for merged models (all providers)
_cached_models: Optional[Dict[str, Dict[str, Any]]] = None
_fetch_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Static Alibaba Cloud Model Studio catalog
# These use OpenAI-compatible API via DashScope international endpoint.
# ---------------------------------------------------------------------------
_ALIBABA_STATIC_MODELS: List[Dict[str, Any]] = [
    # Qwen flagship
    {"id": "alibaba/qwen-max", "name": "Qwen Max", "context_length": 32768},
    {"id": "alibaba/qwen-max-latest", "name": "Qwen Max Latest", "context_length": 32768},
    {"id": "alibaba/qwen-plus", "name": "Qwen Plus", "context_length": 131072},
    {"id": "alibaba/qwen-plus-latest", "name": "Qwen Plus Latest", "context_length": 131072},
    {"id": "alibaba/qwen-turbo", "name": "Qwen Turbo", "context_length": 131072},
    {"id": "alibaba/qwen-turbo-latest", "name": "Qwen Turbo Latest", "context_length": 131072},
    {"id": "alibaba/qwen-long", "name": "Qwen Long", "context_length": 1000000},
    # Qwen 2.5 open-weight
    {"id": "alibaba/qwen2.5-72b-instruct", "name": "Qwen 2.5 72B Instruct", "context_length": 131072},
    {"id": "alibaba/qwen2.5-32b-instruct", "name": "Qwen 2.5 32B Instruct", "context_length": 131072},
    {"id": "alibaba/qwen2.5-14b-instruct", "name": "Qwen 2.5 14B Instruct", "context_length": 131072},
    {"id": "alibaba/qwen2.5-7b-instruct", "name": "Qwen 2.5 7B Instruct", "context_length": 131072},
    {"id": "alibaba/qwen2.5-3b-instruct", "name": "Qwen 2.5 3B Instruct", "context_length": 32768},
    # Reasoning
    {"id": "alibaba/qwq-32b", "name": "QwQ 32B (Reasoning)", "context_length": 131072},
    {"id": "alibaba/qwq-plus", "name": "QwQ Plus (Reasoning)", "context_length": 131072},
]


def _build_alibaba_catalog() -> Dict[str, Dict[str, Any]]:
    """Build Alibaba model entries (only if ALIBABA_API_KEY is set)."""
    if not os.getenv("ALIBABA_API_KEY", "").strip():
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for m in _ALIBABA_STATIC_MODELS:
        model_id = m["id"]
        result[model_id] = {
            "id": model_id,
            "provider": "alibaba",
            "name": m["name"],
            "context_window": m.get("context_length", 0),
            "supports_vision": False,
            "supports_tool_calling": True,
            "supports_reasoning": True,
            "description": "Alibaba Cloud Model Studio (Qwen)",
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {},
        }
    return result


async def _fetch_openrouter_models() -> Dict[str, Dict[str, Any]]:
    """Fetch from OpenRouter API. Returns empty dict if key missing."""
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        logger.info("OPENROUTER_API_KEY not set, skipping OpenRouter models")
        return {}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            response = await client.get(OPENROUTER_MODELS_URL, headers=headers)
            response.raise_for_status()
            data = response.json()

            models_dict: Dict[str, Dict[str, Any]] = {}
            models_list = data.get("data", [])

            for model in models_list:
                model_id = model.get("id", "")
                if not model_id:
                    continue

                capabilities = model.get("capabilities", {})

                supports_tool_calling = (
                    capabilities.get("tool_calling", False)
                    or capabilities.get("supports_tool_calling", False)
                    or "tools" in model.get("supported_parameters", [])
                )
                supports_reasoning = (
                    capabilities.get("reasoning", False)
                    or capabilities.get("supports_reasoning", False)
                    or "include_reasoning" in model.get("supported_parameters", [])
                )

                if not (supports_tool_calling and supports_reasoning):
                    continue

                provider = model_id.split("/")[0] if "/" in model_id else "unknown"
                pricing = model.get("pricing", {})

                models_dict[model_id] = {
                    "id": model_id,
                    "provider": provider,
                    "name": model.get("name", model_id),
                    "context_window": model.get("context_length", 0),
                    "supports_vision": capabilities.get("vision", False),
                    "supports_tool_calling": True,
                    "supports_reasoning": True,
                    "description": f"{provider} model with tool calling and reasoning",
                    "pricing": {
                        "prompt": pricing.get("prompt", "0"),
                        "completion": pricing.get("completion", "0"),
                    },
                    "top_provider": model.get("top_provider", {}),
                }

            logger.info(f"Fetched {len(models_dict)} models from OpenRouter")
            return models_dict

    except Exception as e:
        logger.warning(f"OpenRouter fetch failed (non-fatal): {e}")
        return {}


async def fetch_all_models(
    force_refresh: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """
    Fetch and merge models from all configured providers.
    Gracefully skips providers whose API key is not set.
    """
    global _cached_models

    if _cached_models is not None and not force_refresh:
        return _cached_models

    async with _fetch_lock:
        if _cached_models is not None and not force_refresh:
            return _cached_models

        merged: Dict[str, Dict[str, Any]] = {}

        # 1. Static Alibaba catalog
        alibaba = _build_alibaba_catalog()
        merged.update(alibaba)

        # 2. OpenRouter dynamic catalog
        openrouter = await _fetch_openrouter_models()
        merged.update(openrouter)

        if not merged:
            raise ValueError(
                "No models available. Set at least one API key: "
                "ALIBABA_API_KEY or OPENROUTER_API_KEY"
            )

        _cached_models = merged
        logger.info(
            f"Total models available: {len(merged)} "
            f"(alibaba={len(alibaba)}, openrouter={len(openrouter)})"
        )
        return merged


# Backward-compat alias used by routes.py and other importers
fetch_openrouter_models = fetch_all_models


def get_model_config(model_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve configuration for a specific model."""
    if _cached_models is None:
        return None

    if model_id in _cached_models:
        return _cached_models[model_id]

    # Try stripping known routing prefixes
    for prefix in [
        "openrouter/",
        "alibaba/",
        "anthropic/",
        "openai/",
        "google/",
        "meta-llama/",
        "mistralai/",
    ]:
        if model_id.startswith(prefix):
            clean_id = model_id[len(prefix):]
            if clean_id in _cached_models:
                return _cached_models[clean_id]

    return None


def list_available_models() -> list[str]:
    """Get list of all available model IDs."""
    if _cached_models is None:
        return []
    return list(_cached_models.keys())


def get_models_by_provider(provider: str) -> list[Dict[str, Any]]:
    """Get all models from a specific provider."""
    if _cached_models is None:
        return []
    return [
        config
        for config in _cached_models.values()
        if config.get("provider") == provider
    ]


def get_recommended_models() -> Dict[str, Optional[Dict[str, Any]]]:
    """Get recommended models for different use cases."""
    if _cached_models is None:
        return {}

    return {
        "best_reasoning": (
            _cached_models.get("alibaba/qwq-plus")
            or _cached_models.get("alibaba/qwq-32b")
            or _cached_models.get("anthropic/claude-3.5-sonnet")
        ),
        "balanced": (
            _cached_models.get("alibaba/qwen-plus")
            or _cached_models.get("anthropic/claude-3-opus")
        ),
        "fast": (
            _cached_models.get("alibaba/qwen-turbo")
            or _cached_models.get("anthropic/claude-3-haiku")
        ),
        "vision": _cached_models.get("anthropic/claude-3.5-sonnet"),
    }
