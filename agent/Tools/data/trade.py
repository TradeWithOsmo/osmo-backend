"""
Trade Action Tools

Execution-oriented tools for active position management.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ...Orchestrator.execution_adapter import ExecutionAdapter


async def adjust_position_tpsl(
    user_address: str,
    symbol: str,
    tp: Optional[Any] = None,
    sl: Optional[Any] = None,
    exchange: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update TP/SL for a single symbol position.
    """
    if not user_address:
        return {"error": "Missing user_address."}
    if not symbol:
        return {"error": "Missing symbol."}
    if tp is None and sl is None:
        return {"error": "Provide at least one of tp or sl."}

    return await ExecutionAdapter.adjust_position_tpsl(
        user_address=user_address,
        symbol=symbol,
        tp=tp,
        sl=sl,
        exchange=exchange,
    )


async def adjust_all_positions_tpsl(
    user_address: str,
    tp: Optional[Any] = None,
    sl: Optional[Any] = None,
    tp_pct: Optional[float] = None,
    sl_pct: Optional[float] = None,
    exchange: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Bulk update TP/SL for all open positions.

    Supported modes:
    - absolute replace: pass `tp` and/or `sl`
    - from entry percent: pass `tp_pct` and/or `sl_pct`
    """
    if not user_address:
        return {"error": "Missing user_address."}
    if tp is None and sl is None and tp_pct is None and sl_pct is None:
        return {"error": "Provide tp/sl or tp_pct/sl_pct."}

    return await ExecutionAdapter.adjust_all_positions_tpsl(
        user_address=user_address,
        tp=tp,
        sl=sl,
        tp_pct=tp_pct,
        sl_pct=sl_pct,
        exchange=exchange,
    )
