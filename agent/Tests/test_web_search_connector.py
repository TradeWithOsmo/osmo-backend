import asyncio

from backend.connectors.web_search.connector import WebSearchConnector, _ProviderError


def test_web_search_news_falls_back_to_rss_when_openrouter_fails():
    async def _run():
        connector = WebSearchConnector({"openrouter_key": "dummy"})

        async def fake_openrouter(model: str, prompt: str):
            raise _ProviderError("No endpoints found", model=model, status_code=404)

        async def fake_rss(query: str):
            return {
                "provider": "google_news_rss",
                "model": "google-news-rss",
                "query": query,
                "summary": "- Headline A\n- Headline B",
                "items": [
                    {"title": "Headline A", "url": "https://example.com/a"},
                    {"title": "Headline B", "url": "https://example.com/b"},
                ],
                "cost": 0.0,
            }

        connector._search_with_openrouter = fake_openrouter  # type: ignore[attr-defined]
        connector._search_google_news_rss = fake_rss  # type: ignore[attr-defined]

        result = await connector.fetch("BTC", query="btc news", source="news", mode="quality")
        data = result.get("data", {})
        assert data.get("provider") == "google_news_rss"
        assert len(data.get("items") or []) == 2
        assert "provider_errors" in data

    asyncio.run(_run())


def test_web_search_returns_error_payload_when_all_backends_fail():
    async def _run():
        connector = WebSearchConnector({"openrouter_key": "dummy"})

        async def fake_openrouter(model: str, prompt: str):
            raise _ProviderError("Insufficient credits", model=model, status_code=402)

        async def fake_rss(query: str):
            return {
                "error": "rss unavailable",
                "provider": "google_news_rss",
                "query": query,
                "items": [],
            }

        connector._search_with_openrouter = fake_openrouter  # type: ignore[attr-defined]
        connector._search_google_news_rss = fake_rss  # type: ignore[attr-defined]

        result = await connector.fetch("BTC", query="btc news", source="news", mode="quality")
        data = result.get("data", {})
        assert "error" in data
        assert "provider_errors" in data

    asyncio.run(_run())
