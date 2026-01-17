"""
Osmo Data Connectors

Centralized data connector system for AI agent to fetch trading data from:
- Hyperliquid (WebSocket)
- Ostium (HTTP Polling)
- Chainlink (Oracle)
- Dune Analytics (On-chain)
- TradingView Widget (Frontend indicators)
- Web Search (Grok 2 / Perplexity)
- mem0 (Memory layer)
"""

from .manager import ConnectorManager
from .base_connector import BaseConnector

__all__ = ['ConnectorManager', 'BaseConnector']
