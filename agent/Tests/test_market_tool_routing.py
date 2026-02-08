import asyncio

from backend.agent.Tools.data import market


def test_get_price_auto_routes_fiat_cross_to_rwa(monkeypatch):
    called_urls = []

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"symbol": "USD-CHF", "price": 0.78}]

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

        async def get(self, url, *args, **kwargs):
            _ = (args, kwargs)
            called_urls.append(url)
            return _Resp()

    monkeypatch.setattr(market.httpx, "AsyncClient", lambda *a, **k: _Client())
    result = asyncio.run(market.get_price("USD/CHF"))

    assert result.get("asset_type") == "rwa"
    assert called_urls, "Expected at least one connector call."
    assert called_urls[0].endswith("/ostium/prices")
