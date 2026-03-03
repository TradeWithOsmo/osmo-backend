"""
AI Agent Data Tools Exports

This module exports all data access functions for the AI Agent.
Usage:
    from backend.agent.Tools.data import market, analysis, web
    price = await market.get_price("BTC")
"""

from .market import (
    get_price,
    get_orderbook,
    get_funding_rate, 
    get_ticker_stats,
    get_chainlink_price,
    get_high_low_levels,
)

from .analysis import (
    get_technical_analysis,
    get_patterns,
    get_indicators,
    get_technical_summary
)

from .analytics import (
    get_whale_activity,
    get_token_distribution
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

from .knowledge import (
    search_knowledge_base
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
)

__all__ = [
    # Market
    'get_price', 'get_orderbook', 'get_funding_rate',
    'get_ticker_stats', 'get_chainlink_price', 'get_high_low_levels',
    # Analysis
    'get_technical_analysis', 'get_patterns', 'get_indicators', 'get_technical_summary',
    # Analytics
    'get_whale_activity', 'get_token_distribution',
    # Web
    'search_news', 'search_sentiment', 'search_web_hybrid',
    # Frontend
    'get_active_indicators',
    # Trade actions
    'get_positions', 'adjust_position_tpsl', 'adjust_all_positions_tpsl',
    'close_position', 'close_all_positions', 'reverse_position', 'cancel_order',
    # Memory
    'add_memory', 'search_memory', 'get_recent_history',
    # Knowledge
    'search_knowledge_base',
    # Research
    'research_market', 'compare_markets', 'scan_market_overview',
]
