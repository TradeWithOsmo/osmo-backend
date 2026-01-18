"""
AI Agent Data Tools Exports

This module exports all data access functions for the AI Agent.
Usage:
    from backend.agent.Tools.data import market, analysis, web
    price = await market.get_price("BTC")
"""

from .market import (
    get_price, 
    get_candles, 
    get_orderbook, 
    get_funding_rate, 
    get_ticker_stats,
    get_chainlink_price
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
    search_sentiment
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

__all__ = [
    # Market
    'get_price', 'get_candles', 'get_orderbook', 'get_funding_rate', 
    'get_ticker_stats', 'get_chainlink_price',
    # Analysis
    'get_technical_analysis', 'get_patterns', 'get_indicators', 'get_technical_summary',
    # Analytics
    'get_whale_activity', 'get_token_distribution',
    # Web
    'search_news', 'search_sentiment',
    # Frontend
    'get_active_indicators',
    # Memory
    'add_memory', 'search_memory', 'get_recent_history',
    # Knowledge
    'search_knowledge_base'
]
