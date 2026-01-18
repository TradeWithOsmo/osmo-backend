"""
Market Data Access Tool

Aggregates data from Hyperliquid (Crypto), Ostium (RWA), and Chainlink (Oracle).
"""

import httpx
from typing import Dict, Any, List, Optional
from backend.agent.Config.tools_config import DATA_SOURCES

# Base URL for connectors API
CONNECTORS_API = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")

async def get_price(symbol: str, asset_type: str = "crypto") -> Dict[str, Any]:
    """
    Get current price for a symbol.
    
    Args:
        symbol: e.g. "BTC", "EURUSD"
        asset_type: "crypto" (Hyperliquid) or "rwa" (Ostium)
    """
    url = f"{CONNECTORS_API}/price/{symbol}"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params={"asset_type": asset_type})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": f"Failed to fetch price: {str(e)}"}

async def get_candles(symbol: str, timeframe: str = "1H", limit: int = 100) -> List[Dict]:
    """
    Get OHLCV candles.
    Note: Currently routed via analysis endpoint for raw data
    """
    # Using technical analysis endpoint to get raw candles as side effect
    # Or implement direct candle route in connectors if preferred.
    # For now, we reuse the analysis fetcher which grabs candles.
    url = f"http://localhost:8000/api/analysis/technical/{symbol}"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params={"timeframe": timeframe})
            data = resp.json()
            # This endpoint returns analysis results, need pure candles?
            # Ideally connectors should have direct candles endpoint.
            # Fallback: Return error asking to use analysis tool for now
            return {"error": "Use get_technical_analysis for candle data context"}
        except Exception as e:
            return {"error": str(e)}

async def get_orderbook(symbol: str) -> Dict[str, Any]:
    """
    Get L2 Orderbook (Crypto/Hyperliquid only).
    """
    # Direct fetch from Hyperliquid connector via manager (not exposed in API yet?)
    # TODO: Expose orderbook in api_routes.py if needed.
    # For now, return placeholder or implement direct connector call if allowed.
    return {"error": "Orderbook API not yet exposed in backend/connectors/api_routes.py"}

async def get_funding_rate(symbol: str) -> Dict[str, Any]:
    """
    Get Funding Rate (Crypto/Hyperliquid only).
    """
    # Similar to orderbook, needs API exposure
    return {"error": "Funding Rate API not yet exposed"}

async def get_ticker_stats(symbol: str) -> Dict[str, Any]:
    """
    Get 24h Stats (Volume, Change).
    """
    # Ostium returns this in get_price response (volume_24h).
    # Hyperliquid price response also has data.
    price_data = await get_price(symbol)
    if "error" in price_data: return price_data
    
    data = price_data.get("data", {})
    return {
        "volume_24h": data.get("volume_24h", 0),
        "change_24h": data.get("change_24h", 0),
        "price": data.get("price")
    }

async def get_chainlink_price(symbol: str) -> Dict[str, Any]:
    """
    Get Verified Oracle Price via Chainlink.
    """
    # Chainlink is integrated as a connector.
    # Need to check how to route specific connector in get_price
    # Current implementation of get_price routers by asset_type.
    # TODO: Add specific route for chainlink in api_routes.
    return {"error": "Chainlink direct access not exposed in API"}
