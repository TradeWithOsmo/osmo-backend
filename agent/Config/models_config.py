"""
AI Models Configuration Registry
Contains all 15+ supported models and their metadata for dynamic selection.
Fees are in USD for 1M tokens (Standard) or per action.
"""

from typing import Dict, List, Any

# Model Providers
PROVIDERS = {
    "google": "google",
    "openai": "openai",
    "anthropic": "anthropic",
    "deepseek": "deepseek",
    "qwen": "qwen"
}

# Standard Model Registry
# Pricing from PortfolioFees.tsx ($ per 1M tokens)
AI_MODELS = {
    # Tier 1 & Above (Standard)
    "google/gemini-1.5-pro": {
        "name": "Gemini 1.5 Pro",
        "provider": PROVIDERS["google"],
        "input_fee": 3.50,
        "output_fee": 10.50,
        "min_tier": 1
    },
    "openai/gpt-4o": {
        "name": "GPT-4o",
        "provider": PROVIDERS["openai"],
        "input_fee": 5.00,
        "output_fee": 15.00,
        "min_tier": 1
    },
    "anthropic/claude-3.5-sonnet": {
        "name": "Claude 3.5 Sonnet",
        "provider": PROVIDERS["anthropic"],
        "input_fee": 3.00,
        "output_fee": 15.00,
        "min_tier": 1
    },
    "deepseek/deepseek-v3": {
        "name": "DeepSeek V3",
        "provider": PROVIDERS["deepseek"],
        "input_fee": 0.14,
        "output_fee": 0.28,
        "min_tier": 1
    },
    "qwen/qwen-2.5-72b": {
        "name": "Qwen 2.5",
        "provider": PROVIDERS["qwen"],
        "input_fee": 0.10,
        "output_fee": 0.20,
        "min_tier": 1
    },
    "google/gemini-1.0-pro": {
        "name": "Gemini 1.0 Pro",
        "provider": PROVIDERS["google"],
        "input_fee": 1.50,
        "output_fee": 4.50,
        "min_tier": 1
    },
    "openai/gpt-3.5-turbo": {
        "name": "GPT-3.5 Turbo",
        "provider": PROVIDERS["openai"],
        "input_fee": 0.50,
        "output_fee": 1.50,
        "min_tier": 1
    },
    "anthropic/claude-3-haiku": {
        "name": "Claude 3 Haiku",
        "provider": PROVIDERS["anthropic"],
        "input_fee": 0.25,
        "output_fee": 1.25,
        "min_tier": 1
    },
    
    # Advanced Tier Models
    "google/gemini-ultra": {
        "name": "Gemini Ultra",
        "provider": PROVIDERS["google"],
        "input_fee": 10.00,
        "output_fee": 30.00,
        "min_tier": 4
    },
    "openai/gpt-4-turbo": {
        "name": "GPT-4 Turbo",
        "provider": PROVIDERS["openai"],
        "input_fee": 10.00,
        "output_fee": 30.00,
        "min_tier": 4
    },
    "anthropic/claude-3-opus": {
        "name": "Claude 3 Opus",
        "provider": PROVIDERS["anthropic"],
        "input_fee": 15.00,
        "output_fee": 75.00,
        "min_tier": 4
    },
    
    # Whale Tier Exclusive (Singularity Class - Gimmicks)
    "anthropic/claude-3.5-sonnet:sovereign": {
        "name": "Osmo Sovereign 🏛️",
        "wrapper_for": "anthropic/claude-3.5-sonnet",
        "provider": PROVIDERS["anthropic"],
        "input_fee": 3.00,
        "output_fee": 15.00,
        "min_tier": 6,
        "special_prompt": True
    },
    "google/gemini-1.5-pro:oracle": {
        "name": "Osmo Oracle 🔮",
        "wrapper_for": "google/gemini-1.5-pro",
        "provider": PROVIDERS["google"],
        "input_fee": 3.50,
        "output_fee": 10.50,
        "min_tier": 4,
        "special_prompt": True
    },
    "deepseek/deepseek-v3:quant": {
        "name": "Black-Box Quant 📈",
        "wrapper_for": "deepseek/deepseek-v3",
        "provider": PROVIDERS["deepseek"],
        "input_fee": 0.14,
        "output_fee": 0.28,
        "min_tier": 6,
        "special_prompt": True
    }
}

def get_available_models(user_tier: int = 1) -> List[Dict[str, Any]]:
    """Returns models that the user is authorized to see/use."""
    available = []
    for model_id, config in AI_MODELS.items():
        if user_tier >= config["min_tier"]:
            model_info = config.copy()
            model_info["id"] = model_id
            available.append(model_info)
    return available

def get_model_config(model_id: str) -> Dict[str, Any]:
    """Retrieves config for a specific model ID."""
    return AI_MODELS.get(model_id)
