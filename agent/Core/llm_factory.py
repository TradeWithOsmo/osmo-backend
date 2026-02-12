"""
LLM Factory
Handles the initialization of LangChain ChatOpenAI instances via OpenRouter.
Supports dynamic model selection and specialized prompts for Whale tiers.
"""

import os
from typing import Dict, Any, List, Optional
from langchain_openai import ChatOpenAI
from ..Config.models_config import get_model_config
from ..Prompts.system_prompt_snippets import build_system_prompt
# Constants
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

class LLMFactory:
    """Factory for creating LLM instances with tiered configurations."""


    
    @staticmethod
    def get_llm(
        model_id: str,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
    ) -> Any:
        """
        Initializes an LLM via OpenRouter.
        
        Args:
            model_id: The ID of the model to use (e.g., 'anthropic/claude-3.5-sonnet')
            temperature: Sampling temperature
            
        Returns:
            ChatOpenAI instance
        """
        config = get_model_config(model_id)
        # Fallback if config isn't found but ID looks valid
        if not config and model_id: 
            config = {"id": model_id, "provider": model_id.split('/')[0] if '/' in model_id else "other"}

        if not config:
            raise ValueError(f"Invalid model_id: {model_id}")
            
        # Extract base model if it's a wrapper
        actual_model = config.get("wrapper_for", model_id)
        
        # Determine Provider
        provider = config.get("provider", "")
        if not provider and "/" in model_id:
            provider = model_id.split("/")[0]

        def normalize_reasoning_effort(value: str | None) -> str | None:
            if not value:
                return None
            normalized = value.strip().lower().replace(" ", "_")
            if normalized in ("low", "medium", "high"):
                return normalized
            if normalized in ("extra_high", "extra-high", "extra high"):
                return "high"
            return None

        # Default to OpenRouter
        api_key = os.getenv("OPENROUTER_API_KEY")
        base_url = OPENROUTER_BASE_URL
        
        if not api_key:
            raise ValueError(
                f"Missing API key for provider '{provider}'. "
                "Set OPENROUTER_API_KEY."
            )
        
        api_key = api_key.strip()
        print(f"[LLMFactory] Initializing {actual_model} via OpenRouter...")

        effort = normalize_reasoning_effort(reasoning_effort)
        llm_args: Dict[str, Any] = {
            "model": actual_model,
            "api_key": api_key,
            "base_url": base_url,
            "temperature": temperature,
            "default_headers": {
                "HTTP-Referer": "https://tradewithosmo.com",
                "X-Title": "Osmo Trading Terminal",
            },
        }

        try:
            return ChatOpenAI(**llm_args)
        except TypeError:
            # Backward compatibility for older langchain_openai versions.
            # Some versions use openai_api_key/openai_api_base instead of api_key/base_url
            # or don't support reasoning_effort
            if "api_key" in llm_args:
                llm_args["openai_api_key"] = llm_args.pop("api_key")
            if "base_url" in llm_args:
                llm_args["openai_api_base"] = llm_args.pop("base_url")
                
            if llm_args.get("reasoning_effort") is None:
                return ChatOpenAI(**llm_args)

            fallback_args = dict(llm_args)
            fallback_args.pop("reasoning_effort", None)
            fallback_args["model_kwargs"] = {"reasoning_effort": effort}
            return ChatOpenAI(**fallback_args)

    @staticmethod
    def get_system_prompt(
        model_id: str,
        reasoning_effort: str | None = None,
        tool_states: Dict[str, Any] | None = None
    ) -> str:
        """
        Returns a specialized system prompt based on the chosen model/tier.
        """
        config = get_model_config(model_id)
        base_prompt = build_system_prompt(
            reasoning_effort=reasoning_effort,
            tool_states=tool_states,
        )

        # Keep tier labels for custom "whale gimmick" wrappers.
        if config and config.get("special_prompt"):
            if "sovereign" in model_id:
                return f"{base_prompt}\n\nStatus: Class 2 Active"
            if "oracle" in model_id:
                return f"{base_prompt}\n\nStatus: Class 3 Active"
            if "quant" in model_id:
                return f"{base_prompt}\n\nStatus: Class 4 Active"

        return base_prompt
