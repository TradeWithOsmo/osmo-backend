import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class OrderlyAPIClient:
    def __init__(self):
        self.base_url = "https://api-evm.orderly.org/v1"

    async def get_markets(self) -> List[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(verify=False) as client:
                resp = await client.get(f"{self.base_url}/public/info", timeout=20)
                resp.raise_for_status()
                rows = resp.json().get("data", {}).get("rows", [])
                markets = []
                for p in rows:
                    sym = p.get("symbol", "")
                    if sym.startswith("PERP_") and sym.endswith("_USDC"):
                        base = sym.replace("PERP_", "").replace("_USDC", "").upper()
                        markets.append({
                            "symbol": f"{base}-USD",
                            "from": base,
                            "to": "USD",
                        })
                return markets
        except Exception as e:
            logger.error(f"[Orderly] get_markets failed: {e}")
            return []

    async def get_latest_prices(self) -> List[Dict[str, Any]]:
        """Fetch live tickers/prices from Orderly's market summary endpoint."""
        try:
            async with httpx.AsyncClient(verify=False) as client:
                resp = await client.get(f"{self.base_url}/public/futures", timeout=20)
                resp.raise_for_status()
                rows = resp.json().get("data", {}).get("rows", [])
                prices = []
                for row in rows:
                    sym = row.get("symbol", "")
                    if not sym.startswith("PERP_"):
                        continue
                    base = sym.replace("PERP_", "").replace("_USDC", "").upper()
                    display = f"{base}-USD"
                    prices.append({
                        "symbol": display,
                        "price": row.get("mark_price") or row.get("index_price") or 0,
                        "volume_24h": row.get("volume_24h") or 0,
                        "open_interest": row.get("open_interest") or 0,
                        "est_funding_rate": row.get("est_funding_rate") or 0,
                    })
                return prices
        except Exception as e:
            logger.error(f"[Orderly] get_latest_prices failed: {e}")
            return []
