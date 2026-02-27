import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class AevoAPIClient:
    def __init__(self):
        self.base_url = "https://api.aevo.xyz"

    async def get_markets(self) -> List[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(verify=False) as client:
                resp = await client.get(f"{self.base_url}/markets", timeout=20)
                resp.raise_for_status()
                markets = []
                for p in resp.json():
                    if isinstance(p, dict) and p.get("instrument_type") == "PERPETUAL":
                        base = p.get("underlying_asset", "").upper()
                        markets.append({
                            "symbol": f"{base}-USD",
                            "from": base,
                            "to": "USD",
                        })
                return markets
        except Exception as e:
            logger.error(f"[Aevo] get_markets failed: {e}")
            return []

    async def get_latest_prices(self) -> List[Dict[str, Any]]:
        """Fetch live tickers from Aevo's statistics endpoint."""
        try:
            async with httpx.AsyncClient(verify=False) as client:
                # Use the markets endpoint — it returns instruments including tickers
                resp = await client.get(f"{self.base_url}/statistics", timeout=20)
                resp.raise_for_status()
                prices = []
                data = resp.json()
                perps = data if isinstance(data, list) else data.get("data", [])
                for item in perps:
                    if not isinstance(item, dict):
                        continue
                    instr = item.get("instrument_name", "")
                    if not instr.endswith("-PERP"):
                        continue
                    base = instr.replace("-PERP", "").upper()
                    symbol = f"{base}-USD"
                    prices.append({
                        "symbol": symbol,
                        "instrument_name": instr,
                        "underlying_asset": base,
                        "price": item.get("mark_price") or item.get("index_price") or 0,
                        "volume": item.get("volume") or 0,
                        "open_interest": item.get("open_interest") or 0,
                        "funding_rate": item.get("funding_rate") or 0,
                    })
                return prices
        except Exception as e:
            logger.error(f"[Aevo] get_latest_prices failed: {e}")
            return []
