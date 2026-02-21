import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx
from config import settings

logger = logging.getLogger(__name__)


class OpenRouterService:
    """Service to interact with OpenRouter API for model pricing and availability"""

    BASE_URL = "https://openrouter.ai/api/v1"

    PRIORITY_ORDER = [
        "google",
        "anthropic",
        "deepseek",
        "openai",
        "qwen",
        "mistral",
        "z-ai",
        "moonshot",
        "x-ai",
        "meta",
    ]

    def __init__(self):
        self.api_key = settings.OPENROUTER_API_KEY
        self._models_cache = None
        self._providers_cache = None
        self._last_fetch = None
        self._cache_ttl_seconds = 3600
        self._models_fetch_lock = asyncio.Lock()

    async def get_models(self, search: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all models and their pricing from OpenRouter (with caching)"""
        import time

        current_time = time.time()

        models_list = []

        def _is_cache_valid() -> bool:
            return bool(
                self._models_cache
                and self._last_fetch
                and (current_time - self._last_fetch < self._cache_ttl_seconds)
            )

        # Fast path for warm cache
        if _is_cache_valid():
            models_list = self._models_cache
        else:
            async with self._models_fetch_lock:
                current_time = time.time()
                if _is_cache_valid():
                    models_list = self._models_cache
                else:
                    try:
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            headers = {}
                            if self.api_key:
                                headers["Authorization"] = f"Bearer {self.api_key}"

                            response = await client.get(
                                f"{self.BASE_URL}/models", headers=headers
                            )
                            response.raise_for_status()
                            data = response.json()

                            models = data.get("data", [])

                            # Transform to a cleaner format for our frontend.
                            # Keep IDs aligned with real providers only (no hardcoded futuristic aliases).
                            formatted_models = []
                            seen_ids = set()

                            def append_model(payload: Dict[str, Any]) -> None:
                                model_id = str(payload.get("id") or "").strip()
                                if not model_id or model_id in seen_ids:
                                    return
                                # Disable OpenRouter free-tier model variants globally.
                                if model_id.endswith(":free"):
                                    return
                                seen_ids.add(model_id)
                                formatted_models.append(payload)

                            for m in models:
                                m_id = m.get("id", "")
                                # OpenRouter-only mode: hide nvidia/* aliases.
                                if m_id.startswith("nvidia/"):
                                    continue

                                pricing = m.get("pricing", {})
                                # Apply 5% fee markup directly on backend
                                fee_multiplier = 1.05
                                input_cost = (
                                    float(pricing.get("prompt", 0))
                                    * 1_000_000
                                    * fee_multiplier
                                )
                                output_cost = (
                                    float(pricing.get("completion", 0))
                                    * 1_000_000
                                    * fee_multiplier
                                )

                                name = m.get("name", "")
                                if ":" in name:
                                    name = name.split(":", 1)[1].strip()

                                context_length = m.get("context_length", 0)

                                # --- AGENTIC FILTERING LOGIC ---
                                if context_length < 32000:
                                    continue

                                trusted_families = [
                                    "anthropic/",
                                    "openai/",
                                    "google/",
                                    "deepseek/",
                                    "meta/llama-3",
                                    "mistralai/mistral-large",
                                    "qwen/qwen-2.5",
                                    "x-ai/",
                                    "moonshot/",
                                    "perplexity/",
                                ]

                                is_trusted = any(
                                    m_id.startswith(family)
                                    for family in trusted_families
                                )
                                if not is_trusted:
                                    continue

                                blacklist = [
                                    "audio",
                                    "vision",
                                    "image",
                                    "preview",
                                    "codex",
                                    "moderation",
                                    "embed",
                                    "edit",
                                ]
                                if any(word in m_id.lower() for word in blacklist):
                                    continue

                                append_model(
                                    {
                                        "id": m_id,
                                        "name": name,
                                        "input_cost": input_cost,
                                        "output_cost": output_cost,
                                        "includes_markup": True,
                                        "context_length": context_length,
                                        "description": m.get("description", ""),
                                        "capabilities": {
                                            "tool_use": True,
                                            "reasoning": "thought" in m_id.lower()
                                            or "r1" in m_id.lower()
                                            or "o1" in m_id.lower(),
                                            "rag": True,
                                        },
                                    }
                                )

                            # Update cache
                            self._last_fetch = current_time
                            self._models_cache = formatted_models
                            self._providers_cache = None
                            models_list = formatted_models

                    except Exception as e:
                        logger.error(f"Error fetching models from OpenRouter: {e}")
                        if self._models_cache:
                            models_list = self._models_cache
                        else:
                            models_list = [
                                {
                                    "id": "anthropic/claude-3.5-sonnet",
                                    "name": "Claude 3.5 Sonnet",
                                    "input_cost": 0,
                                    "output_cost": 0,
                                    "includes_markup": False,
                                    "context_length": 131072,
                                    "description": "Fallback model from OpenRouter catalog",
                                    "capabilities": {
                                        "tool_use": True,
                                        "reasoning": True,
                                        "rag": True,
                                    },
                                },
                                {
                                    "id": "google/gemini-1.5-pro",
                                    "name": "Gemini 1.5 Pro",
                                    "input_cost": 0,
                                    "output_cost": 0,
                                    "includes_markup": False,
                                    "context_length": 131072,
                                    "description": "Fallback model from OpenRouter catalog",
                                    "capabilities": {
                                        "tool_use": True,
                                        "reasoning": True,
                                        "rag": True,
                                    },
                                },
                                {
                                    "id": "deepseek/deepseek-v3",
                                    "name": "DeepSeek V3",
                                    "input_cost": 0,
                                    "output_cost": 0,
                                    "includes_markup": False,
                                    "context_length": 131072,
                                    "description": "Fallback model from OpenRouter catalog",
                                    "capabilities": {
                                        "tool_use": True,
                                        "reasoning": True,
                                        "rag": True,
                                    },
                                },
                                {
                                    "id": "moonshotai/kimi-k2.5",
                                    "name": "Kimi K2.5",
                                    "input_cost": 0,
                                    "output_cost": 0,
                                    "includes_markup": False,
                                    "context_length": 131072,
                                    "description": "Fallback model from OpenRouter catalog",
                                    "capabilities": {
                                        "tool_use": True,
                                        "reasoning": True,
                                        "rag": True,
                                    },
                                },
                            ]
                            self._models_cache = models_list
                            self._last_fetch = current_time

        if search:
            q = search.lower()
            return [
                m for m in models_list if q in m["name"].lower() or q in m["id"].lower()
            ]

        return models_list

    async def get_providers(self) -> List[str]:
        """Get unique list of providers from cached models"""
        if self._providers_cache:
            return self._providers_cache

        models = await self.get_models()
        providers = set()
        for m in models:
            parts = m["id"].split("/")
            if len(parts) > 1:
                p_name = parts[0]
                # Capitalize
                p_name = p_name.capitalize()
                providers.add(p_name)
            else:
                providers.add("Other")

        # Sort with custom priority
        def sort_key(p):
            p_lower = p.lower()
            for idx, key in enumerate(self.PRIORITY_ORDER):
                if key in p_lower:
                    return (idx, p)  # Priority group
            return (len(self.PRIORITY_ORDER), p)  # Fallback to alphabetic

        self._providers_cache = sorted(list(providers), key=sort_key)
        return self._providers_cache

    async def get_models_by_provider(self, provider_name: str) -> List[Dict[str, Any]]:
        """Get models filter by provider name"""
        models = await self.get_models()
        filtered = []
        provider_lower = provider_name.lower()

        for m in models:
            parts = m["id"].split("/")
            p_name = parts[0] if len(parts) > 1 else "other"

            if p_name.lower() == provider_lower:
                filtered.append(m)

        return filtered

    async def get_model_info(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve detailed info for a specific model ID, handling suffixes."""
        base_id = model_id.split(":", 1)[0]
        models = await self.get_models()
        for m in models:
            m_id = m.get("id", "")
            if m_id == model_id or m_id == base_id or m_id.split(":", 1)[0] == base_id:
                return m
        return None


# Singleton
openrouter_service = OpenRouterService()
