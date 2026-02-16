from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from ..Tools.data import (
    get_positions,
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
    close_position,
    close_all_positions,
    reverse_position,
    cancel_order,
    add_memory,
    search_memory,
    get_recent_history,
    search_knowledge_base,
    research_market,
    compare_markets,
    scan_market_overview,
)
from ..Tools.trade_execution import place_order
from ..Tools.data.knowledge import (
    get_drawing_guidance,
    get_trade_management_guidance,
    get_market_context_guidance,
    consult_strategy,
)
from ..Tools.tradingview.actions import (
    list_supported_indicator_aliases,
    add_indicator,
    remove_indicator,
    clear_indicators,
    verify_indicator_present,
    set_timeframe,
    set_symbol,
    setup_trade,
    add_price_alert,
    mark_trading_session,
)
from ..Tools.tradingview.verify import verify_tradingview_state
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
        "get_positions": get_positions,
        "adjust_position_tpsl": adjust_position_tpsl,
        "adjust_all_positions_tpsl": adjust_all_positions_tpsl,
        "close_position": close_position,
        "close_all_positions": close_all_positions,
        "reverse_position": reverse_position,
        "cancel_order": cancel_order,

        # Memory + knowledge
        "add_memory": add_memory,
        "search_memory": search_memory,
        "get_recent_history": get_recent_history,
        "search_knowledge_base": search_knowledge_base,
        "get_drawing_guidance": get_drawing_guidance,
        "get_trade_management_guidance": get_trade_management_guidance,
        "get_market_context_guidance": get_market_context_guidance,
        "consult_strategy": consult_strategy,

        # Research (multi-market)
        "research_market": research_market,
        "compare_markets": compare_markets,
        "scan_market_overview": scan_market_overview,

        # TradingView / core actions
        "list_supported_indicator_aliases": list_supported_indicator_aliases,
        "add_indicator": add_indicator,
        "remove_indicator": remove_indicator,
        "clear_indicators": clear_indicators,
        "verify_indicator_present": verify_indicator_present,
        "verify_tradingview_state": verify_tradingview_state,
        "set_timeframe": set_timeframe,
        "set_symbol": set_symbol,
        # setup_trade supports gp/gl aliases and validation/invalidation aliases.
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
        "place_order": place_order,
    }
