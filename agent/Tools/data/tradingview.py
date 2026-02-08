"""
TradingView Frontend Tool

Allows the agent to 'see' what indicators the user has on their chart.
"""

import httpx
from typing import Dict, Any, List
try:
    from agent.Config.tools_config import DATA_SOURCES
except Exception:
    from backend.agent.Config.tools_config import DATA_SOURCES

CONNECTORS_API = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")

async def get_active_indicators(symbol: str, timeframe: str = "1D") -> Dict[str, Any]:
    """
    Get indicators currently active on the user's frontend chart.
    These are pushed by the frontend to Redis.
    """
    url = f"{CONNECTORS_API}/tradingview/indicators"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params={"symbol": symbol, "timeframe": timeframe})
            if resp.status_code == 404:
                return {"info": "No active indicators found for this symbol/timeframe."}
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": f"Failed to fetch TradingView data: {str(e)}"}
