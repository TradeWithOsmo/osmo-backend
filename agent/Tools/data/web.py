"""
Web Intelligence Tool

Wraps Web Search connector for News (Perplexity) and Social Sentiment (Grok 2).
"""

import asyncio
import os
import re
from typing import Dict, Any, Optional
try:
    from agent.Tools.http_client import get_http_client
except Exception:
    from backend.agent.Tools.http_client import get_http_client
try:
    from agent.Config.tools_config import DATA_SOURCES
except Exception:
    from backend.agent.Config.tools_config import DATA_SOURCES

CONNECTORS_API = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")
WEB_SEARCH_TIMEOUT_SEC = float(os.getenv("WEB_SEARCH_TIMEOUT_SEC", "45"))

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
    client = await get_http_client(timeout_sec=WEB_SEARCH_TIMEOUT_SEC)
    try:
        resp = await client.get(
            url,
            params={"query": query, "source": source or "news", "mode": _normalize_mode(mode)},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        detail = str(e).strip() or e.__class__.__name__
        return {"error": f"News search failed: {detail}"}


async def search_sentiment(symbol: str, mode: str = "quality") -> Dict[str, Any]:
    """
    Search Twitter/X sentiment for a symbol using Grok 2.
    """
    url = f"{CONNECTORS_API}/web_search/search"
    client = await get_http_client(timeout_sec=WEB_SEARCH_TIMEOUT_SEC)
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
        detail = str(e).strip() or e.__class__.__name__
        return {"error": f"Sentiment search failed: {detail}"}


def _infer_symbol(query: str, symbol: Optional[str] = None) -> str:
    if symbol and str(symbol).strip():
        return str(symbol).strip().upper()
    text = str(query or "").strip()
    if not text:
        return "BTC"
    dollar_match = re.search(r"\$([A-Za-z0-9]{2,12})", text)
    if dollar_match:
        return dollar_match.group(1).upper()
    plain_match = re.search(r"\b([A-Za-z]{2,12})[-/](USD|USDT)\b", text, flags=re.IGNORECASE)
    if plain_match:
        return plain_match.group(1).upper()
    token_match = re.search(r"\b(BTC|ETH|SOL|BNB|XRP|DOGE|ADA|AVAX|LINK|SUI|APT|ARB|OP)\b", text, flags=re.IGNORECASE)
    if token_match:
        return token_match.group(1).upper()
    return "BTC"


async def search_web_hybrid(query: str, mode: str = "quality", symbol: Optional[str] = None) -> Dict[str, Any]:
    """
    Hybrid web search:
    - News context (Sonar/OpenRouter path)
    - X/Twitter sentiment context (Grok/OpenRouter path)
    Executed concurrently in one tool call.
    """
    normalized_mode = _normalize_mode(mode)
    effective_query = str(query or "").strip()
    effective_symbol = _infer_symbol(effective_query, symbol=symbol)

    news_task = search_news(query=effective_query, mode=normalized_mode, source="news")
    sentiment_task = search_sentiment(symbol=effective_symbol, mode=normalized_mode)
    news_result, sentiment_result = await asyncio.gather(news_task, sentiment_task)

    news_ok = isinstance(news_result, dict) and not news_result.get("error")
    sentiment_ok = isinstance(sentiment_result, dict) and not sentiment_result.get("error")

    if news_ok and sentiment_ok:
        status = "ok"
        error = None
    elif news_ok or sentiment_ok:
        status = "partial"
        error = None
    else:
        status = "error"
        error = "Hybrid web search failed for both news and sentiment."

    return {
        "status": status,
        "query": effective_query,
        "symbol": effective_symbol,
        "mode": normalized_mode,
        "news": news_result,
        "sentiment": sentiment_result,
        "results_count": int(news_ok) + int(sentiment_ok),
        **({"error": error} if error else {}),
    }
