"""
LLM Factory
Handles the initialization of LangChain ChatOpenAI instances via OpenRouter.
Supports dynamic model selection and specialized prompts for Whale tiers.
"""

import os
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from agent.Config.models_config import get_model_config

try:
    from config import settings
except Exception:
    settings = None

# Constants
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

class LLMFactory:
    """Factory for creating LLM instances with tiered configurations."""
    
    @staticmethod
    def get_llm(model_id: str, temperature: float = 0.7, reasoning_effort: str | None = None) -> ChatOpenAI:
        """
        Initializes an LLM via OpenRouter or Groq.
        
        Args:
            model_id: The ID of the model to use (e.g., 'anthropic/claude-3.5-sonnet' or 'groq/openai/gpt-oss-120b')
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
        api_key = (settings.OPENROUTER_API_KEY if settings else None) or os.getenv("OPENROUTER_API_KEY")
        base_url = OPENROUTER_BASE_URL
        
        # Groq Override
        if provider == "groq" or model_id.startswith("groq/"):
            api_key = (getattr(settings, "GROQ_API_KEY", None) if settings else None) or os.getenv("GROQ_API_KEY")
            base_url = "https://api.groq.com/openai/v1"
            # Strip 'groq/' prefix if present, as Groq API expects just 'llama3-70b-8192' etc.
            if actual_model.startswith("groq/"):
                actual_model = actual_model.replace("groq/", "")

        if not api_key:
            raise ValueError(f"Missing API key for provider '{provider}'. Set OPENROUTER_API_KEY or GROQ_API_KEY.")
        
        model_kwargs = {}
        effort = normalize_reasoning_effort(reasoning_effort)
        if effort and (provider == "groq" or model_id.startswith("groq/")):
            model_kwargs["reasoning_effort"] = effort

        return ChatOpenAI(
            model=actual_model,
            openai_api_key=api_key,
            openai_api_base=base_url,
            temperature=temperature,
            model_kwargs=model_kwargs,
            default_headers={
                "HTTP-Referer": "https://tradewithosmo.com",
                "X-Title": "Osmo Trading Terminal"
            }
        )

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
        
        bullet_hint = "2-4 bullets"
        if reasoning_effort:
            normalized_effort = reasoning_effort.strip().lower().replace(" ", "_")
            if normalized_effort in ("high", "extra_high"):
                bullet_hint = "3-6 bullets"
            elif normalized_effort == "low":
                bullet_hint = "1-3 bullets"

        base_prompt = (
            "You are Osmo, an advanced AI trading assistant. "
            "You help users analyze markets (Hyperliquid for crypto, Ostium for RWAs), "
            "manage trades, and understand trading psychology. "
            "Always be professional, concise, and focus on risk management. "
            "Respond using rich Markdown formatting for readability.\n\n"
            "Format your response exactly as:\n"
            "<final>\n"
            "...markdown answer...\n"
            "</final>\n"
            "<reasoning_summary>\n"
            f"- short, high-level bullet points ({bullet_hint})\n"
            "</reasoning_summary>\n"
            "Do NOT reveal chain-of-thought or step-by-step reasoning."
        )

        if reasoning_effort:
            effort_label = reasoning_effort.replace("_", " ").title()
            base_prompt += f"\nReasoning effort: {effort_label}. Use higher effort for deeper checks, but keep the final response concise."

            normalized_effort = reasoning_effort.strip().lower().replace(" ", "_")
            if normalized_effort == "low":
                base_prompt += " Prioritize brevity and only the most critical checks."
            elif normalized_effort == "medium":
                base_prompt += " Balance depth with concise outputs."
            elif normalized_effort == "high":
                base_prompt += " Do deeper validation: check assumptions, risks, and alternatives. Call out unknowns briefly."
            elif normalized_effort == "extra_high":
                base_prompt += " Do maximum validation: check assumptions, risks, alternatives, and data gaps. Propose quick verification steps."

        if tool_states:
            execution = "on" if tool_states.get("execution") else "off"
            write = "on" if tool_states.get("write") else "off"
            timeframe = tool_states.get("timeframe")
            indicators = tool_states.get("indicators")
            tf_str = ", ".join(timeframe) if isinstance(timeframe, list) else str(timeframe) if timeframe else "none"
            ind_str = ", ".join(indicators) if isinstance(indicators, list) and indicators else "none"
            base_prompt += (
                f"\nTool context: execution={execution}, write={write}, timeframe={tf_str}, indicators={ind_str}. "
                "Use this context to tailor analysis and request missing data if needed."
            )
        
        # Check if it's a "Sovereign" or "Oracle" class (Whale Gimmick)
        if config and config.get("special_prompt"):
            if "sovereign" in model_id:
                return f"{base_prompt} (Status: Class 2 Active)"
            elif "oracle" in model_id:
                return f"{base_prompt} (Status: Class 3 Active)"
            elif "quant" in model_id:
                return f"{base_prompt} (Status: Class 4 Active)"
                
        return base_prompt
