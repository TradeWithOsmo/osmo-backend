import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class OrderlyAPIClient:
    def __init__(self):
        self.base_url = "https://api-evm.orderly.org/v1"

    async def get_markets(self) -> List[Dict[str, Any]]:
        return await self.get_latest_prices() or []

    async def get_latest_prices(self) -> List[Dict[str, Any]]:
        """
        Fetch live futures data from Orderly.
        GET /public/futures returns: symbol, index_price, mark_price, volume_24h,
        open_interest, est_funding_rate, last_funding_rate, change_24h, change_percent_24h, high_24h, low_24h
        """
        try:
            async with httpx.AsyncClient(verify=False, timeout=20) as client:
                resp = await client.get(f"{self.base_url}/public/futures")
                resp.raise_for_status()
                rows = resp.json().get("data", {}).get("rows", [])
                prices = []
                for row in rows:
                    sym = row.get("symbol", "")
                    if not sym.startswith("PERP_"):
                        continue
                    base = sym.replace("PERP_", "").replace("_USDC", "").upper()
                    display = f"{base}-USD"
                    mark = float(row.get("mark_price") or row.get("index_price") or 0)
                    open_p = float(row.get("open_24h") or mark)
                    close_p = float(row.get("close_24h") or mark)
                    change_24h = close_p - open_p
                    change_pct = (change_24h / open_p * 100) if open_p else 0.0
                    prices.append({
                        "symbol": display,
                        "from": base,
                        "to": "USD",
                        "price": mark,
                        "volume_24h": float(row.get("volume_24h") or 0),
                        "high_24h": float(row.get("high_24h") or 0),
                        "low_24h": float(row.get("low_24h") or 0),
                        "open_interest": float(row.get("open_interest") or 0),
                        "funding_rate": float(row.get("est_funding_rate") or row.get("last_funding_rate") or 0),
                        "change_24h": change_24h,
                        "change_percent_24h": change_pct,
                        "source": "orderly",
                    })
                return prices
        except Exception as e:
            logger.error(f"[Orderly] get_latest_prices failed: {e}")
            return []
