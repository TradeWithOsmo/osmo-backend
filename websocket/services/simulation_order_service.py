import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional

from connectors.init_connectors import connector_registry
from database.connection import AsyncSessionLocal
from database.models import Order, Position
from sqlalchemy import select
from storage.redis_manager import redis_manager


class SimulationOrderService:
    """Encapsulates simulation/ledger order flow, separate from generic order routing."""

    @staticmethod
    async def _resolve_price(symbol: str, explicit_price: Optional[float]) -> float:
        if explicit_price is not None:
            try:
                parsed = float(explicit_price)
                if parsed > 0:
                    return parsed
            except Exception:
                pass

        # Best-effort live price lookup from available connectors.
        for source in ("hyperliquid", "ostium"):
            try:
                conn = connector_registry.get_connector(source)
            except RuntimeError:
                conn = None
            if not conn:
                continue
            try:
                md = await conn.fetch(symbol.split("-")[0], data_type="price")
                px = float(md.get("data", {}).get("price", 0))
                if px > 0:
                    return px
            except Exception:
                continue

        # Dev fallback to keep simulation usable even when feeds are unavailable.
        fallback_prices = {
            "BTC-USD": 95000.0,
            "ETH-USD": 3500.0,
            "SOL-USD": 180.0,
        }
        return fallback_prices.get(symbol, 50000.0)

    @staticmethod
    async def _publish_order_placed(
        user_address: str,
        *,
        order_id: str,
        symbol: str,
        side: str,
        order_type: str,
        status: str,
        price: Optional[float],
        amount_usd: float,
        leverage: int,
        reduce_only: bool,
        post_only: bool,
        time_in_force: str,
    ) -> None:
        try:
            await redis_manager.publish(
                f"user_notifications:{user_address.lower()}",
                {
                    "type": "order_placed",
                    "address": user_address.lower(),
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": {
                        "order_id": order_id,
                        "exchange": "simulation",
                        "symbol": symbol,
                        "side": side.lower(),
                        "order_type": order_type,
                        "status": status,
                        "price": price,
                        "amount_usd": amount_usd,
                        "leverage": leverage,
                        "reduce_only": reduce_only,
                        "post_only": post_only,
                        "time_in_force": time_in_force,
                    },
                },
            )
        except Exception:
            # Best effort notification only.
            pass

    async def place_order(
        self,
        user_address: str,
        symbol: str,
        side: str,
        order_type: str,
        amount_usd: float,
        leverage: int,
        price: Optional[float],
        stop_price: Optional[float],
        tp: Optional[str],
        sl: Optional[str],
        gp: Optional[float],
        gl: Optional[float],
        reduce_only: bool,
        post_only: bool,
        time_in_force: str,
        update_position_tpsl_cb: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        from services.ledger_service import ledger_service

        current_price = await self._resolve_price(symbol=symbol, explicit_price=price)

        # In simulation mode, input amount_usd is collateral/margin.
        simulation_notional_usd = amount_usd * leverage if leverage > 0 else amount_usd
        size_tokens = (simulation_notional_usd / current_price) if current_price > 0 else 0
        margin_used = amount_usd
        order_id = str(uuid.uuid4())

        is_pending = order_type in ["limit", "stop_market", "stop_limit"]
        exchange_response = {
            "status": "pending" if is_pending else "filled",
            "exchange_order_id": f"sim_{order_id[:8]}",
        }

        if is_pending:
            # Pending orders are persisted for matching engine pickup.
            async with AsyncSessionLocal() as session:
                order = Order(
                    id=order_id,
                    user_address=user_address.lower(),
                    exchange="simulation",
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    price=price,
                    stop_price=stop_price,
                    size=size_tokens,
                    notional_usd=simulation_notional_usd,
                    leverage=leverage,
                    reduce_only=reduce_only,
                    post_only=post_only,
                    time_in_force=time_in_force,
                    exchange_order_id=exchange_response.get("exchange_order_id"),
                    status="OPEN",
                    created_at=datetime.utcnow(),
                    filled_size=0,
                    trigger_condition="BELOW" if str(side).lower() == "sell" else "ABOVE",
                    trigger_price=stop_price,
                )
                session.add(order)
                await session.commit()
        else:
            if reduce_only:
                # Reduce-only market order must close/reduce an existing simulation position,
                # not open the opposite side.
                async with AsyncSessionLocal() as session:
                    res = await session.execute(
                        select(Position)
                        .where(
                            Position.user_address == user_address.lower(),
                            Position.symbol == symbol,
                            Position.exchange == "simulation",
                            Position.status == "OPEN",
                        )
                        .order_by(Position.id.desc())
                        .limit(1)
                    )
                    open_position = res.scalar_one_or_none()

                if not open_position or float(open_position.size or 0) <= 0:
                    raise ValueError(
                        f"No open simulation position found for {symbol} to reduce/close"
                    )

                close_size = min(float(open_position.size), float(size_tokens or 0))
                if close_size <= 0:
                    raise ValueError("Computed reduce_only close size is invalid")

                await ledger_service.process_trade_close(
                    user_address=user_address,
                    symbol=symbol,
                    close_price=current_price,
                    size_to_close=close_size,
                    exchange="simulation",
                )
            else:
                # Market order executes immediately through ledger.
                await ledger_service.process_trade_open(
                    user_address=user_address,
                    symbol=symbol,
                    side=side,
                    size_token=size_tokens,
                    entry_price=current_price,
                    leverage=leverage,
                    margin_used=margin_used,
                    order_id=order_id,
                    tp=tp,
                    sl=sl,
                    gp=gp,
                    gl=gl,
                )

        await self._publish_order_placed(
            user_address=user_address,
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            status=exchange_response.get("status", "pending"),
            price=price if price is not None else current_price,
            amount_usd=amount_usd,
            leverage=leverage,
            reduce_only=reduce_only,
            post_only=post_only,
            time_in_force=time_in_force,
        )

        if (
            (tp is not None or sl is not None)
            and (not reduce_only)
            and update_position_tpsl_cb is not None
        ):
            await update_position_tpsl_cb(
                user_address=user_address,
                symbol=symbol,
                tp=tp,
                sl=sl,
                exchange="simulation",
            )

        return {
            "order_id": order_id,
            "exchange": "simulation",
            "symbol": symbol,
            "status": exchange_response.get("status"),
            "exchange_order_id": exchange_response.get("exchange_order_id"),
            "message": "Order placed on simulation",
        }


simulation_order_service = SimulationOrderService()
