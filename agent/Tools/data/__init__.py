"""
AI Agent Data Tools Exports

This module exports all data access functions for the AI Agent.
Usage:
    from backend.agent.Tools.data import market, analysis, web
    price = await market.get_price("BTC")
"""

from .market import (
    get_price,
    get_funding_rate,
    get_ticker_stats,
    get_chainlink_price,
    get_high_low_levels,
)

from .web import (
    search_news,
    search_sentiment,
    search_web_hybrid,
)

from .tradingview import (
    get_active_indicators
)

from .memory import (
    add_memory,
    search_memory,
    get_recent_history
)

from .trade import (
    get_positions,
    adjust_position_tpsl,
    adjust_all_positions_tpsl,
    close_position,
    close_all_positions,
    reverse_position,
    cancel_order,
)

from .research import (
    research_market,
    compare_markets,
    scan_market_overview,
    list_symbols,
)

__all__ = [
    # Market
    'get_price', 'get_funding_rate',
    'get_ticker_stats', 'get_chainlink_price', 'get_high_low_levels',
    # Web
    'search_news', 'search_sentiment', 'search_web_hybrid',
    # Frontend
    'get_active_indicators',
    # Trade actions
    'get_positions', 'adjust_position_tpsl', 'adjust_all_positions_tpsl',
    'close_position', 'close_all_positions', 'reverse_position', 'cancel_order',
    # Memory
    'add_memory', 'search_memory', 'get_recent_history',
    # Research
    'research_market', 'compare_markets', 'scan_market_overview', 'list_symbols',
]
