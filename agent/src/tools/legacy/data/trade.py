"""
Trade Action Tools

Execution-oriented tools for active position management.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ...Orchestrator.execution_adapter import ExecutionAdapter


def _resolve_user_address(
    user_address: Optional[str],
    tool_states: Optional[Dict[str, Any]] = None,
) -> str:
    if user_address:
        return str(user_address).strip()
    tool_states = tool_states or {}
    return str(tool_states.get("user_address") or "").strip()


async def get_positions(
    user_address: Optional[str] = None,
    exchange: Optional[str] = None,
    tool_states: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Get current open positions and account summary for a user.
    """
    resolved_user_address = _resolve_user_address(user_address, tool_states)
    if not resolved_user_address:
        return {"error": "Missing user_address."}
    return await ExecutionAdapter.get_positions(
        user_address=resolved_user_address,
        exchange=exchange,
    )


async def adjust_position_tpsl(
    user_address: Optional[str] = None,
    symbol: str = "",
    tp: Optional[Any] = None,
    sl: Optional[Any] = None,
    gp: Optional[Any] = None,
    gl: Optional[Any] = None,
    exchange: Optional[str] = None,
    size_tokens: Optional[float] = None,
    tp_limit_price: Optional[float] = None,
    sl_limit_price: Optional[float] = None,
    tool_states: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Update TP/SL/GP/GL for a single symbol position.
    
    GP (Validation): Triggers AI validation decision when price crosses.
    GL (Invalidation): Triggers AI invalidation decision when price crosses.
    """
    resolved_user_address = _resolve_user_address(user_address, tool_states)
    if not resolved_user_address:
        return {"error": "Missing user_address."}
    if not symbol:
        return {"error": "Missing symbol."}
    if tp is None and sl is None and gp is None and gl is None:
        return {"error": "Provide at least one of tp, sl, gp, or gl."}

    return await ExecutionAdapter.adjust_position_tpsl(
        user_address=resolved_user_address,
        symbol=symbol,
        tp=tp,
        sl=sl,
        gp=gp,
        gl=gl,
        exchange=exchange,
        size_tokens=size_tokens,
        tp_limit_price=tp_limit_price,
        sl_limit_price=sl_limit_price,
    )


async def adjust_all_positions_tpsl(
    user_address: Optional[str] = None,
    tp: Optional[Any] = None,
    sl: Optional[Any] = None,
    tp_pct: Optional[float] = None,
    sl_pct: Optional[float] = None,
    exchange: Optional[str] = None,
    tool_states: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Bulk update TP/SL for all open positions.

    Supported modes:
    - absolute replace: pass `tp` and/or `sl`
    - from entry percent: pass `tp_pct` and/or `sl_pct`
    """
    resolved_user_address = _resolve_user_address(user_address, tool_states)
    if not resolved_user_address:
        return {"error": "Missing user_address."}
    if tp is None and sl is None and tp_pct is None and sl_pct is None:
        return {"error": "Provide tp/sl or tp_pct/sl_pct."}

    return await ExecutionAdapter.adjust_all_positions_tpsl(
        user_address=resolved_user_address,
        tp=tp,
        sl=sl,
        tp_pct=tp_pct,
        sl_pct=sl_pct,
        exchange=exchange,
    )


async def close_position(
    user_address: Optional[str] = None,
    symbol: str = "",
    price: Optional[float] = None,
    size_pct: float = 1.0,
    exchange: Optional[str] = None,
    tool_states: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Close an open position (market or limit if price is provided).
    """
    resolved_user_address = _resolve_user_address(user_address, tool_states)
    if not resolved_user_address:
        return {"error": "Missing user_address."}
    if not symbol:
        return {"error": "Missing symbol."}
    if size_pct <= 0 or size_pct > 1:
        return {"error": "size_pct must be between 0 and 1."}

    return await ExecutionAdapter.close_position(
        user_address=resolved_user_address,
        symbol=symbol,
        price=price,
        size_pct=size_pct,
        exchange=exchange,
    )


async def close_all_positions(
    user_address: Optional[str] = None,
    tool_states: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Close all open positions for a user (market closes).
    """
    resolved_user_address = _resolve_user_address(user_address, tool_states)
    if not resolved_user_address:
        return {"error": "Missing user_address."}
    return await ExecutionAdapter.close_all_positions(user_address=resolved_user_address)


async def reverse_position(
    user_address: Optional[str] = None,
    symbol: str = "",
    exchange: Optional[str] = None,
    price: Optional[float] = None,
    tool_states: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Reverse a position: close existing then open opposite (simulation/onchain depending on exchange).
    """
    resolved_user_address = _resolve_user_address(user_address, tool_states)
    if not resolved_user_address:
        return {"error": "Missing user_address."}
    if not symbol:
        return {"error": "Missing symbol."}
    return await ExecutionAdapter.reverse_position(
        user_address=resolved_user_address,
        symbol=symbol,
        exchange=exchange,
        price=price,
    )


async def cancel_order(
    user_address: Optional[str] = None,
    order_id: str = "",
    tool_states: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Cancel a pending order by id.
    """
    resolved_user_address = _resolve_user_address(user_address, tool_states)
    if not resolved_user_address:
        return {"error": "Missing user_address."}
    if not order_id:
        return {"error": "Missing order_id."}
    return await ExecutionAdapter.cancel_order(
        user_address=resolved_user_address,
        order_id=order_id,
    )
