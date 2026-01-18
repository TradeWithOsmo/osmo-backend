"""
Web Search Integration

Multi-model web search routing (Grok 2 for X/Twitter, Perplexity for news).
"""

from ..base_connector import BaseConnector, ConnectorStatus
from typing import Dict, Any, Callable
import os


class WebSearchConnector(BaseConnector):
    """
    Web search connector with multi-model routing.
    
    Models:
    - Grok 2 (x-ai/grok-2-1212): X/Twitter search (exclusive access)
    - Perplexity Large: Quality news search ($1/M tokens)
    - Perplexity Small: Budget news search ($0.20/M tokens)
    
    Important: Web search is MODEL-SPECIFIC. Only Grok 2 and Perplexity
    support web search. Claude/Gemini will hallucinate if asked to search web.
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("web_search", config)
        
        self.openrouter_key = config.get(
            "openrouter_key",
            os.getenv("OPENROUTER_API_KEY")
        )
        
        if self.openrouter_key:
            self.status = ConnectorStatus.HEALTHY
        else:
            self.status = ConnectorStatus.OFFLINE
            print("OPENROUTER_API_KEY not configured")
    
    async def fetch(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """
        Execute web search.
        
        Args:
            symbol: Search subject (e.g., "BTC", "ETH")
            **kwargs:
                - source: "twitter" | "news" | "general"
                - mode: "quality" | "speed" | "budget"
                - query: Custom search query (optional)
        
        Returns:
            Search results (sentiment, news, etc.)
        """
        source = kwargs.get("source", "news")
        mode = kwargs.get("mode", "quality")
        query = kwargs.get("query", f"{symbol} cryptocurrency sentiment")
        
        try:
            # Route to appropriate model
            if source == "twitter":
                result = await self._search_grok(query)
            elif mode == "budget":
                result = await self._search_perplexity(query, model="small")
            else:
                result = await self._search_perplexity(query, model="large")
            
            return self.normalize(result, source)
        
        except Exception as e:
            self.status = ConnectorStatus.ERROR
            raise Exception(f"Web search error: {e}")
    
    async def subscribe(
        self,
        symbol: str,
        callback: Callable,
        **kwargs
    ) -> None:
        """Web search doesn't support subscriptions"""
        raise NotImplementedError("Web search doesn't support subscriptions")
    
    async def _search_grok(self, query: str) -> Dict[str, Any]:
        """
        Search X/Twitter using Grok 2.
        
        Cost: $2/M input tokens, $10/M output tokens
        """
        try:
            import httpx
            
            response = await httpx.AsyncClient().post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openrouter_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "x-ai/grok-2-1212",
                    "messages": [{
                        "role": "user",
                        "content": f"{query}. Analyze sentiment from Twitter/X (last 24h). "
                                   f"Return JSON: {{sentiment_score: -1 to 1, direction: str, "
                                   f"trending_topics: [], sources_count: int}}"
                    }]
                }, timeout=30.0
            )
            
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            # Parse JSON response
            import json
            try:
                data = json.loads(content)
            except:
                # Fallback if not valid JSON
                data = {"raw_response": content}
            
            # Calculate cost
            usage = result.get("usage", {})
            cost = (usage.get("prompt_tokens", 0) * 2 / 1_000_000 + 
                   usage.get("completion_tokens", 0) * 10 / 1_000_000)
            
            data["cost"] = cost
            data["model"] = "grok-2"
            
            return data
        
        except Exception as e:
            raise Exception(f"Grok search failed: {e}")
    
    async def _search_perplexity(
        self,
        query: str,
        model: str = "large"
    ) -> Dict[str, Any]:
        """
        Search web using Perplexity.
        
        Models:
        - large: $1/M tokens (better quality)
        - small: $0.20/M tokens (budget)
        """
        model_id = "perplexity/llama-3.1-sonar-large-128k-online" if model == "large" \
                  else "perplexity/llama-3.1-sonar-small-128k-online"
        
        try:
            import httpx
            
            response = await httpx.AsyncClient().post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openrouter_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model_id,
                    "messages": [{
                        "role": "user",
                        "content": f"Search web: {query}. Provide summary with citations."
                    }]
                },
                timeout=30.0
            )
            
            result = response.json()
            
            # Check for API error
            if "error" in result:
                error_msg = result["error"].get("message", str(result["error"]))
                raise Exception(f"OpenRouter API Error: {error_msg}")
            
            if "choices" not in result:
                raise Exception(f"Unexpected API response: {result}")
                
            content = result["choices"][0]["message"]["content"]
            
            # Calculate cost
            usage = result.get("usage", {})
            cost_per_token = 1 / 1_000_000 if model == "large" else 0.20 / 1_000_000
            cost = usage.get("total_tokens", 0) * cost_per_token
            
            return {
                "summary": content,
                "cost": cost,
                "model": model_id
            }
        
        except Exception as e:
            # self.status = ConnectorStatus.ERROR # Don't mark offline for transient errors
            raise Exception(f"Perplexity search failed: {e}")
    
    def normalize(self, raw_data: Any, source: str) -> Dict[str, Any]:
        """
        Normalize web search results.
        
        Args:
            raw_data: Search results
            source: "twitter" | "news"
        
        Returns:
            Normalized search data
        """
        return {
            "source": "web_search",
            "symbol": None,  # Web search is not symbol-specific
            "data_type": f"{source}_search",
            "timestamp": None,
            "data": raw_data
        }
