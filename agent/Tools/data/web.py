"""
Web Intelligence Tool

Wraps Web Search connector for News (Perplexity) and Social Sentiment (Grok 2).
"""

import httpx
from typing import Dict, Any
try:
    from agent.Config.tools_config import DATA_SOURCES
except Exception:
    from backend.agent.Config.tools_config import DATA_SOURCES

CONNECTORS_API = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")

def _normalize_mode(mode: str | None, default: str = "quality") -> str:
    value = (mode or default).strip().lower()
    if value in {"quality", "speed", "budget"}:
        return value
    return default


async def search_news(query: str, mode: str = "quality", source: str = "news") -> Dict[str, Any]:
    """
    Search for high-quality news using Perplexity.
    """
    url = f"{CONNECTORS_API}/web_search/search"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                url,
                params={"query": query, "source": source or "news", "mode": _normalize_mode(mode)},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": f"News search failed: {str(e)}"}


async def search_sentiment(symbol: str, mode: str = "quality") -> Dict[str, Any]:
    """
    Search Twitter/X sentiment for a symbol using Grok 2.
    """
    url = f"{CONNECTORS_API}/web_search/search"
    async with httpx.AsyncClient() as client:
        try:
            # Grok for sentiment (source="twitter")
            query = f"${symbol} crypto sentiment analysis"
            resp = await client.get(
                url,
                params={"query": query, "source": "twitter", "mode": _normalize_mode(mode)},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": f"Sentiment search failed: {str(e)}"}
