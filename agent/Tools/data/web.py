"""
Web Intelligence Tool

Wraps Web Search connector for News (Perplexity) and Social Sentiment (Grok 2).
"""

import httpx
from typing import Dict, Any
from backend.agent.Config.tools_config import DATA_SOURCES

CONNECTORS_API = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")

async def search_news(query: str) -> Dict[str, Any]:
    """
    Search for high-quality news using Perplexity.
    """
    url = f"{CONNECTORS_API}/web_search/search"
    async with httpx.AsyncClient() as client:
        try:
            # Perplexity for news (source="news")
            resp = await client.get(url, params={"query": query, "source": "news"})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": f"News search failed: {str(e)}"}

async def search_sentiment(symbol: str) -> Dict[str, Any]:
    """
    Search Twitter/X sentiment for a symbol using Grok 2.
    """
    url = f"{CONNECTORS_API}/web_search/search"
    async with httpx.AsyncClient() as client:
        try:
            # Grok for sentiment (source="twitter")
            query = f"${symbol} crypto sentiment analysis"
            resp = await client.get(url, params={"query": query, "source": "twitter"})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": f"Sentiment search failed: {str(e)}"}
