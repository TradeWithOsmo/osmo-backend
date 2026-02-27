import httpx
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class ParadexAPIClient:
    def __init__(self):
        self.base_url = "https://api.prod.paradex.trade/v1"

    async def get_markets(self) -> List[Dict[str, Any]]:
        return await self.get_latest_prices() or []

    async def get_latest_prices(self) -> List[Dict[str, Any]]:
        """
        Fetch market summary from Paradex.
        GET /markets/summary — mark_price, volume_24h, open_interest, funding_rate,
                              price_change_24h_percent, high_24h, low_24h.
        GET /markets — max_leverage per market.
        """
        try:
            async with httpx.AsyncClient(verify=False, timeout=20) as client:
                # Fetch summary stats
                resp_sum = await client.get(f"{self.base_url}/markets/summary")
                resp_sum.raise_for_status()
                results_raw = resp_sum.json().get("results", [])

                # Fetch market configs for max_leverage
                resp_mkts = await client.get(f"{self.base_url}/markets")
                markets_cfg: Dict[str, Dict] = {}
                if resp_mkts.status_code == 200:
                    for m in (resp_mkts.json().get("results", []) or []):
                        markets_cfg[m.get("symbol", "")] = m

                prices = []
                for item in results_raw:
                    sym = item.get("symbol", "")
                    if not sym.endswith("-USD-PERP"):
                        continue
                    base = sym.replace("-USD-PERP", "").upper()
                    display = f"{base}-USD"
                    mark = float(item.get("mark_price") or item.get("last_traded_price") or 0)
                    change_pct = float(item.get("price_change_24h_percent") or 0)

                    # max_leverage from market config
                    cfg = markets_cfg.get(sym, {})
                    max_lev = int(cfg.get("max_leverage") or 20)

                    prices.append({
                        "symbol": display,
                        "from": base,
                        "to": "USD",
                        "price": mark,
                        "volume_24h": float(item.get("volume_24h") or 0),
                        "high_24h": float(item.get("high_24h") or 0),
                        "low_24h": float(item.get("low_24h") or 0),
                        "open_interest": float(item.get("open_interest") or 0),
                        "funding_rate": float(item.get("funding_rate") or 0),
                        "change_percent_24h": change_pct,
                        "change_24h": mark * change_pct / 100 if mark else 0,
                        "max_leverage": max_lev,
                        "source": "paradex",
                    })
                return prices
        except Exception as e:
            logger.error(f"[Paradex] get_latest_prices failed: {e}")
            return []
