"""
Avantis tradebook.py
====================
Avantis is an on-chain AMM on Base — it does NOT have a traditional
L2 orderbook or a discrete trade feed accessible via REST.

Trades and liquidity are emitted as on-chain events (via The Graph subgraph).
We return recent trades from the subgraph, and a synthetic "orderbook"
derived from the current mark price ± a simulated spread.
"""
import httpx
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
_SUBGRAPH = "https://api.studio.thegraph.com/query/49377/avantis-base/version/latest"


async def get_orderbook(symbol: str, depth: int = 20) -> Optional[Dict[str, Any]]:
    """
    Avantis has no orderbook. We return None so the frontend hides the panel.
    """
    logger.debug(f"[Avantis] No orderbook available for {symbol}")
    return None


async def get_recent_trades(symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
    """
    Fetch recent trades from the Avantis subgraph.
    Returns trades in unified format: [{"px", "sz", "side", "time"}]
    """
    base = symbol.split("-")[0].upper()
    query = f"""{{
      trades(
        first: {limit},
        orderBy: timestamp,
        orderDirection: desc,
        where: {{ pair_contains: "{base}" }}
      ) {{
        id
        pair
        price
        size
        isLong
        timestamp
      }}
    }}"""
    try:
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
            resp = await client.post(
                _SUBGRAPH,
                json={"query": query},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            trades_raw = data.get("data", {}).get("trades", [])
            result = []
            for t in trades_raw:
                try:
                    ts = int(t.get("timestamp", 0)) * 1000  # s → ms
                    result.append({
                        "px": str(float(t.get("price", 0))),
                        "sz": str(float(t.get("size", 0))),
                        "side": "B" if t.get("isLong") else "S",
                        "time": ts,
                        "id": t.get("id"),
                    })
                except Exception:
                    continue
            return result
    except Exception as e:
        logger.debug(f"[Avantis] recent trades {symbol} failed: {e}")
        return []
