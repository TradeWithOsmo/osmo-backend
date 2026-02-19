import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from database.connection import AsyncSessionLocal
from database.models import Order, Position
from services.ledger_service import ledger_service
from services.order_service import OrderService
from sqlalchemy import select

logger = logging.getLogger(__name__)


class TradeActionService:
    """
    Handles complex simulation actions that require multiple steps or ledger interactions:
    - Close Position (Market/Limit)
    - Close All Positions
    - Reverse Position
    - Stop Loss / Take Profit triggering (Check logic)
    """

    def __init__(self):
        self.order_service = OrderService()

    async def close_position(
        self,
        user_address: str,
        symbol: str,
        close_price: float = None,
        size_pct: float = 1.0,
        exchange: Optional[str] = None,
        is_limit: bool = False,
    ) -> Dict[str, Any]:
        """
        Close a position (Full or Partial) in Simulation/Ledger mode.
        If is_limit=True and close_price is set, creates a pending limit order.
        Otherwise executes immediately at close_price (or market price if not set).
        """
        import os

        from connectors.init_connectors import connector_registry

        # Check if force simulation mode is enabled
        force_mode = os.getenv("FORCE_EXECUTION_MODE", "auto").lower().strip()
        use_simulation = force_mode == "simulation"

        async with AsyncSessionLocal() as session:
            # 1. Get Current Position
            exchange_norm = (exchange or "").strip().lower() or None
            result = await session.execute(
                select(Position).where(
                    Position.user_address == user_address.lower(),
                    Position.symbol == symbol,
                    Position.status == "OPEN",
                    *([Position.exchange == exchange_norm] if exchange_norm else []),
                )
            )
            positions = result.scalars().all()

            if not positions:
                raise ValueError(f"No open position found for {symbol}")

            if len(positions) > 1:
                # We can have multiple OPEN rows per (user,symbol) because the DB is a mirror/cache.
                # Pick a deterministic target so close actions don't 500.
                logger.warning(
                    "Multiple OPEN positions found; selecting one to close",
                    extra={
                        "user_address": user_address.lower(),
                        "symbol": symbol,
                        "count": len(positions),
                        "exchanges": [p.exchange for p in positions],
                    },
                )

                def _sort_key(p: Position):
                    # Prefer onchain if present, otherwise newest.
                    onchain_rank = 1 if (p.exchange or "").lower() == "onchain" else 0
                    opened = p.opened_at or datetime.min
                    return (onchain_rank, opened, p.id or 0)

                position = sorted(positions, key=_sort_key, reverse=True)[0]
            else:
                position = positions[0]

            # --- FORCE SIMULATION MODE ---
            if use_simulation:
                print(
                    f"[TradeActionService] FORCE_EXECUTION_MODE=simulation, using ledger for {symbol} close"
                )

                if is_limit and close_price and close_price > 0:
                    size_to_close = position.size * size_pct
                    opposite_side = "sell" if position.side.lower() in ("long", "buy") else "buy"
                    order_id = f"sim_limit_close_{symbol}_{datetime.utcnow().timestamp()}"
                    
                    async with AsyncSessionLocal() as session:
                        limit_order = Order(
                            id=order_id,
                            user_address=user_address.lower(),
                            exchange="simulation",
                            symbol=symbol,
                            side=opposite_side,
                            order_type="limit",
                            size=size_to_close,
                            price=close_price,
                            notional_usd=size_to_close * close_price,
                            leverage=position.leverage,
                            reduce_only=True,
                            status="OPEN",
                            filled_size=0,
                            created_at=datetime.utcnow(),
                        )
                        session.add(limit_order)
                        await session.commit()

                    return {
                        "symbol": symbol,
                        "action": "limit_close",
                        "order_id": order_id,
                        "size": size_to_close,
                        "limit_price": close_price,
                        "status": "pending",
                    }

                fallback_price = getattr(position, "entry_price", None)
                conn = connector_registry.get_connector("hyperliquid")
                if not conn or "USD" not in symbol:
                    conn = connector_registry.get_connector("ostium")

                if conn:
                    try:
                        base = symbol.split("-")[0]
                        data = await asyncio.wait_for(
                            conn.fetch(base, data_type="price"), timeout=0.75
                        )
                        close_price = float(
                            (data or {}).get("data", {}).get("price", 0) or 0
                        )
                    except Exception:
                        pass

                if (
                    (not close_price or close_price <= 0)
                    and fallback_price
                    and fallback_price > 0
                ):
                    close_price = float(fallback_price)

                if not close_price:
                    raise ValueError("Could not determine market price for close.")

                size_to_close = position.size * size_pct

                await ledger_service.process_trade_close(
                    user_address,
                    symbol,
                    close_price,
                    size_to_close,
                    exchange="simulation",
                )

                return {
                    "symbol": symbol,
                    "action": "close",
                    "size_closed": size_to_close,
                    "price": close_price,
                    "status": "success",
                }

            # --- ON-CHAIN ROUTING ---
            if position.exchange == "onchain":
                # For on-chain close, we place a reduce-only order via OrderService
                opposite_side = (
                    "sell" if position.side.lower() in ("long", "buy") else "buy"
                )

                # We use the amount_usd from the position (notional) for a full close
                # size_to_close is tokens, but on-chain connector usually handles amount_usd
                # Actually, our on-chain connector's place_order expects 'size' as AmountUSD for on-chain.

                # Calculate size in USD for the close order
                close_amount_usd = (
                    position.size
                    * (close_price if close_price else position.entry_price)
                    * size_pct
                )

                print(
                    f"[TradeActionService] Routing On-Chain Close for {symbol}: side={opposite_side} (position.side={position.side}), amount_usd={close_amount_usd}, reduce_only=True"
                )

                return await self.order_service.place_order(
                    user_address=user_address,
                    symbol=symbol,
                    side=opposite_side,
                    order_type="market" if not close_price else "limit",
                    amount_usd=close_amount_usd,
                    leverage=position.leverage,
                    price=close_price,
                    exchange="onchain",
                    reduce_only=True,
                )

            # --- SIMULATION ROUTING ---
            if is_limit and close_price and close_price > 0:
                size_to_close = position.size * size_pct
                opposite_side = "sell" if position.side.lower() in ("long", "buy") else "buy"
                order_id = f"sim_limit_close_{symbol}_{datetime.utcnow().timestamp()}"
                
                async with AsyncSessionLocal() as session:
                    limit_order = Order(
                        id=order_id,
                        user_address=user_address.lower(),
                        exchange="simulation",
                        symbol=symbol,
                        side=opposite_side,
                        order_type="limit",
                        size=size_to_close,
                        price=close_price,
                        notional_usd=size_to_close * close_price,
                        leverage=position.leverage,
                        reduce_only=True,
                        status="OPEN",
                        filled_size=0,
                        created_at=datetime.utcnow(),
                    )
                    session.add(limit_order)
                    await session.commit()

                return {
                    "symbol": symbol,
                    "action": "limit_close",
                    "order_id": order_id,
                    "size": size_to_close,
                    "limit_price": close_price,
                    "status": "pending",
                }

            # Market close - get price if needed
            fallback_price = getattr(position, "entry_price", None)

            conn = connector_registry.get_connector("hyperliquid")
            if not conn or "USD" not in symbol:
                conn = connector_registry.get_connector("ostium")

            if conn:
                try:
                    base = symbol.split("-")[0]
                    data = await asyncio.wait_for(
                        conn.fetch(base, data_type="price"), timeout=0.75
                    )
                    close_price = float(
                        (data or {}).get("data", {}).get("price", 0) or 0
                    )
                except Exception:
                    pass

            if (
                (not close_price or close_price <= 0)
                and fallback_price
                and fallback_price > 0
            ):
                close_price = float(fallback_price)

            if not close_price:
                raise ValueError("Could not determine market price for close.")

            size_to_close = position.size * size_pct

            await ledger_service.process_trade_close(
                user_address,
                symbol,
                close_price,
                size_to_close,
                exchange=position.exchange or "simulation",
            )

            return {
                "symbol": symbol,
                "action": "close",
                "size_closed": size_to_close,
                "price": close_price,
                "status": "success",
            }

    async def close_all_positions(self, user_address: str) -> List[Dict[str, Any]]:
        """Close all open positions for a user"""
        results = []
        from connectors.init_connectors import connector_registry

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Position).where(
                    Position.user_address == user_address.lower(),
                    Position.status == "OPEN",
                )
            )
            positions = result.scalars().all()

            # We need to close them one by one.
            pos_list = [
                {
                    "symbol": p.symbol,
                    "size": p.size,
                    "exchange": p.exchange,
                    "side": p.side,
                }
                for p in positions
            ]
            closed_symbols = set(p["symbol"] for p in pos_list)

        # --- ROBUSTNESS: Also check on-chain for missed positions ---
        connector = connector_registry.get_connector("onchain")
        if connector:
            try:
                onchain_positions = await asyncio.wait_for(
                    connector.get_user_positions(user_address), timeout=1.0
                )
                for op in onchain_positions:
                    # Skip if we already have this symbol in DB (avoid double-close)
                    if op["symbol"] in closed_symbols:
                        continue

                    print(
                        f"[TradeActionService] Found missed on-chain position for {op['symbol']}, adding to close list"
                    )
                    pos_list.append(
                        {
                            "symbol": op["symbol"],
                            "size": op["size"],
                            "exchange": "onchain",
                            "side": op.get("side"),
                            "is_fallback": True,
                        }
                    )
            except Exception as e:
                logger.error(f"Failed to fetch on-chain positions for Close All: {e}")

        for i, p in enumerate(pos_list):
            try:
                if i > 0:
                    await asyncio.sleep(2.1)
                res = await self.close_position(
                    user_address,
                    p["symbol"],
                    size_pct=1.0,
                    exchange=p.get("exchange"),
                )
                results.append(res)
                closed_symbols.add(p["symbol"])
            except Exception as e:
                logger.error(f"Failed to close {p['symbol']}: {e}")
                results.append({"symbol": p["symbol"], "error": str(e)})

        return results

    async def reverse_position(
        self,
        user_address: str,
        symbol: str,
        exchange: Optional[str] = None,
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Reverse a position: Close existing and Open opposite (2x size notional effect to flip).
        For on-chain, we attempt to do this in a single transaction if possible.
        """
        import os

        from connectors.init_connectors import connector_registry

        # Check if force simulation mode is enabled
        force_mode = os.getenv("FORCE_EXECUTION_MODE", "auto").lower().strip()
        use_simulation = force_mode == "simulation"

        exchange_norm = (exchange or "").strip().lower() or None
        price_hint = (
            float(price)
            if isinstance(price, (int, float)) and price and price > 0
            else None
        )

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Position).where(
                    Position.user_address == user_address.lower(),
                    Position.symbol == symbol,
                    Position.status == "OPEN",
                    *([Position.exchange == exchange_norm] if exchange_norm else []),
                )
            )
            positions = result.scalars().all()
            position = None
            if positions:
                if len(positions) > 1:
                    logger.warning(
                        "Multiple OPEN positions found during reverse; selecting one",
                        extra={
                            "user_address": user_address.lower(),
                            "symbol": symbol,
                            "count": len(positions),
                            "exchanges": [p.exchange for p in positions],
                        },
                    )

                    def _sort_key(p: Position):
                        onchain_rank = (
                            1 if (p.exchange or "").lower() == "onchain" else 0
                        )
                        opened = p.opened_at or datetime.min
                        return (onchain_rank, opened, p.id or 0)

                    position = sorted(positions, key=_sort_key, reverse=True)[0]
                else:
                    position = positions[0]

            # --- ROBUSTNESS: If not in DB, try to fetch from On-chain Connector ---
            if not position and (exchange_norm is None or exchange_norm == "onchain"):
                print(
                    f"[TradeActionService] Position {symbol} not in DB for {user_address}, checking On-Chain..."
                )
                connector = connector_registry.get_connector("onchain")
                if connector:
                    onchain_pos = await connector.get_user_positions(user_address)
                    target = next(
                        (p for p in onchain_pos if p["symbol"] == symbol), None
                    )
                    if target:
                        print(
                            f"[TradeActionService] Found on-chain position for {symbol}: {target['side']} {target['position_value']} USD"
                        )
                        # Use a transient object for processing
                        position = Position(
                            user_address=user_address.lower(),
                            symbol=symbol,
                            side=target["side"],
                            size=target["size"],
                            leverage=target["leverage"],
                            exchange="onchain",
                            status="OPEN",
                        )

            if not position:
                raise ValueError(f"No open position to reverse for {symbol}")

            # --- FORCE SIMULATION MODE ---
            if use_simulation:
                print(
                    f"[TradeActionService] FORCE_EXECUTION_MODE=simulation, using ledger for {symbol} reverse"
                )

                # Get current price
                current_price = price_hint or (await self._get_current_price(symbol))

                old_side = position.side
                old_size = position.size
                old_leverage = position.leverage

                # 1. Close Existing
                close_res = await self.close_position(
                    user_address,
                    symbol,
                    close_price=current_price,
                    size_pct=1.0,
                    exchange="simulation",
                )
                close_price = close_res.get("price") or current_price

                # 2. Open New Opposite
                new_side = "short" if old_side.lower() in ("long", "buy") else "long"
                margin_required = (old_size * close_price) / old_leverage

                import uuid

                order_id = "rev_" + str(uuid.uuid4())[:8]

                await ledger_service.process_trade_open(
                    user_address,
                    symbol,
                    new_side,
                    old_size,
                    close_price,
                    old_leverage,
                    margin_required,
                    order_id,
                    exchange="simulation",
                )

                return {
                    "symbol": symbol,
                    "action": "reverse",
                    "old_side": old_side,
                    "new_side": new_side,
                    "price": close_price,
                    "status": "success",
                }

            # --- ON-CHAIN SINGLE TRANSACTION REVERSE ---
            if position.exchange == "onchain":
                current_price = price_hint or (await self._get_current_price(symbol))
                # To reverse, we need 2x the current notional size
                # 1x to close, 1x to open opposite
                amount_usd = (position.size * current_price) * 2
                new_side = (
                    "sell" if position.side.lower() in ("long", "buy", "0") else "buy"
                )

                print(
                    f"[TradeActionService] Single-Tx On-Chain Reverse for {symbol}: {new_side} {amount_usd} USD (size_tokens: {position.size})"
                )

                return await self.order_service.place_order(
                    user_address=user_address,
                    symbol=symbol,
                    side=new_side,
                    order_type="market",
                    amount_usd=amount_usd,
                    leverage=position.leverage,
                    exchange="onchain",
                    reduce_only=False,  # Critical: must be False to allow opening opposite
                )

            # --- SIMULATION / DEFAULT ROUTING ---
            old_side = position.side
            old_size = position.size
            old_leverage = position.leverage

            # 1. Close Existing
            close_res = await self.close_position(
                user_address,
                symbol,
                close_price=price_hint,
                size_pct=1.0,
                exchange=position.exchange,
            )
            close_price = (
                close_res.get("price")
                or price_hint
                or (await self._get_current_price(symbol))
            )

            # 2. Open New Opposite
            new_side = "short" if old_side.lower() in ("long", "buy") else "long"
            margin_required = (old_size * close_price) / old_leverage

            import uuid

            order_id = "rev_" + str(uuid.uuid4())[:8]

            await ledger_service.process_trade_open(
                user_address,
                symbol,
                new_side,
                old_size,
                close_price,
                old_leverage,
                margin_required,
                order_id,
                exchange=position.exchange or "simulation",
            )

            return {
                "symbol": symbol,
                "action": "reverse",
                "old_side": old_side,
                "new_side": new_side,
                "price": close_price,
                "status": "success",
            }


trade_action_service = TradeActionService()
