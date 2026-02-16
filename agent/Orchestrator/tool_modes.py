from __future__ import annotations

from typing import Set

CHART_WRITE_TOOL_NAMES: Set[str] = {
    "set_symbol",
    "set_timeframe",
    "add_indicator",
    "remove_indicator",
    "clear_indicators",
    "draw",
    "update_drawing",
    "clear_drawings",
    "setup_trade",
    "add_price_alert",
    "mark_trading_session",
}

EXECUTION_WRITE_TOOL_NAMES: Set[str] = {
    # Order execution + portfolio mutations (side-effects)
    "place_order",
    "adjust_position_tpsl",
    "adjust_all_positions_tpsl",
    "close_position",
    "close_all_positions",
    "reverse_position",
    "cancel_order",
}

WRITE_TOOL_NAMES: Set[str] = set(CHART_WRITE_TOOL_NAMES) | set(EXECUTION_WRITE_TOOL_NAMES)

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

DECISION_TOOL_NAMES: Set[str] = {
    "setup_trade",
    "place_order",
}


def classify_tool_mode(tool_name: str) -> str:
    name = str(tool_name or "").strip()
    if name in WRITE_TOOL_NAMES:
        return "write"
    if name in NAV_TOOL_NAMES:
        return "nav"
    return "read"
