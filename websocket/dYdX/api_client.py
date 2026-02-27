import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class DydxAPIClient:
    def __init__(self):
        self.base_url = "https://indexer.dydx.trade/v4"

    async def get_markets(self) -> List[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
                resp = await client.get(f"{self.base_url}/perpetualMarkets", timeout=20)
                resp.raise_for_status()
                markets = []
                data = resp.json().get("markets", {})
                for key, p in data.items():
                    sym = p.get("ticker", "")
                    if p.get("status") == "ACTIVE" and sym.endswith("-USD"):
                        base = sym.replace("-USD", "").upper()
                        markets.append({
                            "symbol": f"{base}-USD",
                            "from": base,
                            "to": "USD",
                        })
                return markets
        except Exception as e:
            logger.error(f"[dYdX] get_markets failed: {e}")
            return []

    async def get_latest_prices(self) -> List[Dict[str, Any]]:
        """Fetch live market data including prices from dYdX v4 indexer."""
        try:
            async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
                resp = await client.get(f"{self.base_url}/perpetualMarkets", timeout=20)
                resp.raise_for_status()
                prices = []
                data = resp.json().get("markets", {})
                for key, p in data.items():
                    sym = p.get("ticker", "")
                    if p.get("status") != "ACTIVE" or not sym.endswith("-USD"):
                        continue
                    base = sym.replace("-USD", "").upper()
                    display = f"{base}-USD"
                    prices.append({
                        "symbol": display,
                        "price": p.get("oraclePrice") or p.get("priceChange24H") or 0,
                        "oracle_price": p.get("oraclePrice") or 0,
                        "volume_24h": p.get("volume24H") or 0,
                        "open_interest": p.get("openInterest") or 0,
                        "next_funding_rate": p.get("nextFundingRate") or 0,
                    })
                return prices
        except Exception as e:
            logger.error(f"[dYdX] get_latest_prices failed: {e}")
            return []
