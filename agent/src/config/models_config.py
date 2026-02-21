"""
Models Configuration
Centralized configuration for LLM models via OpenRouter.
Fetches models dynamically from OpenRouter API with mandatory filtering.
NO FALLBACK - API key is required.
"""

import asyncio
import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# OpenRouter API endpoint
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# Cache for fetched models
_cached_models: Optional[Dict[str, Dict[str, Any]]] = None
_fetch_lock = asyncio.Lock()


def _get_api_key() -> Optional[str]:
    """Get OpenRouter API key from environment."""
    return os.getenv("OPENROUTER_API_KEY")


async def fetch_openrouter_models(
    force_refresh: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """
    Fetch all models from OpenRouter API.

    MANDATORY FILTER: Only models with BOTH tool_calling AND reasoning capabilities.

    Args:
        force_refresh: Force refresh cache even if already populated

    Returns:
        Dictionary of model configurations filtered by tool calling AND reasoning support.
    """
    global _cached_models

    # Return cached models if available and not forcing refresh
    if _cached_models is not None and not force_refresh:
        return _cached_models

    async with _fetch_lock:
        # Double-check after acquiring lock
        if _cached_models is not None and not force_refresh:
            return _cached_models

        api_key = _get_api_key()
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is required")

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

                # OpenRouter returns {"data": [...]} format
                models_list = data.get("data", [])

                for model in models_list:
                    model_id = model.get("id", "")
                    if not model_id:
                        continue

                    # Extract capabilities
                    # OpenRouter uses different field names - check both formats
                    capabilities = model.get("capabilities", {})

                    # Check for tool calling support
                    supports_tool_calling = (
                        capabilities.get("tool_calling", False)
                        or capabilities.get("supports_tool_calling", False)
                        or "tools" in model.get("supported_parameters", [])
                    )

                    # Check for reasoning support
                    supports_reasoning = (
                        capabilities.get("reasoning", False)
                        or capabilities.get("supports_reasoning", False)
                        or "include_reasoning" in model.get("supported_parameters", [])
                    )

                    # MANDATORY FILTER: Both tool calling AND reasoning must be True
                    if not (supports_tool_calling and supports_reasoning):
                        logger.debug(
                            f"Skipping {model_id}: tool_calling={supports_tool_calling}, reasoning={supports_reasoning}"
                        )
                        continue

                    # Parse provider from model ID (e.g., "anthropic/claude-3.5-sonnet" -> "anthropic")
                    provider = model_id.split("/")[0] if "/" in model_id else "unknown"

                    # Get pricing info
                    pricing = model.get("pricing", {})

                    # Build model config
                    models_dict[model_id] = {
                        "id": model_id,
                        "provider": provider,
                        "name": model.get("name", model_id),
                        "context_window": model.get("context_length", 0),
                        "supports_vision": capabilities.get("vision", False),
                        "supports_tool_calling": True,  # Already filtered
                        "supports_reasoning": True,  # Already filtered
                        "description": f"{provider} model with tool calling and reasoning",
                        "pricing": {
                            "prompt": pricing.get("prompt", "0"),
                            "completion": pricing.get("completion", "0"),
                        },
                        "top_provider": model.get("top_provider", {}),
                    }

                _cached_models = models_dict
                logger.info(
                    f"Fetched {len(models_dict)} models from OpenRouter (filtered for tool_calling + reasoning)"
                )
                return models_dict

        except httpx.HTTPStatusError as e:
            logger.error(
                f"OpenRouter API HTTP error: {e.status_code} - {e.response.text}"
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"Failed to connect to OpenRouter API: {e}")
            raise
        except Exception as e:
            logger.error(f"Error fetching models from OpenRouter: {e}")
            raise


def get_model_config(model_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve configuration for a specific model.
    Uses cached models from OpenRouter API.

    Args:
        model_id: Model identifier (e.g., 'anthropic/claude-3.5-sonnet')

    Returns:
        Model configuration dict or None if not found
    """
    if _cached_models is None:
        return None

    # Try exact match
    if model_id in _cached_models:
        return _cached_models[model_id]

    # Try with provider prefix
    for prefix in [
        "openrouter/",
        "anthropic/",
        "openai/",
        "google/",
        "meta-llama/",
        "mistralai/",
    ]:
        if model_id.startswith(prefix):
            clean_id = model_id[len(prefix) :]
            if clean_id in _cached_models:
                return _cached_models[clean_id]

    return None


def list_available_models() -> list[str]:
    """
    Get list of all available model IDs.
    MANDATORY: All models support BOTH tool calling AND reasoning.
    """
    if _cached_models is None:
        return []
    return list(_cached_models.keys())


def get_models_by_provider(provider: str) -> list[Dict[str, Any]]:
    """
    Get all models from a specific provider.
    MANDATORY: All models support BOTH tool calling AND reasoning.
    """
    if _cached_models is None:
        return []
    return [
        config
        for config in _cached_models.values()
        if config.get("provider") == provider
    ]


def get_recommended_models() -> Dict[str, Dict[str, Any]]:
    """Get recommended models for different use cases."""
    if _cached_models is None:
        return {}

    return {
        "best_reasoning": _cached_models.get("anthropic/claude-3.5-sonnet"),
        "balanced": _cached_models.get("anthropic/claude-3-opus"),
        "fast": _cached_models.get("anthropic/claude-3-haiku"),
        "vision": _cached_models.get("anthropic/claude-3.5-sonnet"),
    }
