"""
Execution Adapter

Bridges agent tools to websocket business services.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def _order_service():
    try:
        from websocket.services.order_service import order_service
    except Exception:
        from services.order_service import order_service
    return order_service


def _trade_action_service():
    try:
        from websocket.services.trade_action_service import trade_action_service
    except Exception:
        from services.trade_action_service import trade_action_service
    return trade_action_service


class ExecutionAdapter:
    """Static adapter methods used by legacy/new tool modules."""

    @staticmethod
    async def place_order(
        *,
        user_address: str,
        symbol: str,
        side: str,
        amount_usd: float,
        leverage: int = 1,
        order_type: str = "market",
        exchange: Optional[str] = None,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        tp: Optional[Any] = None,
        sl: Optional[Any] = None,
        gp: Optional[Any] = None,
        gl: Optional[Any] = None,
        reduce_only: bool = False,
        post_only: bool = False,
        time_in_force: str = "GTC",
        trigger_condition: Optional[str] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        service = _order_service()
        return await service.place_order(
            user_address=user_address,
            symbol=symbol,
            side=side,
            order_type=order_type,
            amount_usd=float(amount_usd),
            leverage=int(leverage),
            price=price,
            stop_price=stop_price,
            tp=tp,
            sl=sl,
            gp=gp,
            gl=gl,
            exchange=exchange,
            reduce_only=bool(reduce_only),
            post_only=bool(post_only),
            time_in_force=time_in_force,
            trigger_condition=trigger_condition,
        )

    @staticmethod
    async def get_positions(
        *,
        user_address: str,
        exchange: Optional[str] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        service = _order_service()
        return await service.get_user_positions(user_address, exchange=exchange)

    @staticmethod
    async def close_position(
        *,
        user_address: str,
        symbol: str,
        price: Optional[float] = None,
        size_pct: float = 1.0,
        exchange: Optional[str] = None,
        is_limit: bool = False,
        **_: Any,
    ) -> Dict[str, Any]:
        service = _trade_action_service()
        return await service.close_position(
            user_address=user_address,
            symbol=symbol,
            close_price=price,
            size_pct=float(size_pct),
            exchange=exchange,
            is_limit=bool(is_limit),
        )

    @staticmethod
    async def close_all_positions(
        *,
        user_address: str,
        **_: Any,
    ) -> Dict[str, Any]:
        service = _trade_action_service()
        results = await service.close_all_positions(user_address=user_address)
        return {"results": results, "count": len(results)}

    @staticmethod
    async def reverse_position(
        *,
        user_address: str,
        symbol: str,
        exchange: Optional[str] = None,
        price: Optional[float] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        service = _trade_action_service()
        return await service.reverse_position(
            user_address=user_address,
            symbol=symbol,
            exchange=exchange,
            price=price,
        )

    @staticmethod
    async def cancel_order(
        *,
        user_address: str,
        order_id: str,
        **_: Any,
    ) -> Dict[str, Any]:
        service = _order_service()
        return await service.cancel_order(user_address=user_address, order_id=order_id)

    @staticmethod
    async def adjust_position_tpsl(
        *,
        user_address: str,
        symbol: str,
        tp: Optional[Any] = None,
        sl: Optional[Any] = None,
        exchange: Optional[str] = None,
        size_tokens: Optional[float] = None,
        tp_limit_price: Optional[float] = None,
        sl_limit_price: Optional[float] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        service = _order_service()
        return await service.update_position_tpsl(
            user_address=user_address,
            symbol=symbol,
            tp=tp,
            sl=sl,
            exchange=exchange,
            size_tokens=size_tokens,
            tp_limit_price=tp_limit_price,
            sl_limit_price=sl_limit_price,
        )

    @staticmethod
    async def adjust_all_positions_tpsl(
        *,
        user_address: str,
        tp: Optional[Any] = None,
        sl: Optional[Any] = None,
        tp_pct: Optional[float] = None,
        sl_pct: Optional[float] = None,
        exchange: Optional[str] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        service = _order_service()
        return await service.update_all_positions_tpsl(
            user_address=user_address,
            tp=tp,
            sl=sl,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            exchange=exchange,
        )

    # Compatibility alias used in some older call-sites.
    @staticmethod
    async def execute_trade(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await ExecutionAdapter.place_order(*args, **kwargs)


__all__ = ["ExecutionAdapter"]
