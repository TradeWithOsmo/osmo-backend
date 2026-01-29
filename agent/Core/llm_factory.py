"""
LLM Factory
Handles the initialization of LangChain ChatOpenAI instances via OpenRouter.
Supports dynamic model selection and specialized prompts for Whale tiers.
"""

import os
from langchain_openai import ChatOpenAI
from agent.Config.models_config import get_model_config

# Constants
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

class LLMFactory:
    """Factory for creating LLM instances with tiered configurations."""
    
    @staticmethod
    def get_llm(model_id: str, temperature: float = 0.7) -> ChatOpenAI:
        """
        Initializes an LLM via OpenRouter.
        
        Args:
            model_id: The ID of the model to use (e.g., 'anthropic/claude-3.5-sonnet')
            temperature: Sampling temperature
            
        Returns:
            ChatOpenAI instance
        """
        config = get_model_config(model_id)
        if not config:
            raise ValueError(f"Invalid model_id: {model_id}")
            
        # Extract base model if it's a wrapper
        actual_model = config.get("wrapper_for", model_id)
        
        return ChatOpenAI(
            model=actual_model,
            openai_api_key=OPENROUTER_API_KEY,
            openai_api_base=OPENROUTER_BASE_URL,
            temperature=temperature,
            default_headers={
                "HTTP-Referer": "https://tradewithosmo.com",
                "X-Title": "Osmo Trading Terminal"
            }
        )

    @staticmethod
    def get_system_prompt(model_id: str) -> str:
        """
        Returns a specialized system prompt based on the chosen model/tier.
        """
        config = get_model_config(model_id)
        
        base_prompt = (
            "You are Osmo, an advanced AI trading assistant. "
            "You help users analyze markets (Hyperliquid for crypto, Ostium for RWAs), "
            "manage trades, and understand trading psychology. "
            "Always be professional, concise, and focus on risk management."
        )
        
        # Check if it's a "Sovereign" or "Oracle" class (Whale Gimmick)
        if config and config.get("special_prompt"):
            if "sovereign" in model_id:
                return (
                    f"{base_prompt} "
                    "You are now in SOVEREIGN MODE. You provide institutional-grade analysis, "
                    "focusing on deep liquidity, market structure, and macro trends. "
                    "Your tone is direct, authoritative, and focused on maximizing efficiency for high-capital accounts."
                )
            elif "oracle" in model_id:
                return (
                    f"{base_prompt} "
                    "You are now in ORACLE MODE. You focus on predictive patterns, "
                    "advanced geometry, and multi-symbol correlations. "
                    "Your goal is to identify early signals and market anomalies."
                )
                
        return base_prompt
