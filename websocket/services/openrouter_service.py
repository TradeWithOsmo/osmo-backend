import httpx
import logging
from typing import List, Dict, Any, Optional
from config import settings

logger = logging.getLogger(__name__)

class OpenRouterService:
    """Service to interact with OpenRouter API for model pricing and availability"""
    
    BASE_URL = "https://openrouter.ai/api/v1"

    PRIORITY_ORDER = [
        "google", "anthropic", "deepseek", "openai", "groq", "qwen", 
        "mistral", "z-ai", "moonshot", "x-ai", "meta"
    ]
    
    def __init__(self):
        self.api_key = settings.OPENROUTER_API_KEY
        self._models_cache = None
        self._providers_cache = None
        self._last_fetch = None

    async def get_models(self, search: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all models and their pricing from OpenRouter (with caching)"""
        import time
        current_time = time.time()
        
        models_list = []
        
        # Return cached if valid (1 hour cache)
        if self._models_cache and self._last_fetch and (current_time - self._last_fetch < 3600):
            models_list = self._models_cache
        else:
            try:
                # --- GROQ MODELS (Added Manually for Testing) ---
                groq_models = [
                    {"id": "groq/openai/gpt-oss-120b", "name": "Groq GPT-OSS 120B", "input_cost": 0, "output_cost": 0, "context": 131072},
                ]
                
                async with httpx.AsyncClient(timeout=30.0) as client:
                    headers = {}
                    if self.api_key:
                        headers["Authorization"] = f"Bearer {self.api_key}"
                    
                    response = await client.get(f"{self.BASE_URL}/models", headers=headers)
                    response.raise_for_status()
                    data = response.json()
                    
                    models = data.get("data", [])
                    
                    # Transform to a cleaner format for our frontend
                    formatted_models = []
                    
                    # --- MOCK/FUTURISTIC MODELS INJECTION ---
                    # These models are requested by the user for the 'Active Models' view.
                    # We inject them to ensure they appear in the UI selection.
                    mock_models = [
                        {"id": "anthropic/claude-4.5-sonnet", "name": "Claude 4.5 Sonnet", "input_cost": 3.0, "output_cost": 15.0, "context": 200000},
                        {"id": "openai/gpt-5.1", "name": "GPT-5.1", "input_cost": 5.0, "output_cost": 25.0, "context": 1000000},
                        {"id": "deepseek/deepseek-chat-v3.1", "name": "DeepSeek Chat v3.1", "input_cost": 0.1, "output_cost": 0.5, "context": 128000},
                        {"id": "google/gemini-3-pro", "name": "Gemini 3 Pro", "input_cost": 1.2, "output_cost": 4.5, "context": 2000000},
                        {"id": "x-ai/grok-4", "name": "Grok 4", "input_cost": 2.5, "output_cost": 10.0, "context": 128000},
                        {"id": "x-ai/grok-420", "name": "Grok 420", "input_cost": 0.69, "output_cost": 4.20, "context": 420000},
                        {"id": "moonshot/kimi-k2-thinking", "name": "Kimi K2 Thinking", "input_cost": 0.5, "output_cost": 2.0, "context": 128000},
                        {"id": "qwen/qwen-3-max", "name": "Qwen 3 Max", "input_cost": 1.5, "output_cost": 6.0, "context": 128000}
                    ]
                    
                    # Add Mock Models
                    for mock in mock_models:
                        formatted_models.append({
                            "id": mock["id"],
                            "name": mock["name"],
                            "input_cost": mock["input_cost"],
                            "output_cost": mock["output_cost"],
                            "includes_markup": False,
                            "context_length": mock["context"],
                            "description": f"Next-gen reasoning model from {mock['id'].split('/')[0].capitalize()}",
                            "capabilities": {"tool_use": True, "reasoning": True, "rag": True}
                        })

                    # Add Groq Models
                    for groq_m in groq_models:
                        formatted_models.append({
                            "id": groq_m["id"],
                            "name": groq_m["name"],
                            "input_cost": groq_m["input_cost"],
                            "output_cost": groq_m["output_cost"],
                            "includes_markup": False,
                            "context_length": groq_m["context"],
                            "description": "High-speed inference model via Groq LPU (Free Tier)",
                            "capabilities": {"tool_use": True, "reasoning": "reasoning" in groq_m["name"].lower(), "rag": True}
                        })
                        
                    for m in models:
                        m_id = m.get("id", "")
                        # Skip if we already added a mock version or if it's a Groq model (unlikely from OR but possible)
                        if any(mock["id"] == m_id for mock in mock_models) or m_id.startswith("groq/"):
                            continue

                        pricing = m.get("pricing", {})
                        # Apply 5% fee markup directly on backend
                        fee_multiplier = 1.05
                        input_cost = float(pricing.get("prompt", 0)) * 1_000_000 * fee_multiplier
                        output_cost = float(pricing.get("completion", 0)) * 1_000_000 * fee_multiplier
                        
                        name = m.get("name", "")
                        if ":" in name:
                            name = name.split(":", 1)[1].strip()

                        context_length = m.get("context_length", 0)
                        
                        # --- AGENTIC FILTERING LOGIC ---
                        if context_length < 32000:
                            continue
                            
                        trusted_families = [
                            "anthropic/", "openai/", "google/", "deepseek/", 
                            "meta/llama-3", "mistralai/mistral-large", "qwen/qwen-2.5",
                            "x-ai/", "moonshot/", "perplexity/", "groq/"
                        ]
                        
                        is_trusted = any(m_id.startswith(family) for family in trusted_families)
                        if not is_trusted:
                            continue

                        blacklist = ["audio", "vision", "image", "preview", "codex", "moderation", "embed", "edit"]
                        if any(word in m_id.lower() for word in blacklist):
                            continue

                        formatted_models.append({
                            "id": m_id,
                            "name": name,
                            "input_cost": input_cost,
                            "output_cost": output_cost,
                            "includes_markup": True,
                            "context_length": context_length,
                            "description": m.get("description", ""),
                            "capabilities": {
                                "tool_use": True,
                                "reasoning": "thought" in m_id.lower() or "r1" in m_id.lower() or "o1" in m_id.lower(),
                                "rag": True
                            }
                        })
                    
                    # Update cache
                    self._last_fetch = current_time
                    models_list = formatted_models
                    
            except Exception as e:
                logger.error(f"Error fetching models from OpenRouter: {e}")
                models_list = self._models_cache if self._models_cache else []

            self._models_cache = models_list

        if search:
            q = search.lower()
            return [
                m for m in models_list 
                if q in m["name"].lower() or q in m["id"].lower()
            ]
        
        return models_list

    async def get_providers(self) -> List[str]:
        """Get unique list of providers from cached models"""
        if self._providers_cache:
             return self._providers_cache
             
        models = await self.get_models()
        providers = set()
        for m in models:
            parts = m["id"].split('/')
            if len(parts) > 1:
                p_name = parts[0]
                # Capitalize
                p_name = p_name.capitalize()
                providers.add(p_name)
            else:
                providers.add('Other')
        
        # Sort with custom priority
        def sort_key(p):
            p_lower = p.lower()
            for idx, key in enumerate(self.PRIORITY_ORDER):
                if key in p_lower:
                    return (idx, p) # Priority group
            return (len(self.PRIORITY_ORDER), p) # Fallback to alphabetic
            
        self._providers_cache = sorted(list(providers), key=sort_key)
        return self._providers_cache

    async def get_models_by_provider(self, provider_name: str) -> List[Dict[str, Any]]:
        """Get models filter by provider name"""
        models = await self.get_models()
        filtered = []
        provider_lower = provider_name.lower()
        
        for m in models:
            parts = m["id"].split('/')
            p_name = parts[0] if len(parts) > 1 else 'other'
            
            if p_name.lower() == provider_lower:
                filtered.append(m)
        
        return filtered

    async def get_model_info(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve detailed info for a specific model ID, handling suffixes."""
        base_id = model_id.split(":")[0]
        models = await self.get_models()
        for m in models:
            if m["id"] == base_id:
                return m
        return None

# Singleton
openrouter_service = OpenRouterService()
