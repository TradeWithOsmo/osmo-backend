import httpx
import logging
from typing import List, Dict, Any, Optional
from config import settings

logger = logging.getLogger(__name__)

class OpenRouterService:
    """Service to interact with OpenRouter API for model pricing and availability"""
    
    BASE_URL = "https://openrouter.ai/api/v1"
    
    def __init__(self):
        self.api_key = settings.OPENROUTER_API_KEY
        self._models_cache = None
        self._last_fetch = None

    async def get_models(self) -> List[Dict[str, Any]]:
        """Fetch all models and their pricing from OpenRouter"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                
                response = await client.get(f"{self.BASE_URL}/models", headers=headers)
                response.raise_for_status()
                data = response.json()
                
                models = data.get("data", [])
                
                # Transform to a cleaner format for our frontend
                formatted_models = []
                for m in models:
                    pricing = m.get("pricing", {})
                    # OpenRouter gives pricing in USD per token. We want it per 1M tokens.
                    input_cost = float(pricing.get("prompt", 0)) * 1_000_000
                    output_cost = float(pricing.get("completion", 0)) * 1_000_000
                    
                    formatted_models.append({
                        "id": m.get("id"),
                        "name": m.get("name"),
                        "input_cost": input_cost,
                        "output_cost": output_cost,
                        "context_length": m.get("context_length"),
                        "description": m.get("description", "")
                    })
                
                return formatted_models
        except Exception as e:
            logger.error(f"Error fetching models from OpenRouter: {e}")
            return []

# Singleton
openrouter_service = OpenRouterService()
