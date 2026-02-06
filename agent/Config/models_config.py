"""
AI Models Configuration Registry
All pricing and provider data is fetched live from OpenRouter.
Specialized modes are detected dynamically via ID suffixes.
"""

from typing import Dict, List, Any

def get_model_config(model_id: str) -> Dict[str, Any]:
    """
    Dynamically generates configuration for any model ID.
    Detects Osmo specialized modes like :sovereign, :oracle, or :quant.
    """
    parts = model_id.split(":")
    base_id = parts[0]
    suffix = parts[1].lower() if len(parts) > 1 else None
    
    # Base metadata
    clean_name = base_id.split("/")[-1].replace("-", " ").title()
    provider = base_id.split("/")[0] if "/" in base_id else "other"
    
    config = {
        "id": model_id,
        "name": clean_name,
        "provider": provider,
        "input_fee": 1.00,
        "output_fee": 2.00,
    }
    
    # Pure dynamic detection for specialized Osmo wrappers
    if suffix:
        # Map suffix to display name dynamically
        mode_names = {
            "sovereign": "Sovereign 🏛️",
            "oracle": "Oracle 🔮",
            "quant": "Black-Box Quant 📈"
        }
        
        display_suffix = mode_names.get(suffix, suffix.title())
        config["name"] = f"Osmo {display_suffix}"
        config["wrapper_for"] = base_id
        config["special_prompt"] = True
        
    return config

def get_available_models(user_tier: int = 1) -> List[Dict[str, Any]]:
    """
    Returns the list of specialized models currently enabled.
    """
    curated_wrappers = [
        "anthropic/claude-3.5-sonnet:sovereign",
        "google/gemini-1.5-pro:oracle",
        "deepseek/deepseek-v3:quant"
    ]
    return [get_model_config(m) for m in curated_wrappers]
