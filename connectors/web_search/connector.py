"""
Web Search Integration

Resilient web search connector:
- Primary: OpenRouter models (Perplexity/X-AI/OpenAI search variants)
- Fallback: Google News RSS (no API key, no credits)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote_plus
from xml.etree import ElementTree

import httpx

from ..base_connector import BaseConnector, ConnectorStatus


class _ProviderError(Exception):
    def __init__(self, message: str, model: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.model = model
        self.status_code = status_code

    @property
    def is_insufficient_credits(self) -> bool:
        text = (self.message or "").lower()
        return self.status_code == 402 or "insufficient credits" in text


class WebSearchConnector(BaseConnector):
    """
    Web search connector with model fallback and zero-cost RSS fallback.
    """

    NEWS_MODELS_BY_MODE: Dict[str, List[str]] = {
        "quality": [
            "perplexity/sonar-pro-search",
            "perplexity/sonar-pro",
            "perplexity/sonar",
            "openai/gpt-4o-search-preview",
            "openai/gpt-4o-mini-search-preview",
        ],
        "speed": [
            "perplexity/sonar",
            "openai/gpt-4o-mini-search-preview",
            "relace/relace-search",
        ],
        "budget": [
            "perplexity/sonar",
            "openai/gpt-4o-mini-search-preview",
        ],
    }
    TWITTER_MODELS: List[str] = [
        "x-ai/grok-4-fast",
        "x-ai/grok-3-mini",
        "x-ai/grok-3",
    ]

    def __init__(self, config: Dict[str, Any]):
        super().__init__("web_search", config)
        self.openrouter_key = config.get("openrouter_key", os.getenv("OPENROUTER_API_KEY"))
        self.request_timeout = float(config.get("request_timeout_sec", 30))
        self.rss_timeout = float(config.get("rss_timeout_sec", 15))
        self.max_rss_items = int(config.get("rss_max_items", 8))

        # Degraded (not offline) because RSS fallback can still work without key.
        self.status = ConnectorStatus.HEALTHY if self.openrouter_key else ConnectorStatus.DEGRADED

    async def fetch(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """
        Execute web search.

        Args:
            symbol: Search subject (unused directly; query is preferred)
            kwargs:
                - source: "twitter" | "news" | "general"
                - mode: "quality" | "speed" | "budget"
                - query: custom query
        """
        source = str(kwargs.get("source", "news") or "news").strip().lower()
        mode = self._normalize_mode(kwargs.get("mode"))
        query = str(kwargs.get("query") or f"{symbol} market update").strip()

        try:
            if source == "twitter":
                payload = await self._search_twitter(query=query, mode=mode)
            else:
                payload = await self._search_news(query=query, mode=mode)

            if isinstance(payload, dict) and payload.get("error"):
                self.status = ConnectorStatus.DEGRADED
            elif self.openrouter_key:
                self.status = ConnectorStatus.HEALTHY
            else:
                self.status = ConnectorStatus.DEGRADED

            return self.normalize(payload, source)
        except Exception as exc:
            self.status = ConnectorStatus.ERROR
            return self.normalize(
                {
                    "error": f"Web search failed: {exc}",
                    "query": query,
                    "mode": mode,
                    "source": source,
                },
                source,
            )

    async def subscribe(self, symbol: str, callback: Callable, **kwargs) -> None:
        """Web search does not support subscriptions."""
        raise NotImplementedError("Web search does not support subscriptions")

    async def _search_news(self, query: str, mode: str) -> Dict[str, Any]:
        provider_errors: List[Dict[str, Any]] = []

        if self.openrouter_key:
            for model in self._news_models_for_mode(mode):
                try:
                    result = await self._search_with_openrouter(
                        model=model,
                        prompt=f"Search web for: {query}. Provide concise summary with citations.",
                    )
                    result["mode"] = mode
                    result["query"] = query
                    result["source"] = "news"
                    return result
                except _ProviderError as exc:
                    provider_errors.append(
                        {
                            "model": exc.model,
                            "status_code": exc.status_code,
                            "message": exc.message,
                        }
                    )
                    if exc.is_insufficient_credits:
                        break

        rss_result = await self._search_google_news_rss(query=query)
        if rss_result.get("items"):
            rss_result["fallback_reason"] = "openrouter_failed_or_unavailable"
            rss_result["provider_errors"] = provider_errors
            return rss_result

        return {
            "error": "No news results available from OpenRouter and RSS fallback.",
            "query": query,
            "mode": mode,
            "provider_errors": provider_errors,
        }

    async def _search_twitter(self, query: str, mode: str) -> Dict[str, Any]:
        provider_errors: List[Dict[str, Any]] = []

        if self.openrouter_key:
            for model in self.TWITTER_MODELS:
                try:
                    result = await self._search_with_openrouter(
                        model=model,
                        prompt=(
                            f"{query}. Analyze X/Twitter sentiment in last 24h. "
                            "Return compact JSON: "
                            '{"sentiment_score": -1 to 1, "direction": "bullish|bearish|neutral", '
                            '"trending_topics": [], "sources_count": number}'
                        ),
                    )
                    parsed = self._try_parse_json(result.get("summary", ""))
                    if parsed:
                        parsed.setdefault("model", model)
                        parsed.setdefault("provider", "openrouter")
                        parsed.setdefault("query", query)
                        parsed.setdefault("mode", mode)
                        return parsed
                    return {
                        "provider": "openrouter",
                        "model": model,
                        "query": query,
                        "mode": mode,
                        "raw_response": result.get("summary", ""),
                    }
                except _ProviderError as exc:
                    provider_errors.append(
                        {
                            "model": exc.model,
                            "status_code": exc.status_code,
                            "message": exc.message,
                        }
                    )
                    if exc.is_insufficient_credits:
                        break

        # Fallback heuristic: infer sentiment from latest headlines.
        rss_result = await self._search_google_news_rss(query=f"{query} crypto market")
        items = rss_result.get("items") or []
        if items:
            sentiment = self._heuristic_sentiment(items)
            return {
                "provider": "rss_heuristic",
                "model": "google-news-rss-heuristic",
                "query": query,
                "mode": mode,
                "sentiment_score": sentiment["score"],
                "direction": sentiment["direction"],
                "trending_topics": sentiment["topics"],
                "sources_count": len(items),
                "provider_errors": provider_errors,
            }

        return {
            "error": "No sentiment results available from OpenRouter and RSS fallback.",
            "query": query,
            "mode": mode,
            "provider_errors": provider_errors,
        }

    async def _search_with_openrouter(self, model: str, prompt: str) -> Dict[str, Any]:
        if not self.openrouter_key:
            raise _ProviderError("OPENROUTER_API_KEY is missing", model=model, status_code=401)

        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 500,
        }

        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
            )

        body = self._safe_json(response)
        if response.status_code >= 400:
            message = self._extract_error_message(body) or response.text or "OpenRouter request failed"
            raise _ProviderError(message=message, model=model, status_code=response.status_code)

        choices = body.get("choices") if isinstance(body, dict) else None
        if not choices:
            raise _ProviderError(
                message=f"Unexpected OpenRouter response: {body}",
                model=model,
                status_code=response.status_code,
            )

        content = choices[0].get("message", {}).get("content", "")
        usage = body.get("usage", {}) if isinstance(body, dict) else {}
        return {
            "provider": "openrouter",
            "model": model,
            "summary": content,
            "usage": usage,
            "cost": self._estimate_cost_from_usage(usage),
            "citations": self._extract_urls(content),
        }

    async def _search_google_news_rss(self, query: str) -> Dict[str, Any]:
        url = (
            "https://news.google.com/rss/search?"
            f"q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
        )
        try:
            async with httpx.AsyncClient(timeout=self.rss_timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
            root = ElementTree.fromstring(response.text)

            items: List[Dict[str, Any]] = []
            for node in root.findall(".//item")[: self.max_rss_items]:
                title = (node.findtext("title") or "").strip()
                link = (node.findtext("link") or "").strip()
                pub_date = (node.findtext("pubDate") or "").strip()
                source_node = node.find("source")
                source_name = (
                    (source_node.text or "").strip() if source_node is not None and source_node.text else ""
                )
                if title:
                    items.append(
                        {
                            "title": title,
                            "url": link,
                            "published_at": pub_date,
                            "source": source_name or None,
                        }
                    )

            summary = self._build_rss_summary(items)
            return {
                "provider": "google_news_rss",
                "model": "google-news-rss",
                "query": query,
                "summary": summary,
                "items": items,
                "cost": 0.0,
            }
        except Exception as exc:
            return {
                "error": f"Google News RSS fallback failed: {exc}",
                "provider": "google_news_rss",
                "query": query,
                "items": [],
            }

    def _normalize_mode(self, mode: Any) -> str:
        value = str(mode or "quality").strip().lower()
        if value in {"quality", "speed", "budget"}:
            return value
        return "quality"

    def _news_models_for_mode(self, mode: str) -> List[str]:
        return self.NEWS_MODELS_BY_MODE.get(mode, self.NEWS_MODELS_BY_MODE["quality"])

    def _safe_json(self, response: httpx.Response) -> Dict[str, Any]:
        try:
            parsed = response.json()
            return parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            return {"raw_text": response.text}

    def _extract_error_message(self, body: Dict[str, Any]) -> Optional[str]:
        if not isinstance(body, dict):
            return None
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)
        if error:
            return str(error)
        return None

    def _extract_urls(self, text: str) -> List[str]:
        if not text:
            return []
        urls = re.findall(r"https?://[^\s)\]}>\"']+", text)
        seen = set()
        unique: List[str] = []
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            unique.append(url)
        return unique[:12]

    def _estimate_cost_from_usage(self, usage: Dict[str, Any]) -> float:
        # Provider/model pricing differs; keep lightweight estimate placeholder.
        # We preserve the field for compatibility with downstream consumers.
        _ = usage
        return 0.0

    def _build_rss_summary(self, items: List[Dict[str, Any]]) -> str:
        if not items:
            return "No recent headlines found."
        top = items[:5]
        lines = [f"- {item.get('title', '')}" for item in top if item.get("title")]
        return "\n".join(lines) if lines else "No recent headlines found."

    def _try_parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            # Try extracting JSON object from mixed text.
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                return None
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None

    def _heuristic_sentiment(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        positive_terms = {
            "surge",
            "rally",
            "gain",
            "bullish",
            "breakout",
            "up",
            "rise",
            "record",
        }
        negative_terms = {
            "drop",
            "fall",
            "bearish",
            "crash",
            "selloff",
            "down",
            "loss",
            "decline",
        }

        pos = 0
        neg = 0
        topics: List[str] = []
        for item in items[:12]:
            title = str(item.get("title") or "")
            lower = title.lower()
            words = set(re.findall(r"[a-zA-Z]{3,}", lower))
            pos += sum(1 for term in positive_terms if term in words)
            neg += sum(1 for term in negative_terms if term in words)
            for token in re.findall(r"\b[A-Z]{2,6}\b", title):
                if token not in topics:
                    topics.append(token)
                if len(topics) >= 8:
                    break

        score = 0.0
        total = pos + neg
        if total > 0:
            score = (pos - neg) / float(total)
        score = max(-1.0, min(1.0, score))

        if score > 0.2:
            direction = "bullish"
        elif score < -0.2:
            direction = "bearish"
        else:
            direction = "neutral"

        return {
            "score": round(score, 3),
            "direction": direction,
            "topics": topics[:6],
        }

    def normalize(self, raw_data: Any, source: str) -> Dict[str, Any]:
        return {
            "source": "web_search",
            "symbol": None,
            "data_type": f"{source}_search",
            "timestamp": None,
            "data": raw_data,
        }

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update(
            {
                "openrouter_key_configured": bool(self.openrouter_key),
                "request_timeout_sec": self.request_timeout,
                "rss_fallback_enabled": True,
            }
        )
        return base
