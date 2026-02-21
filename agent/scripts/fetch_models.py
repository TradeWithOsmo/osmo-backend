"""
Fetch all models from OpenRouter API and filter by capabilities.
Only models with BOTH tool calling and reasoning support are kept.
"""

import json
import os
from typing import Any, Dict, List

import httpx


def fetch_openrouter_models(api_key: str) -> Dict[str, Any]:
    """
    Fetch all available models from OpenRouter API.

    Args:
        api_key: OpenRouter API key

    Returns:
        Dictionary of models
    """
    url = "https://openrouter.ai/api/v1/models"

    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    print("🔄 Fetching models from OpenRouter...")

    try:
        response = httpx.get(url, headers=headers, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        print(f"✅ Successfully fetched {len(data.get('data', []))} models")
        return data
    except Exception as e:
        print(f"❌ Error fetching models: {e}")
        return {}


def filter_capable_models(models_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Filter models that support BOTH tool calling AND reasoning.

    Args:
        models_data: Raw models data from OpenRouter

    Returns:
        List of filtered models with both capabilities
    """
    if not models_data or "data" not in models_data:
        return []

    models = models_data.get("data", [])
    capable_models = []

    print(f"\n🔍 Filtering models for tool calling + reasoning support...")
    print(f"Total models: {len(models)}\n")

    for model in models:
        model_id = model.get("id", "")
        supports_tool_calling = False
        supports_reasoning = False

        # Check architecture and top_provider for capabilities
        architecture = model.get("architecture", {})
        top_provider = model.get("top_provider", {})

        # Tool calling checks
        if top_provider.get("supports_tool_use"):
            supports_tool_calling = True

        capabilities = architecture.get("capabilities", [])
        if isinstance(capabilities, list):
            if "tool_use" in capabilities:
                supports_tool_calling = True
        elif isinstance(capabilities, dict):
            if capabilities.get("tool_use"):
                supports_tool_calling = True

        # Reasoning checks
        if top_provider.get("supports_reasoning"):
            supports_reasoning = True

        if isinstance(capabilities, dict):
            if capabilities.get("reasoning"):
                supports_reasoning = True
        elif isinstance(capabilities, list):
            if "reasoning" in capabilities:
                supports_reasoning = True

        # Filter: MUST have BOTH capabilities
        if supports_tool_calling and supports_reasoning:
            context_window = None
            if architecture.get("tokenizer"):
                context_window = architecture.get("tokenizer", {}).get("limit")

            pricing = model.get("pricing", {})

            capable_models.append(
                {
                    "id": model_id,
                    "name": model.get("name", model_id),
                    "supports_tool_calling": True,
                    "supports_reasoning": True,
                    "context_window": context_window,
                    "pricing": {
                        "prompt": pricing.get("prompt"),
                        "completion": pricing.get("completion"),
                    },
                    "provider": extract_provider(model_id),
                }
            )
            print(f"✅ {model_id}")

    return capable_models


def extract_provider(model_id: str) -> str:
    """Extract provider name from model ID."""
    parts = model_id.split("/")
    return parts[0] if parts else "unknown"


def save_models_config(models: List[Dict[str, Any]], output_path: str) -> None:
    """
    Save filtered models to Python config file.

    Args:
        models: List of filtered models
        output_path: Path to save config file
    """
    config_content = '''"""
Models Configuration - Auto-generated from OpenRouter API
Only includes models with BOTH tool calling AND reasoning support.
Generated dynamically to keep in sync with OpenRouter.
"""

from typing import Any, Dict, Optional

# Model configurations - Tool calling + Reasoning REQUIRED
MODELS_CONFIG: Dict[str, Dict[str, Any]] = {
'''

    for model in models:
        model_id = model["id"]
        context = model.get("context_window") or "None"
        prompt_price = model.get("pricing", {}).get("prompt") or "None"
        completion_price = model.get("pricing", {}).get("completion") or "None"

        config_content += f'''    "{model_id}": {{
        "id": "{model_id}",
        "name": "{model.get("name", model_id)}",
        "provider": "{model.get("provider", "unknown")}",
        "context_window": {context},
        "supports_tool_calling": True,
        "supports_reasoning": True,
        "pricing": {{"prompt": {prompt_price}, "completion": {completion_price}}},
    }},
'''

    config_content += '''
}


def get_model_config(model_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve configuration for a specific model."""
    if model_id in MODELS_CONFIG:
        return MODELS_CONFIG[model_id]

    openrouter_key = f"openrouter/{model_id}"
    if openrouter_key in MODELS_CONFIG:
        return MODELS_CONFIG[openrouter_key]

    return None


def list_available_models() -> list[str]:
    """Get list of all available model IDs."""
    return list(MODELS_CONFIG.keys())


def get_models_by_provider(provider: str) -> list[Dict[str, Any]]:
    """Get all models from a specific provider."""
    return [
        config
        for config in MODELS_CONFIG.values()
        if config.get("provider") == provider
    ]
'''

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w") as f:
        f.write(config_content)

    print(f"\n✅ Config saved to: {output_path}")


def save_models_json(models: List[Dict[str, Any]], output_path: str) -> None:
    """Save filtered models to JSON file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(models, f, indent=2)

    print(f"✅ Models JSON saved to: {output_path}")


def main():
    """Main execution."""
    api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        print("❌ Error: OPENROUTER_API_KEY environment variable not set")
        return

    # Fetch models
    models_data = fetch_openrouter_models(api_key)

    if not models_data:
        print("❌ Failed to fetch models")
        return

    # Filter models
    capable_models = filter_capable_models(models_data)

    if not capable_models:
        print("\n⚠️  No models found with both tool calling AND reasoning support")
        return

    print(
        f"\n✅ Found {len(capable_models)} models with tool calling + reasoning support\n"
    )

    # Save configurations
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)

    config_path = os.path.join(project_root, "src", "config", "models_config.py")
    json_path = os.path.join(project_root, "models_list.json")

    save_models_config(capable_models, config_path)
    save_models_json(capable_models, json_path)

    print(f"\n📊 Summary:")
    print(f"   Total models with tool calling + reasoning: {len(capable_models)}")
    providers = set(m["provider"] for m in capable_models)
    print(f"   Providers: {providers}")
    print(f"\n✅ Models configuration updated!")


if __name__ == "__main__":
    main()
