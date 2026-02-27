import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class AevoAPIClient:
    def __init__(self):
        self.base_url = "https://api.aevo.xyz"

    async def get_markets(self) -> List[Dict[str, Any]]:
        return await self.get_latest_prices() or []

    async def get_latest_prices(self) -> List[Dict[str, Any]]:
        """
        Fetch live statistics from Aevo.
        GET /statistics returns perpetual instruments with 24h stats.
        """
        try:
            async with httpx.AsyncClient(verify=False, timeout=20) as client:
                resp = await client.get(f"{self.base_url}/statistics")
                resp.raise_for_status()
                data = resp.json()
                perps = data if isinstance(data, list) else data.get("data", [])
                prices = []
                for item in perps:
                    if not isinstance(item, dict):
                        continue
                    instr = item.get("instrument_name", "")
                    if not instr.endswith("-PERP"):
                        continue
                    base = instr.replace("-PERP", "").upper()
                    symbol = f"{base}-USD"
                    mark = float(item.get("mark_price") or item.get("index_price") or 0)
                    change_pct = float(item.get("change_24h") or 0)  # Aevo uses "change_24h" as percent
                    prices.append({
                        "symbol": symbol,
                        "from": base,
                        "to": "USD",
                        "instrument_name": instr,
                        "price": mark,
                        "volume_24h": float(item.get("volume") or item.get("volume_24h") or 0),
                        "high_24h": float(item.get("high") or item.get("high_24h") or 0),
                        "low_24h": float(item.get("low") or item.get("low_24h") or 0),
                        "open_interest": float(item.get("open_interest") or 0),
                        "funding_rate": float(item.get("funding_rate") or 0),
                        "change_percent_24h": change_pct,
                        "change_24h": mark * change_pct / 100 if mark else 0,
                        "source": "aevo",
                    })
                return prices
        except Exception as e:
            logger.error(f"[Aevo] get_latest_prices failed: {e}")
            return []
