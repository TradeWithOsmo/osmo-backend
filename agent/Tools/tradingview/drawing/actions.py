"""
Unified TradingView Drawing Tool
Allows the agent to draw ANY supported shape using a single interface.
"""

import httpx
from typing import Dict, Any, List, Optional, Union
from backend.agent.Config.tools_config import DATA_SOURCES

CONNECTORS_API = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")

async def _send_command(symbol: str, action: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    url = f"{CONNECTORS_API}/tradingview/commands"
    command = {
        "symbol": symbol,
        "action": action,
        "params": params or {}
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=command)
            resp.raise_for_status()
            return {"status": "success", "info": f"Drawing '{action}' sent to {symbol}."}
        except Exception as e:
            return {"error": f"Failed to send command: {str(e)}"}

async def draw(symbol: str, 
               tool: str, 
               points: List[Dict[str, Any]], 
               style: Dict[str, Any] = None, 
               text: str = None,
               id: str = None) -> Dict[str, Any]:
    """
    Draw a shape on the chart.
    
    Args:
        symbol: Ticker symbol (e.g., "BTC").
        tool: Tool name from cheatsheet (e.g., 'trend_line', 'fib_retracement').
        points: List of coordinates. 
        style: Optional style overrides.
        text: Optional text content.
        id: Optional Custom ID (tag) to track this drawing for future updates (e.g., "trailing_sl").
    """
    params = {
        "type": tool,
        "points": points,
        "style": style or {}
    }
    if text:
        params["text"] = text
    if id:
        params["id"] = id

    return await _send_command(symbol, "draw_shape", params)

async def update_drawing(symbol: str, 
                        id: str, 
                        points: List[Dict[str, Any]] = None, 
                        style: Dict[str, Any] = None, 
                        text: str = None) -> Dict[str, Any]:
    """
    Modify an existing drawing by its Custom ID.
    """
    params = {
        "id": id
    }
    if points:
        params["points"] = points
    if style:
        params["style"] = style
    if text:
        params["text"] = text
        
    return await _send_command(symbol, "update_drawing", params)

async def clear_drawings(symbol: str) -> Dict[str, Any]:
    return await _send_command(symbol, "clear_drawings")
