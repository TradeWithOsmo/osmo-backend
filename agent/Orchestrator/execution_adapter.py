from __future__ import annotations

from typing import Any, Dict, Optional


class ExecutionAdapter:
    """Adapter to bridge agent runtime and backend order execution service."""

    @staticmethod
    async def place_order(
        user_address: str,
        symbol: str,
        side: str,
        amount_usd: float,
        leverage: int,
        order_type: str = "market",
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        tp: Optional[float] = None,
        sl: Optional[float] = None,
        exchange: str = "simulation",
        reduce_only: bool = False,
        post_only: bool = False,
        time_in_force: str = "GTC",
        trigger_condition: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            from services.order_service import OrderService
        except Exception:
            try:
                from backend.websocket.services.order_service import OrderService
            except Exception as exc:
                return {"error": f"Order service import failed: {exc}"}

        svc = OrderService()
        try:
            result = await svc.place_order(
                user_address=user_address,
                symbol=symbol,
                side=side,
                order_type=order_type,
                amount_usd=amount_usd,
                leverage=leverage,
                price=price,
                stop_price=stop_price,
                tp=tp,
                sl=sl,
                exchange=exchange,
                reduce_only=reduce_only,
                post_only=post_only,
                time_in_force=time_in_force,
                trigger_condition=trigger_condition,
            )
            return {"status": "ok", "result": result}
        except Exception as exc:
            return {"error": str(exc)}

    @staticmethod
    async def get_positions(
        user_address: str,
        exchange: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            from services.order_service import OrderService
        except Exception:
            try:
                from backend.websocket.services.order_service import OrderService
            except Exception as exc:
                return {"error": f"Order service import failed: {exc}"}

        svc = OrderService()
        try:
            result = await svc.get_user_positions(user_address=user_address, exchange=exchange)
            return {"status": "ok", "result": result}
        except Exception as exc:
            return {"error": str(exc)}

    @staticmethod
    async def adjust_position_tpsl(
        user_address: str,
        symbol: str,
        tp: Optional[Any] = None,
        sl: Optional[Any] = None,
        exchange: Optional[str] = None,
        size_tokens: Optional[float] = None,
        tp_limit_price: Optional[float] = None,
        sl_limit_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        try:
            from services.order_service import OrderService
        except Exception:
            try:
                from backend.websocket.services.order_service import OrderService
            except Exception as exc:
                return {"error": f"Order service import failed: {exc}"}

        svc = OrderService()
        try:
            result = await svc.update_position_tpsl(
                user_address=user_address,
                symbol=symbol,
                tp=tp,
                sl=sl,
                exchange=exchange,
                size_tokens=size_tokens,
                tp_limit_price=tp_limit_price,
                sl_limit_price=sl_limit_price,
            )
            return {"status": "ok", "result": result}
        except Exception as exc:
            return {"error": str(exc)}

    @staticmethod
    async def adjust_all_positions_tpsl(
        user_address: str,
        tp: Optional[Any] = None,
        sl: Optional[Any] = None,
        tp_pct: Optional[float] = None,
        sl_pct: Optional[float] = None,
        exchange: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            from services.order_service import OrderService
        except Exception:
            try:
                from backend.websocket.services.order_service import OrderService
            except Exception as exc:
                return {"error": f"Order service import failed: {exc}"}

        svc = OrderService()
        try:
            result = await svc.update_all_positions_tpsl(
                user_address=user_address,
                tp=tp,
                sl=sl,
                tp_pct=tp_pct,
                sl_pct=sl_pct,
                exchange=exchange,
            )
            return {"status": "ok", "result": result}
        except Exception as exc:
            return {"error": str(exc)}

    @staticmethod
    async def close_position(
        user_address: str,
        symbol: str,
        price: Optional[float] = None,
        size_pct: float = 1.0,
        exchange: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            from services.trade_action_service import trade_action_service
        except Exception:
            try:
                from backend.websocket.services.trade_action_service import trade_action_service
            except Exception as exc:
                return {"error": f"Trade action service import failed: {exc}"}

        try:
            result = await trade_action_service.close_position(
                user_address=user_address,
                symbol=symbol,
                close_price=price,
                size_pct=size_pct,
                exchange=exchange,
            )
            return {"status": "ok", "result": result}
        except Exception as exc:
            return {"error": str(exc)}

    @staticmethod
    async def close_all_positions(user_address: str) -> Dict[str, Any]:
        try:
            from services.trade_action_service import trade_action_service
        except Exception:
            try:
                from backend.websocket.services.trade_action_service import trade_action_service
            except Exception as exc:
                return {"error": f"Trade action service import failed: {exc}"}

        try:
            results = await trade_action_service.close_all_positions(user_address)
            return {"status": "ok", "result": {"results": results}}
        except Exception as exc:
            return {"error": str(exc)}

    @staticmethod
    async def reverse_position(
        user_address: str,
        symbol: str,
        exchange: Optional[str] = None,
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        try:
            from services.trade_action_service import trade_action_service
        except Exception:
            try:
                from backend.websocket.services.trade_action_service import trade_action_service
            except Exception as exc:
                return {"error": f"Trade action service import failed: {exc}"}

        try:
            result = await trade_action_service.reverse_position(
                user_address=user_address,
                symbol=symbol,
                exchange=exchange,
                price=price,
            )
            return {"status": "ok", "result": result}
        except Exception as exc:
            return {"error": str(exc)}

    @staticmethod
    async def cancel_order(user_address: str, order_id: str) -> Dict[str, Any]:
        try:
            from services.order_service import OrderService
        except Exception:
            try:
                from backend.websocket.services.order_service import OrderService
            except Exception as exc:
                return {"error": f"Order service import failed: {exc}"}

        svc = OrderService()
        try:
            result = await svc.cancel_order(user_address, order_id)
            return {"status": "ok", "result": result}
        except Exception as exc:
            return {"error": str(exc)}
