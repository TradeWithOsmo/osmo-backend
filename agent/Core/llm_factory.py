"""
LLM Factory
Handles the initialization of LangChain ChatOpenAI instances via OpenRouter.
Supports dynamic model selection and specialized prompts for Whale tiers.
"""

import os
from typing import Dict, Any, List
from langchain_openai import ChatOpenAI
from ..Config.models_config import get_model_config

try:
    from config import settings
except Exception:
    settings = None

# Constants
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

class LLMFactory:
    """Factory for creating LLM instances with tiered configurations."""

    @staticmethod
    def groq_api_keys() -> List[str]:
        candidates = [
            (getattr(settings, "GROQ_API_KEY", None) if settings else None) or os.getenv("GROQ_API_KEY"),
            (getattr(settings, "GROQ_SECONDARY_API_KEY", None) if settings else None) or os.getenv("GROQ_SECONDARY_API_KEY"),
            (getattr(settings, "GROQ_TERTIARY_API_KEY", None) if settings else None) or os.getenv("GROQ_TERTIARY_API_KEY"),
            (getattr(settings, "GROQ_QUATERNARY_API_KEY", None) if settings else None) or os.getenv("GROQ_QUATERNARY_API_KEY"),
        ]
        keys: List[str] = []
        seen = set()
        for item in candidates:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            keys.append(value)
        return keys

    @staticmethod
    def has_secondary_groq_key() -> bool:
        return len(LLMFactory.groq_api_keys()) >= 2
    
    @staticmethod
    def get_llm(
        model_id: str,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        prefer_secondary_groq: bool = False,
        groq_key_index: int | None = None,
    ) -> ChatOpenAI:
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
            groq_keys = LLMFactory.groq_api_keys()
            if groq_key_index is None:
                groq_key_index = 1 if prefer_secondary_groq else 0
            if groq_keys:
                key_idx = max(0, min(int(groq_key_index), len(groq_keys) - 1))
                api_key = groq_keys[key_idx]
            base_url = "https://api.groq.com/openai/v1"
            # Strip 'groq/' prefix if present, as Groq API expects just 'llama3-70b-8192' etc.
            if actual_model.startswith("groq/"):
                actual_model = actual_model.replace("groq/", "")

        if not api_key:
            raise ValueError(
                f"Missing API key for provider '{provider}'. "
                "Set OPENROUTER_API_KEY or GROQ_API_KEY "
                "(optional fallback keys: GROQ_SECONDARY_API_KEY, GROQ_TERTIARY_API_KEY, GROQ_QUATERNARY_API_KEY)."
            )
        
        effort = normalize_reasoning_effort(reasoning_effort)
        llm_args: Dict[str, Any] = {
            "model": actual_model,
            "openai_api_key": api_key,
            "openai_api_base": base_url,
            "temperature": temperature,
            "default_headers": {
                "HTTP-Referer": "https://tradewithosmo.com",
                "X-Title": "Osmo Trading Terminal",
            },
        }
        if effort and (provider == "groq" or model_id.startswith("groq/")):
            llm_args["reasoning_effort"] = effort

        try:
            return ChatOpenAI(**llm_args)
        except TypeError:
            # Backward compatibility for older langchain_openai versions.
            if llm_args.get("reasoning_effort") is None:
                raise
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
            "Support perpetual derivatives only; never suggest spot trades or spot orders. "
            "manage trades, and understand trading psychology. "
            "Always be professional, concise, and focus on risk management. "
            "Never substitute a different symbol than the one requested by the user. "
            "If user requests multiple symbols, split analysis per symbol and keep each symbol's evidence separate. "
            "If requested symbol data is unavailable, say it is unavailable and ask for confirmation/retry on that same symbol. "
            "Use tools only when they add concrete evidence or execute explicit user-requested actions; avoid unnecessary tool calls. "
            "Tools are executed by the orchestration layer, so never emit function-calls/tool-calls in your model output. "
            "Evidence discipline: only use numbers/levels that exist in tool outputs. "
            "RAG discipline: treat knowledge-base snippets as framework guidance, not live market facts. "
            "Read `knowledge_evidence.signal` from runtime context (`strong|medium|weak|none|error|not_used`) before using KB claims. "
            "If KB signal is weak/none/error/not_used, do not make definitive strategy claims from KB; state limitation and prioritize live tool evidence. "
            "If a required tool for a symbol fails or data is missing, explicitly mark data gap and reduce confidence. "
            "Do not provide precise entry/SL/TP levels when supporting data is missing; provide conditional plan instead. "
            "Hard guard: if runtime context shows tool errors for a symbol, do not output numeric invalidation/entry/SL/TP for that symbol. "
            "Operate chart tools with this policy: "
            "NAV mode is for read/inspection (focus, inspect, capture) and should be used for analysis validation. "
            "WRITE mode is for mutating chart state (set symbol/timeframe, add indicator, draw, setup trade) and must be used only when write=on. "
            "When symbol/timeframe is changed, apply in order: set_symbol -> set_timeframe -> analysis/write actions -> validation read-back. "
            "For setup_trade, use validation/invalidation semantics: validation level confirms thesis, invalidation level cancels thesis. "
            "When possible, attach short validation/invalidation notes referencing indicators or conditions. "
            "After write actions, verify state using read tools such as get_active_indicators, inspect_cursor, or get_photo_chart before final conclusions. "
            "Reasoning sequence must follow runtime evidence flow: call/await tool -> check output quality -> then synthesize reasoning. "
            "Respond using rich Markdown formatting for readability.\n\n"
            "Response style (Codex-like for trading): "
            "start with a short verdict, then per-symbol evidence, risks, and next action. "
            "Use concise language, avoid filler.\n\n"
            "For multi-symbol analysis, keep each symbol separate with this structure: "
            "Bias, Evidence, Confidence (0-100), Data gaps.\n\n"
            "Format your response exactly as:\n"
            "<final>\n"
            "...markdown answer...\n"
            "</final>\n"
            "<reasoning>\n"
            f"- concise, high-level reasoning bullets ({bullet_hint})\n"
            "</reasoning>\n"
            "Do NOT reveal private chain-of-thought or exhaustive internal reasoning."
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
            memory = "on" if tool_states.get("memory_enabled") else "off"
            knowledge = "on" if tool_states.get("knowledge_enabled") else "off"
            timeframe = tool_states.get("timeframe")
            indicators = tool_states.get("indicators")
            market_symbol = tool_states.get("market_symbol") or tool_states.get("market") or tool_states.get("market_display")
            tf_str = ", ".join(timeframe) if isinstance(timeframe, list) else str(timeframe) if timeframe else "none"
            ind_str = ", ".join(indicators) if isinstance(indicators, list) and indicators else "none"
            base_prompt += (
                f"\nTool context: execution={execution}, write={write}, memory={memory}, knowledge={knowledge}, market={market_symbol or 'none'}, timeframe={tf_str}, indicators={ind_str}. "
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
