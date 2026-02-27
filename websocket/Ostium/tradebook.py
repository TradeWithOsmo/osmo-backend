"""
Ostium tradebook.py
===================
Ostium is an oracle-based perpetuals DEX on Arbitrum.
It does NOT expose a public orderbook or trade history REST API.
Trades happen via on-chain position opens/closes.

We return None for orderbook and empty list for trades so the
frontend gracefully hides those panels for Ostium markets.
"""
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


async def get_orderbook(symbol: str, depth: int = 20) -> Optional[Dict[str, Any]]:
    """Ostium has no public orderbook. Returns None."""
    logger.debug(f"[Ostium] No orderbook available for {symbol}")
    return None


async def get_recent_trades(symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
    """Ostium has no public trade history REST endpoint. Returns empty list."""
    logger.debug(f"[Ostium] No public trade history for {symbol}")
    return []
