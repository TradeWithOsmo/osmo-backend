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
            )
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
