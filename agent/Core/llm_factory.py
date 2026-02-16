"""
LLM Factory
Handles the initialization of LangChain ChatOpenAI instances via OpenRouter.
Supports dynamic model selection and specialized prompts for Whale tiers.
"""

import os
from typing import Dict, Any, List, Optional, Tuple
from langchain_openai import ChatOpenAI
from ..Config.models_config import get_model_config
from ..Prompts.system_prompt_snippets import build_system_prompt
# Constants
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

class LLMFactory:
    """Factory for creating LLM instances with tiered configurations."""


    @staticmethod
    def groq_api_keys() -> List[str]:
        """
        Returns the configured Groq API keys in priority order.
        Supports both a single key (GROQ_API_KEY) and multiple tier keys.
        """
        keys: List[str] = []
        for env_name in (
            "GROQ_API_KEY",
            "GROQ_SECONDARY_API_KEY",
            "GROQ_TERTIARY_API_KEY",
            "GROQ_QUATERNARY_API_KEY",
        ):
            raw = os.getenv(env_name)
            if raw and raw.strip():
                keys.append(raw.strip())

        # Optional comma-separated list for convenience.
        raw_list = os.getenv("GROQ_API_KEYS")
        if raw_list:
            for item in raw_list.split(","):
                value = item.strip()
                if value:
                    keys.append(value)

        # De-duplicate while preserving order.
        deduped: List[str] = []
        seen = set()
        for k in keys:
            if k in seen:
                continue
            seen.add(k)
            deduped.append(k)
        return deduped

    @staticmethod
    def _split_runtime_provider(model_id: str) -> Tuple[str, str]:
        """
        Supports provider-prefixed IDs like:
        - groq/{model}
        - openrouter/{model}
        - nvidia/{model} (legacy prefix; normalized to openrouter/{model})
        Otherwise defaults to openrouter.

        Returns: (runtime_provider, provider_model_id)
        """
        raw = str(model_id or "").strip()
        if not raw:
            return "openrouter", raw

        base_id, suffix = (raw.split(":", 1) + [None])[:2]
        if "/" not in base_id:
            return "openrouter", raw

        prefix, remainder = base_id.split("/", 1)
        if prefix in {"groq", "openrouter"} and remainder:
            resolved = remainder + (f":{suffix}" if suffix else "")
            return prefix, resolved
        if prefix == "nvidia" and remainder:
            resolved = remainder + (f":{suffix}" if suffix else "")
            return "openrouter", resolved

        return "openrouter", raw

    @staticmethod
    def get_llm(
        model_id: str,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        groq_key_index: int = 0,
    ) -> Any:
        """
        Initializes an LLM via OpenRouter.
        
        Args:
            model_id: The ID of the model to use (e.g., 'anthropic/claude-3.5-sonnet')
            temperature: Sampling temperature
            
        Returns:
            ChatOpenAI instance
        """
        runtime_provider, provider_model_id = LLMFactory._split_runtime_provider(model_id)
        config = get_model_config(provider_model_id)
        # Fallback if config isn't found but ID looks valid
        if not config and provider_model_id:
            config = {"id": provider_model_id, "provider": provider_model_id.split('/')[0] if '/' in provider_model_id else "other"}

        if not config:
            raise ValueError(f"Invalid model_id: {model_id}")
            
        # Extract base model if it's a wrapper
        actual_model = config.get("wrapper_for", provider_model_id)
        
        # Determine Provider
        provider = config.get("provider", "")
        if not provider and "/" in provider_model_id:
            provider = provider_model_id.split("/")[0]

        def normalize_reasoning_effort(value: str | None) -> str | None:
            if not value:
                return None
            normalized = value.strip().lower().replace(" ", "_")
            if normalized in ("low", "medium", "high"):
                return normalized
            if normalized in ("extra_high", "extra-high", "extra high"):
                return "high"
            return None

        # Provider selection (OpenAI-compatible endpoints)
        api_key: Optional[str] = None
        base_url: str = OPENROUTER_BASE_URL

        if runtime_provider == "groq":
            keys = LLMFactory.groq_api_keys()
            if keys:
                idx = max(0, min(int(groq_key_index or 0), len(keys) - 1))
                api_key = keys[idx]
                base_url = GROQ_BASE_URL

        # Default to OpenRouter when no provider-specific key is configured.
        if not api_key:
            api_key = os.getenv("OPENROUTER_API_KEY")
            base_url = OPENROUTER_BASE_URL
        
        if not api_key:
            raise ValueError(
                f"Missing API key for runtime provider '{runtime_provider}'. "
                "Set OPENROUTER_API_KEY (or GROQ_API_KEY for direct Groq provider)."
            )
        
        api_key = api_key.strip()
        print(f"[LLMFactory] Initializing {actual_model} via {runtime_provider}...")

        effort = normalize_reasoning_effort(reasoning_effort)
        llm_args: Dict[str, Any] = {
            "model": actual_model,
            "api_key": api_key,
            "base_url": base_url,
            "temperature": temperature,
        }
        if runtime_provider == "openrouter":
            llm_args["default_headers"] = {
                "HTTP-Referer": "https://tradewithosmo.com",
                "X-Title": "Osmo Trading Terminal",
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
