"""
Analytics Tool (On-Chain / Dune)

Wraps Dune Analytics connector for whale tracking and on-chain data.
"""

import httpx
from typing import Dict, Any
from backend.agent.Config.tools_config import DATA_SOURCES

CONNECTORS_API = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")

async def get_whale_activity(symbol: str, min_size_usd: int = 100000) -> Dict[str, Any]:
    """
    Get recent whale trades for a token.
    Uses Dune Analytics via backend connector.
    """
    url = f"{CONNECTORS_API}/dune/whale_trades/{symbol}"
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params={"min_size_usd": min_size_usd})
            # Handle 500/404 specifically
            if resp.status_code == 404:
                return {"error": "Dune connector not active"}
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": f"Failed to fetch whale data: {str(e)}"}

async def get_token_distribution(symbol: str) -> Dict[str, Any]:
    """
    Get token holder distribution.
    """
    return {"error": "Not implemented"}
