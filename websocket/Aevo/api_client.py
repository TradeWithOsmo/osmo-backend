import httpx
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class AevoAPIClient:
    def __init__(self):
        self.base_url = "https://api.aevo.xyz"

    async def get_markets(self) -> List[Dict[str, Any]]:
        return await self.get_latest_prices() or []

    async def get_latest_prices(self) -> List[Dict[str, Any]]:
        """
        Fetch live per-market data from Aevo.
        New API shape (2026): /markets returns per-instrument market snapshot.
        """
        try:
            async with httpx.AsyncClient(verify=False, timeout=20) as client:
                resp = await client.get(f"{self.base_url}/markets")
                resp.raise_for_status()
                markets = resp.json()
                perps = markets if isinstance(markets, list) else markets.get("markets", [])
                prices = []
                for item in perps:
                    if not isinstance(item, dict):
                        continue
                    instr = item.get("instrument_name", "")
                    if not instr.endswith("-PERP"):
                        continue
                    base = (item.get("underlying_asset") or instr.replace("-PERP", "")).upper()
                    quote = (item.get("quote_asset") or "USD").upper()
                    symbol = f"{base}-{quote}"
                    mark = float(item.get("mark_price") or item.get("index_price") or item.get("price") or 0)
                    change_pct = float(item.get("price_change_percent_24h") or item.get("change_percent_24h") or item.get("change_24h") or 0)
                    max_lev = int(float(item.get("max_leverage") or 20))

                    prices.append({
                        "symbol": symbol,
                        "from": base,
                        "to": quote,
                        "instrument_name": instr,
                        "price": mark,
                        "volume_24h": float(item.get("volume_24h") or item.get("volume") or 0),
                        "high_24h": float(item.get("high_24h") or item.get("high") or 0),
                        "low_24h": float(item.get("low_24h") or item.get("low") or 0),
                        "open_interest": float(item.get("open_interest") or 0),
                        "funding_rate": float(item.get("funding_rate") or 0),
                        "change_percent_24h": change_pct,
                        "change_24h": mark * change_pct / 100 if mark else 0,
                        "max_leverage": max_lev,
                        "source": "aevo",
                    })
                return prices
        except Exception as e:
            logger.error(f"[Aevo] get_latest_prices failed: {e}")
            return []
