"""
Models Configuration
Centralized configuration for LLM models via OpenRouter.
"""

from typing import Any, Dict, Optional

# Model configurations with provider and metadata
MODELS_CONFIG: Dict[str, Dict[str, Any]] = {
    # Anthropic Models via OpenRouter
    "anthropic/claude-3.5-sonnet": {
        "id": "anthropic/claude-3.5-sonnet",
        "provider": "openrouter",
        "name": "Claude 3.5 Sonnet",
        "context_window": 200000,
        "supports_vision": True,
        "supports_tool_calling": True,
        "supports_reasoning": True,
        "description": "Most capable model, best for complex reasoning",
    },
    "anthropic/claude-3-opus": {
        "id": "anthropic/claude-3-opus",
        "provider": "openrouter",
        "name": "Claude 3 Opus",
        "context_window": 200000,
        "supports_vision": True,
        "supports_tool_calling": True,
        "supports_reasoning": True,
        "description": "Balanced performance and cost",
    },
    "anthropic/claude-3-sonnet": {
        "id": "anthropic/claude-3-sonnet",
        "provider": "openrouter",
        "name": "Claude 3 Sonnet",
        "context_window": 200000,
        "supports_vision": True,
        "supports_tool_calling": True,
        "supports_reasoning": True,
        "description": "Good balance of speed and quality",
    },
    "anthropic/claude-3-haiku": {
        "id": "anthropic/claude-3-haiku",
        "provider": "openrouter",
        "name": "Claude 3 Haiku",
        "context_window": 200000,
        "supports_vision": True,
        "supports_tool_calling": True,
        "supports_reasoning": True,
        "description": "Fast and efficient",
    },
    # OpenAI Models via OpenRouter
    "openai/gpt-4-turbo": {
        "id": "openai/gpt-4-turbo",
        "provider": "openrouter",
        "name": "GPT-4 Turbo",
        "context_window": 128000,
        "supports_vision": True,
        "supports_tool_calling": True,
        "supports_reasoning": True,
        "description": "Powerful and reliable",
    },
    "openai/gpt-4": {
        "id": "openai/gpt-4",
        "provider": "openrouter",
        "name": "GPT-4",
        "context_window": 8192,
        "supports_vision": False,
        "supports_tool_calling": True,
        "supports_reasoning": True,
        "description": "Original GPT-4 model",
    },
    "openai/gpt-4o": {
        "id": "openai/gpt-4o",
        "provider": "openrouter",
        "name": "GPT-4o",
        "context_window": 128000,
        "supports_vision": True,
        "supports_tool_calling": True,
        "supports_reasoning": True,
        "description": "Latest optimized GPT-4",
    },
    "openai/gpt-3.5-turbo": {
        "id": "openai/gpt-3.5-turbo",
        "provider": "openrouter",
        "name": "GPT-3.5 Turbo",
        "context_window": 16384,
        "supports_vision": False,
        "supports_tool_calling": True,
        "supports_reasoning": False,
        "description": "Fast and cost-effective",
    },
    # Google Models via OpenRouter
    "google/gemini-pro": {
        "id": "google/gemini-pro",
        "provider": "openrouter",
        "name": "Gemini Pro",
        "context_window": 32768,
        "supports_vision": False,
        "supports_tool_calling": True,
        "supports_reasoning": True,
        "description": "Google's advanced model",
    },
    "google/gemini-pro-vision": {
        "id": "google/gemini-pro-vision",
        "provider": "openrouter",
        "name": "Gemini Pro Vision",
        "context_window": 32768,
        "supports_vision": True,
        "supports_tool_calling": True,
        "supports_reasoning": True,
        "description": "Gemini with vision capabilities",
    },
    # Meta Models via OpenRouter
    "meta-llama/llama-2-70b-chat": {
        "id": "meta-llama/llama-2-70b-chat",
        "provider": "openrouter",
        "name": "Llama 2 70B Chat",
        "context_window": 4096,
        "supports_vision": False,
        "supports_tool_calling": False,
        "supports_reasoning": False,
        "description": "Open source large model",
    },
    # Mistral Models via OpenRouter
    "mistralai/mistral-7b-instruct": {
        "id": "mistralai/mistral-7b-instruct",
        "provider": "openrouter",
        "name": "Mistral 7B Instruct",
        "context_window": 32768,
        "supports_vision": False,
        "supports_tool_calling": True,
        "supports_reasoning": False,
        "description": "Efficient open source model",
    },
}


def get_model_config(model_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve configuration for a specific model.

    Args:
        model_id: Model identifier (e.g., 'anthropic/claude-3.5-sonnet')

    Returns:
        Model configuration dict or None if not found
    """
    # Try exact match first
    if model_id in MODELS_CONFIG:
        return MODELS_CONFIG[model_id]

    # Try with openrouter prefix if not found
    openrouter_key = f"openrouter/{model_id}"
    if openrouter_key in MODELS_CONFIG:
        return MODELS_CONFIG[openrouter_key]

    return None


def list_available_models() -> list[str]:
    """Get list of all available model IDs that support tool calling AND reasoning."""
    return [
        model_id
        for model_id, config in MODELS_CONFIG.items()
        if config.get("supports_tool_calling") and config.get("supports_reasoning")
    ]


def get_models_by_provider(provider: str) -> list[Dict[str, Any]]:
    """Get all models from a specific provider that support tool calling AND reasoning."""
    return [
        config
        for config in MODELS_CONFIG.values()
        if config.get("provider") == provider
        and config.get("supports_tool_calling")
        and config.get("supports_reasoning")
    ]


def get_recommended_models() -> Dict[str, Dict[str, Any]]:
    """Get recommended models for different use cases."""
    return {
        "best_reasoning": MODELS_CONFIG.get("anthropic/claude-3.5-sonnet"),
        "balanced": MODELS_CONFIG.get("anthropic/claude-3-opus"),
        "fast": MODELS_CONFIG.get("anthropic/claude-3-haiku"),
        "vision": MODELS_CONFIG.get("anthropic/claude-3.5-sonnet"),
    }
