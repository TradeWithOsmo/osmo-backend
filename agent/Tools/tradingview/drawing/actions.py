"""
Unified TradingView Drawing Tool
Allows the agent to draw ANY supported shape using a single interface.
"""

from typing import Dict, Any, List, Optional
from ..command_client import send_tradingview_command

TOOL_ALIAS_MAP: Dict[str, str] = {
    "line": "trend_line",
    "trend_line": "trend_line",
    "arrow": "arrow",
    "arrow_up": "arrow_up",
    "arrow_down": "arrow_down",
    "ray": "ray",
    "extended": "extended",
    "horizontal_line": "horizontal_line",
    "hline": "horizontal_line",
    "support": "horizontal_line",
    "resistance": "horizontal_line",
    "vertical_line": "vertical_line",
    "vline": "vertical_line",
    "parallel_channel": "parallel_channel",
    "fib_retracement": "fib_retracement",
    "fib_trend_ext": "fib_trend_ext",
    "pitchfork": "pitchfork",
    "gann_box": "gann_box",
    "head_and_shoulders": "head_and_shoulders",
    "triangle_pattern": "triangle_pattern",
    "elliott_impulse_wave": "elliott_impulse_wave",
    "long_position": "long_position",
    "short_position": "short_position",
    "price_range": "price_range",
    "date_range": "date_range",
    "prediction": "prediction",
    "rect": "rectangle",
    "rectangle": "rectangle",
    "circle": "circle",
    "ellipse": "ellipse",
    "text": "text",
    "icon": "icon",
    "callout": "balloon",
    "balloon": "balloon",
    "note": "note",
}


def _normalize_tool_name(tool: str) -> str:
    raw = str(tool or "").strip()
    if not raw:
        return raw
    key = raw.lower().replace(" ", "_").replace("-", "_")
    return TOOL_ALIAS_MAP.get(key, key)


def _normalize_points(points: List[Dict[str, Any]], tool: str = None) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    tool_normalized = _normalize_tool_name(tool) if tool else ""
    
    for pt in (points or []):
        if not isinstance(pt, dict):
            continue
        time_value = pt.get("time", pt.get("timestamp", pt.get("ts", pt.get("x"))))
        price_value = pt.get("price", pt.get("y"))
        
        # For horizontal_line, only price is required (time optional)
        if tool_normalized == "horizontal_line":
            if price_value is None:
                continue
            try:
                parsed_time = 0
                if time_value is not None:
                    parsed_time = float(time_value)
                    if parsed_time > 1_000_000_000_000:
                        parsed_time = parsed_time / 1000.0
                normalized.append({"time": int(parsed_time), "price": float(price_value)})
            except (TypeError, ValueError):
                continue
                
        # For vertical_line, only time is required (price optional)
        elif tool_normalized == "vertical_line":
            if time_value is None:
                continue
            try:
                parsed_time = float(time_value)
                if parsed_time > 1_000_000_000_000:
                    parsed_time = parsed_time / 1000.0
                normalized.append({"time": int(parsed_time), "price": 0})
            except (TypeError, ValueError):
                continue
                
        # Default: both time and price required
        else:
            if time_value is None or price_value is None:
                continue
            try:
                parsed_time = float(time_value)
                if parsed_time > 1_000_000_000_000:
                    parsed_time = parsed_time / 1000.0
                normalized.append({"time": int(parsed_time), "price": float(price_value)})
            except (TypeError, ValueError):
                continue
                
    return normalized


async def _send_command(symbol: str, action: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    return await send_tradingview_command(
        symbol=symbol,
        action=action,
        params=params or {},
        mode="write",
        expected_state={"symbol": symbol},
    )

async def list_supported_draw_tools() -> Dict[str, Any]:
    return {
        "status": "ok",
        "count": len(set(TOOL_ALIAS_MAP.values())),
        "tools": sorted(set(TOOL_ALIAS_MAP.values())),
        "aliases": sorted(TOOL_ALIAS_MAP.keys()),
    }


async def draw(
    symbol: str,
    tool: str,
    points: List[Dict[str, Any]],
    style: Dict[str, Any] = None,
    text: str = None,
    id: str = None,
    write_txn_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Draw a shape on the chart.
    
    Args:
        symbol: Ticker symbol (e.g., "BTC").
        tool: Tool name from cheatsheet (e.g., 'trend_line', 'fib_retracement', 'horizontal_line').
        points: List of coordinates. 
            - For most tools: [{"time": 1234567890, "price": 50000}]
            - For horizontal_line: [{"price": 50000}] (time optional)
            - For vertical_line: [{"time": 1234567890}] (price optional)
        style: Optional style overrides.
        text: Optional text content.
        id: Optional Custom ID (tag) to track this drawing for future updates (e.g., "trailing_sl").
    
    Examples:
        # Draw horizontal support line
        draw(symbol="BTC", tool="horizontal_line", points=[{"price": 67460}], id="support")
        
        # Draw horizontal resistance line  
        draw(symbol="BTC", tool="horizontal_line", points=[{"price": 68225}], id="resistance")
        
        # Draw trend line
        draw(symbol="BTC", tool="trend_line", points=[
            {"time": 1704067200, "price": 42000},
            {"time": 1704153600, "price": 43000}
        ])
    """
    normalized_tool = _normalize_tool_name(tool)
    normalized_points = _normalize_points(points, tool=tool)

    params = {
        "type": normalized_tool,
        "points": normalized_points,
        "style": style or {},
    }
    if text:
        params["text"] = text
    if id:
        params["id"] = id
    if write_txn_id:
        params["write_txn_id"] = write_txn_id

    expected_state: Dict[str, Any] = {"symbol": symbol}
    if id:
        expected_state["drawing_id"] = id
    return await send_tradingview_command(
        symbol=symbol,
        action="draw_shape",
        params=params,
        mode="write",
        expected_state=expected_state,
    )

async def update_drawing(
    symbol: str,
    id: str,
    points: List[Dict[str, Any]] = None,
    style: Dict[str, Any] = None,
    text: str = None,
    write_txn_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Modify an existing drawing by its Custom ID.
    """
    params = {
        "id": id
    }
    if points:
        params["points"] = _normalize_points(points, tool=None)
    if style:
        params["style"] = style
    if text:
        params["text"] = text
    if write_txn_id:
        params["write_txn_id"] = write_txn_id
        
    return await send_tradingview_command(
        symbol=symbol,
        action="update_drawing",
        params=params,
        mode="write",
        expected_state={"symbol": symbol, "drawing_id": id},
    )

async def clear_drawings(symbol: str, write_txn_id: Optional[str] = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    if write_txn_id:
        params["write_txn_id"] = write_txn_id
    return await send_tradingview_command(
        symbol=symbol,
        action="clear_drawings",
        params=params,
        mode="write",
        expected_state={"symbol": symbol, "drawings_cleared": True},
    )
