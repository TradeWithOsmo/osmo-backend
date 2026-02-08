from __future__ import annotations

from typing import Set

WRITE_TOOL_NAMES: Set[str] = {
    "set_symbol",
    "set_timeframe",
    "add_indicator",
    "draw",
    "update_drawing",
    "clear_drawings",
    "setup_trade",
    "add_price_alert",
    "mark_trading_session",
}

NAV_TOOL_NAMES: Set[str] = {
    "focus_chart",
    "ensure_mode",
    "mouse_move",
    "mouse_press",
    "pan",
    "zoom",
    "press_key",
    "reset_view",
    "focus_latest",
    "set_crosshair",
    "move_crosshair",
    "get_canvas",
    "get_box",
    "get_screenshot",
    "get_photo_chart",
    "hover_candle",
    "inspect_cursor",
    "capture_moment",
}


def classify_tool_mode(tool_name: str) -> str:
    name = str(tool_name or "").strip()
    if name in WRITE_TOOL_NAMES:
        return "write"
    if name in NAV_TOOL_NAMES:
        return "nav"
    return "read"
