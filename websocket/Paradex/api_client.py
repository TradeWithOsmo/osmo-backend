import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class ParadexAPIClient:
    def __init__(self):
        self.base_url = "https://api.prod.paradex.trade/v1"

    async def get_markets(self) -> List[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(verify=False) as client:
                resp = await client.get(f"{self.base_url}/markets", timeout=20)
                resp.raise_for_status()
                markets = []
                for p in resp.json().get("results", []):
                    sym = p.get("symbol", "")
                    if sym.endswith("-USD-PERP"):
                        base = sym.replace("-USD-PERP", "").upper()
                        markets.append({
                            "symbol": f"{base}-USD",
                            "from": base,
                            "to": "USD",
                        })
                return markets
        except Exception as e:
            logger.error(f"[Paradex] get_markets failed: {e}")
            return []

    async def get_latest_prices(self) -> List[Dict[str, Any]]:
        """Fetch live market summary from Paradex."""
        try:
            async with httpx.AsyncClient(verify=False) as client:
                resp = await client.get(f"{self.base_url}/markets/summary", timeout=20)
                resp.raise_for_status()
                results = resp.json().get("results", [])
                prices = []
                for item in results:
                    sym = item.get("symbol", "")
                    if not sym.endswith("-USD-PERP"):
                        continue
                    base = sym.replace("-USD-PERP", "").upper()
                    display = f"{base}-USD"
                    prices.append({
                        "symbol": display,
                        "price": item.get("mark_price") or item.get("last_traded_price") or 0,
                        "volume_24h": item.get("volume_24h") or 0,
                        "open_interest": item.get("open_interest") or 0,
                        "funding_rate": item.get("funding_rate") or 0,
                    })
                return prices
        except Exception as e:
            logger.error(f"[Paradex] get_latest_prices failed: {e}")
            return []
