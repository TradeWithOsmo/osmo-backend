from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from ..Tools.data import (
    get_price,
    get_candles,
    get_orderbook,
    get_funding_rate,
    get_high_low_levels,
    get_technical_analysis,
    get_patterns,
    get_indicators,
    get_technical_summary,
    get_whale_activity,
    get_token_distribution,
    search_news,
    search_sentiment,
    get_ticker_stats,
    get_chainlink_price,
    get_active_indicators,
    adjust_position_tpsl,
    adjust_all_positions_tpsl,
    add_memory,
    search_memory,
    get_recent_history,
    search_knowledge_base,
)
from ..Tools.data.knowledge import (
    get_drawing_guidance,
    get_trade_management_guidance,
    get_market_context_guidance,
    consult_strategy,
)
from ..Tools.tradingview.actions import (
    add_indicator,
    set_timeframe,
    set_symbol,
    setup_trade,
    add_price_alert,
    mark_trading_session,
)
from ..Tools.tradingview.drawing.actions import (
    draw,
    update_drawing,
    clear_drawings,
    list_supported_draw_tools,
)
from ..Tools.tradingview.nav.actions import (
    focus_chart,
    ensure_mode,
    mouse_move,
    mouse_press,
    pan,
    zoom,
    press_key,
    reset_view,
    focus_latest,
    set_crosshair,
    move_crosshair,
    get_canvas,
    get_box,
    get_screenshot,
    get_photo_chart,
    hover_candle,
    inspect_cursor,
    capture_moment,
)

ToolFunc = Callable[..., Awaitable[Any]]


def get_tool_registry() -> Dict[str, ToolFunc]:
    return {
        # Data / market
        "get_price": get_price,
        "get_candles": get_candles,
        "get_orderbook": get_orderbook,
        "get_funding_rate": get_funding_rate,
        "get_high_low_levels": get_high_low_levels,
        "get_ticker_stats": get_ticker_stats,
        "get_chainlink_price": get_chainlink_price,

        # Data / analysis
        "get_technical_analysis": get_technical_analysis,
        "get_patterns": get_patterns,
        "get_indicators": get_indicators,
        "get_technical_summary": get_technical_summary,

        # Data / onchain + web
        "get_whale_activity": get_whale_activity,
        "get_token_distribution": get_token_distribution,
        "search_news": search_news,
        "search_sentiment": search_sentiment,

        # Data / chart context
        "get_active_indicators": get_active_indicators,
        "adjust_position_tpsl": adjust_position_tpsl,
        "adjust_all_positions_tpsl": adjust_all_positions_tpsl,

        # Memory + knowledge
        "add_memory": add_memory,
        "search_memory": search_memory,
        "get_recent_history": get_recent_history,
        "search_knowledge_base": search_knowledge_base,
        "get_drawing_guidance": get_drawing_guidance,
        "get_trade_management_guidance": get_trade_management_guidance,
        "get_market_context_guidance": get_market_context_guidance,
        "consult_strategy": consult_strategy,

        # TradingView / core actions
        "add_indicator": add_indicator,
        "set_timeframe": set_timeframe,
        "set_symbol": set_symbol,
        "setup_trade": setup_trade,
        "add_price_alert": add_price_alert,
        "mark_trading_session": mark_trading_session,

        # TradingView / drawing actions
        "draw": draw,
        "update_drawing": update_drawing,
        "clear_drawings": clear_drawings,
        "list_supported_draw_tools": list_supported_draw_tools,

        # TradingView / nav actions
        "focus_chart": focus_chart,
        "ensure_mode": ensure_mode,
        "mouse_move": mouse_move,
        "mouse_press": mouse_press,
        "pan": pan,
        "zoom": zoom,
        "press_key": press_key,
        "reset_view": reset_view,
        "focus_latest": focus_latest,
        "set_crosshair": set_crosshair,
        "move_crosshair": move_crosshair,
        "get_canvas": get_canvas,
        "get_box": get_box,
        "get_screenshot": get_screenshot,
        "get_photo_chart": get_photo_chart,
        "hover_candle": hover_candle,
        "inspect_cursor": inspect_cursor,
        "capture_moment": capture_moment,
    }
