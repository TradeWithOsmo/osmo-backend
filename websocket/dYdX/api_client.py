import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class DydxAPIClient:
    def __init__(self):
        self.base_url = "https://indexer.dydx.trade/v4"

    async def get_markets(self) -> List[Dict[str, Any]]:
        return await self.get_latest_prices() or []

    async def get_latest_prices(self) -> List[Dict[str, Any]]:
        """
        Fetch perpetual market data from dYdX v4 indexer.
        GET /perpetualMarkets returns: ticker, status, oraclePrice, priceChange24H,
        volume24H, trades24H, openInterest, nextFundingRate, high_24h, low_24h
        """
        try:
            async with httpx.AsyncClient(verify=False, follow_redirects=True, timeout=20) as client:
                resp = await client.get(f"{self.base_url}/perpetualMarkets")
                resp.raise_for_status()
                prices = []
                data = resp.json().get("markets", {})
                for key, p in data.items():
                    sym = p.get("ticker", "")
                    if p.get("status") != "ACTIVE" or not sym.endswith("-USD"):
                        continue
                    base = sym.replace("-USD", "").upper()
                    display = f"{base}-USD"
                    oracle = float(p.get("oraclePrice") or 0)
                    change_24h = float(p.get("priceChange24H") or 0)
                    change_pct = (change_24h / (oracle - change_24h) * 100) if (oracle - change_24h) != 0 else 0.0
                    prices.append({
                        "symbol": display,
                        "from": base,
                        "to": "USD",
                        "price": oracle,
                        "volume_24h": float(p.get("volume24H") or 0),
                        "high_24h": float(p.get("high24h") or 0),
                        "low_24h": float(p.get("low24h") or 0),
                        "open_interest": float(p.get("openInterest") or 0),
                        "funding_rate": float(p.get("nextFundingRate") or 0),
                        "change_24h": change_24h,
                        "change_percent_24h": change_pct,
                        "trades_24h": int(p.get("trades24H") or 0),
                        "source": "dydx",
                    })
                return prices
        except Exception as e:
            logger.error(f"[dYdX] get_latest_prices failed: {e}")
            return []
