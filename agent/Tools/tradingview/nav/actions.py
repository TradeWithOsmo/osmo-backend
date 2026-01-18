"""
TradingView Navigation Tools

Allows the agent to control chart navigation (Pan, Zoom, Reset) and inputs.
"""

import httpx
from typing import Dict, Any, List, Optional
from backend.agent.Config.tools_config import DATA_SOURCES

CONNECTORS_API = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")

async def _send_command(symbol: str, action: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    """Helper to send command to connector"""
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
            return {"status": "success", "info": f"Command '{action}' sent to {symbol}."}
        except Exception as e:
            return {"error": f"Failed to send command: {str(e)}"}

# === FOCUS & BASE STATE ===

async def focus_chart(symbol: str) -> Dict[str, Any]:
    """Focus the chart canvas to ensure it receives input."""
    return await _send_command(symbol, "focus_chart")

async def ensure_mode(symbol: str, mode: str = "nav") -> Dict[str, Any]:
    """Ensure specific mode (e.g., 'nav' ensuring no drawing tool is active)."""
    return await _send_command(symbol, "ensure_mode", {"mode": mode})

# === MOUSE CONTROL ===

async def mouse_move(symbol: str, x: int, y: int, relative: bool = False) -> Dict[str, Any]:
    """Simulate mouse movement."""
    return await _send_command(symbol, "mouse_move", {"x": x, "y": y, "relative": relative})

async def mouse_press(symbol: str, state: str = "down") -> Dict[str, Any]:
    """Simulate mouse press ('down', 'up', 'click')."""
    return await _send_command(symbol, "mouse_press", {"state": state})

# === PAN NAVIGATION ===

async def pan(symbol: str, axis: str, direction: str, amount: str = "medium") -> Dict[str, Any]:
    """
    Pan the chart.
    Args:
        axis: "time" or "price"
        direction: "left", "right", "up", "down"
        amount: "small", "medium", "large" or specific number
    """
    return await _send_command(symbol, "pan", {
        "axis": axis,
        "direction": direction,
        "amount": amount
    })

# === ZOOM NAVIGATION ===

async def zoom(symbol: str, mode: str, amount: Any = None) -> Dict[str, Any]:
    """
    Zoom the chart.
    Args:
        mode: "in", "out", "auto", "fit", "range"
        amount: For in/out: "small", "medium", "percent". For range: number of candles.
    """
    return await _send_command(symbol, "zoom", {
        "mode": mode,
        "amount": amount
    })

# === KEYBOARD NAVIGATION ===

async def press_key(symbol: str, key: str) -> Dict[str, Any]:
    """Simulate a key press (e.g., 'Esc', 'ArrowLeft')."""
    return await _send_command(symbol, "press_key", {"key": key})

# === RESET & POSITIONING ===

async def reset_view(symbol: str) -> Dict[str, Any]:
    """Reset chart to default view."""
    return await _send_command(symbol, "reset_view")

async def focus_latest(symbol: str) -> Dict[str, Any]:
    """Jump to the latest candle."""
    return await _send_command(symbol, "focus_latest")

# === CROSSHAIR NAVIGATION ===

async def set_crosshair(symbol: str, active: bool) -> Dict[str, Any]:
    """Enable or disable crosshair."""
    return await _send_command(symbol, "set_crosshair", {"active": active})

async def move_crosshair(symbol: str, axis: str, direction: str, amount: str = "medium") -> Dict[str, Any]:
    """Move crosshair specifically."""
    return await _send_command(symbol, "move_crosshair", {
        "axis": axis,
        "direction": direction,
        "amount": amount
    })


# === CANVAS ACCESS ===

async def get_canvas(symbol: str) -> Dict[str, Any]:
    """Get chart canvas details (selector)."""
    return await _send_command(symbol, "get_canvas", {"selector": "#tv_chart_container canvas"})

async def get_box(symbol: str) -> Dict[str, Any]:
    """Get canvas bounding box (coordinates)."""
    return await _send_command(symbol, "get_box", {"selector": "#tv_chart_container canvas"})

async def get_screenshot(symbol: str) -> Dict[str, Any]:
    """Get a screenshot of the chart canvas."""
    return await _send_command(symbol, "get_screenshot", {"target": "canvas"})

# === ADVANCED INTERACTION ===

async def hover_candle(symbol: str, from_right: int, price_level: Optional[float] = None) -> Dict[str, Any]:
    """
    Hover over a specific candle (calculated by index from right).
    Args:
        from_right: Index of candle from right (0 = latest).
        price_level: Price level to hover (y-axis). If None, uses center of candle.
    """
    return await _send_command(symbol, "hover_candle", {
        "x_from_right": from_right,
        "y_price": price_level
    })

async def inspect_cursor(symbol: str) -> Dict[str, Any]:
    """
    Get detailed data at the current cursor (crosshair) position.
    Returns OHLC, Indicator values, and Coordinate info.
    """
    return await _send_command(symbol, "inspect_cursor")

async def capture_moment(symbol: str, caption: str = "snapshot") -> Dict[str, Any]:
    """
    Capture a screenshot (visual) and data snapshot (technical) of the current chart state.
    Use this to save trade setups or anomalies.
    """
    return await _send_command(symbol, "capture_moment", {"caption": caption})

