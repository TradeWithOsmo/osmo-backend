"""
LLM Factory
Handles the initialization of LangChain ChatOpenAI instances via OpenRouter.
Supports dynamic model selection and specialized prompts.
"""

import os
from typing import Any, Dict, List, Optional, Tuple

from langchain_openai import ChatOpenAI

from ..config.models_config import get_model_config
from ..utils.prompts import build_system_prompt

# Constants
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class LLMFactory:
    """Factory for creating LLM instances with OpenRouter."""

    @staticmethod
    def _split_runtime_provider(model_id: str) -> str:
        """
        Parse model ID and return the actual model identifier.
        Supports provider-prefixed IDs like:
        - openrouter/{model}
        - {model} (defaults to openrouter)

        Returns: model_id
        """
        raw = str(model_id or "").strip()
        if not raw:
            return raw

        # Remove openrouter prefix if present
        if raw.startswith("openrouter/"):
            return raw.replace("openrouter/", "")

        return raw

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
            temperature: Sampling temperature (0.0-1.0)
            reasoning_effort: Reasoning effort level (low, medium, high)

        Returns:
            ChatOpenAI instance

        Raises:
            ValueError: If model_id is invalid or API key is missing
        """
        # Parse model ID
        actual_model = LLMFactory._split_runtime_provider(model_id)

        if not actual_model:
            raise ValueError(f"Invalid model_id: {model_id}")

        # Get API key
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError(
                "Missing required environment variable: OPENROUTER_API_KEY. "
                "Set your OpenRouter API key to use the agent."
            )

        api_key = api_key.strip()
        base_url = OPENROUTER_BASE_URL

        print(f"[LLMFactory] Initializing {actual_model} via OpenRouter...")

        # Build LLM arguments
        llm_args: Dict[str, Any] = {
            "model": actual_model,
            "api_key": api_key,
            "base_url": base_url,
            "temperature": temperature,
        }

        # Add OpenRouter headers
        llm_args["default_headers"] = {
            "HTTP-Referer": "https://tradewithosmo.com",
            "X-Title": "Osmo Trading Terminal",
        }

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
        """
        Returns a specialized system prompt based on the chosen model.

        Args:
            model_id: The model identifier
            reasoning_effort: Optional reasoning effort level
            tool_states: Optional dictionary of tool states

        Returns:
            System prompt string
        """
        config = get_model_config(model_id)
        base_prompt = build_system_prompt(
            reasoning_effort=reasoning_effort,
            tool_states=tool_states,
        )

        return base_prompt
