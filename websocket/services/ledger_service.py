import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from database.connection import AsyncSessionLocal
from database.models import FundingHistory, LedgerAccount, Order, Position
from sqlalchemy import select
from sqlalchemy.orm import Session
from storage.redis_manager import redis_manager

INITIAL_SIMULATION_BALANCE = float(os.getenv("INITIAL_SIMULATION_BALANCE", "1000"))


class LedgerService:
    """
    Manages the Off-Chain Ledger State.
    Source of Truth for User Balances and Positions in Hybrid Mode.
    """

    async def get_account(self, user_address: str, session: Session) -> LedgerAccount:
        """Get or create ledger account with initial balance for simulation"""
        result = await session.execute(
            select(LedgerAccount).where(LedgerAccount.address == user_address.lower())
        )
        account = result.scalar_one_or_none()
        if not account:
            account = LedgerAccount(address=user_address.lower())

            force_mode = os.getenv("FORCE_EXECUTION_MODE", "auto").lower().strip()
            if force_mode == "simulation":
                # Seed initial balance from on-chain vault balance to mirror real balance.
                initial_balance = await self._fetch_vault_balance(user_address)
                if initial_balance <= 0:
                    initial_balance = INITIAL_SIMULATION_BALANCE
                account.balance = initial_balance
                account.available_balance = initial_balance
                account.locked_margin = 0
                print(f"[Ledger] Created simulation account for {user_address} with initial balance {initial_balance}")

            session.add(account)
            await session.flush()
        return account

    async def _fetch_vault_balance(self, user_address: str) -> float:
        """Fetch user's on-chain TradingVault balance for simulation seed."""
        try:
            from connectors.init_connectors import connector_registry
            onchain = connector_registry.get_connector("onchain")
            if onchain and hasattr(onchain, "get_user_balances"):
                import asyncio
                balances = await asyncio.wait_for(
                    onchain.get_user_balances(user_address), timeout=3.0
                )
                return float(balances.get("account_value", 0) or 0)
        except Exception as e:
            print(f"[Ledger] Could not fetch vault balance for {user_address}: {e}")
        return 0.0

    async def _notify_user(
        self,
        user_address: str,
        event_type: str = "account_update",
        meta: Optional[Dict[str, Any]] = None,
    ):
        """Publish notification to Redis for WebSocket broadcast"""
        try:
            # We fetch latest positions & summary to send the full state for "instant" update
            from services.order_service import OrderService

            order_service = OrderService()
            state = await order_service.get_user_positions(user_address)

            message = {
                "type": event_type,
                "address": user_address.lower(),
                "data": state,
                "meta": meta or {},
                "timestamp": datetime.utcnow().isoformat(),
            }
            await redis_manager.publish(
                f"user_notifications:{user_address.lower()}", message
            )
        except Exception as e:
            print(f"[Ledger] Failed to notify user {user_address}: {e}")

    async def process_deposit(self, user_address: str, amount: float, tx_hash: str):
        """Credit user balance from on-chain deposit"""
        async with AsyncSessionLocal() as session:
            account = await self.get_account(user_address, session)

            # Check for duplicate processing
            exists = await session.execute(
                select(FundingHistory).where(FundingHistory.tx_hash == tx_hash)
            )
            if exists.scalar_one_or_none():
                return

            force_mode = os.getenv("FORCE_EXECUTION_MODE", "auto").lower().strip()
            if force_mode == "simulation":
                # In pure simulation mode, do not mutate simulation ledger balance
                # with on-chain funding events. Keep it isolated from real vault balance.
                history = FundingHistory(
                    user_address=user_address.lower(),
                    type="Deposit",
                    asset="USDC",
                    amount=amount,
                    tx_hash=tx_hash,
                    status="Completed",
                )
                session.add(history)
                await session.commit()
                print(
                    f"[Ledger] Simulation mode: tracked on-chain deposit {amount} USDC for {user_address} without ledger balance mutation"
                )
                return

            # Update Balance
            account.balance += amount
            account.available_balance = account.balance - account.locked_margin

            # Record History
            history = FundingHistory(
                user_address=user_address.lower(),
                type="Deposit",
                asset="USDC",
                amount=amount,
                tx_hash=tx_hash,
                status="Completed",
            )
            session.add(history)
            await session.commit()
            print(f"[Ledger] Deposited {amount} USDC for {user_address}")
            await self._notify_user(
                user_address,
                "deposit_confirmed",
                meta={"asset": "USDC", "amount": amount, "tx_hash": tx_hash},
            )

    async def process_withdrawal(self, user_address: str, amount: float, tx_hash: str):
        """Debit user balance from on-chain withdrawal"""
        async with AsyncSessionLocal() as session:
            account = await self.get_account(user_address, session)

            exists = await session.execute(
                select(FundingHistory).where(FundingHistory.tx_hash == tx_hash)
            )
            if exists.scalar_one_or_none():
                return

            force_mode = os.getenv("FORCE_EXECUTION_MODE", "auto").lower().strip()
            if force_mode == "simulation":
                # In pure simulation mode, do not mutate simulation ledger balance
                # with on-chain funding events. Keep it isolated from real vault balance.
                history = FundingHistory(
                    user_address=user_address.lower(),
                    type="Withdraw",
                    asset="USDC",
                    amount=amount,
                    tx_hash=tx_hash,
                    status="Completed",
                )
                session.add(history)
                await session.commit()
                print(
                    f"[Ledger] Simulation mode: tracked on-chain withdrawal {amount} USDC for {user_address} without ledger balance mutation"
                )
                return

            account.balance -= amount
            account.available_balance = account.balance - account.locked_margin

            history = FundingHistory(
                user_address=user_address.lower(),
                type="Withdraw",
                asset="USDC",
                amount=amount,
                tx_hash=tx_hash,
                status="Completed",
            )
            session.add(history)
            await session.commit()
            print(f"[Ledger] Withdrawn {amount} USDC for {user_address}")
            await self._notify_user(
                user_address,
                "withdrawal_confirmed",
                meta={"asset": "USDC", "amount": amount, "tx_hash": tx_hash},
            )

    async def process_trade_open(
        self,
        user_address: str,
        symbol: str,
        side: str,
        size_token: float,
        entry_price: float,
        leverage: int,
        margin_used: float,
        order_id: str,
        position_id: str = None,
        exchange: str = "simulation",
        tp: str = None,
        sl: str = None,
        gp: float = None,
        gl: float = None,
    ):
        """Lock margin and open/increase position"""
        print(
            f"[Ledger.process_trade_open] Opening {side} position for {symbol}, size={size_token}, exchange={exchange}"
        )

        async with AsyncSessionLocal() as session:
            # Normalize side
            norm_side = "long" if side.lower() in ("buy", "long") else "short"

            account = await self.get_account(user_address, session)

            # Update Ledger
            account.locked_margin += margin_used
            account.available_balance = account.balance - account.locked_margin

            # Create/Update Position
            # Logic to merge if exists
            result = await session.execute(
                select(Position)
                .where(
                    Position.user_address == user_address.lower(),
                    Position.symbol == symbol,
                    Position.exchange == exchange,
                    Position.status == "OPEN",
                )
                .order_by(Position.id)  # Ensure deterministic ordering
                .limit(1)  # Prevent multiple rows error
            )
            positions = result.scalars().all()
            position = positions[0] if positions else None

            # Check if there's a recently CLOSED position (to prevent accidental opposite-side opens)
            closed_result = await session.execute(
                select(Position)
                .where(
                    Position.user_address == user_address.lower(),
                    Position.symbol == symbol,
                    Position.exchange == exchange,
                    Position.status == "CLOSED",
                )
                .order_by(Position.closed_at.desc())
                .limit(1)
            )
            closed_positions = closed_result.scalars().all()
            closed_position = closed_positions[0] if closed_positions else None

            if closed_position and closed_position.side != norm_side:
                # Warn about potential unintended flip
                print(
                    f"[Ledger] Warning: Opening {norm_side} position for {symbol}, but recently closed {closed_position.side} position. "
                    f"This might be an unintended flip. Consider using reverse_position instead."
                )

            if position:
                # For now, we don't net opposite-direction opens into an existing position via OrderService.
                # Users should close/reverse explicitly so margin/PnL accounting stays predictable.
                if position.side != norm_side:
                    raise ValueError(
                        f"Opposite-side position exists for {symbol} ({position.side}). Close or reverse first."
                    )

                # Merge logic (weighted avg entry)
                total_size = position.size + size_token
                new_entry = (
                    (position.entry_price * position.size) + (entry_price * size_token)
                ) / total_size

                position.entry_price = new_entry
                position.size = total_size
                position.margin_used += margin_used

                # Keep leverage internally consistent with notional/margin after merges.
                try:
                    notional = position.size * position.entry_price
                    if (
                        position.margin_used
                        and position.margin_used > 0
                        and notional > 0
                    ):
                        effective = notional / position.margin_used
                        position.leverage = max(1, int(round(effective)))
                except Exception:
                    pass
                if tp is not None:
                    position.tp = str(tp)
                if sl is not None:
                    position.sl = str(sl)
                if gp is not None:
                    position.gp = float(gp)
                if gl is not None:
                    position.gl = float(gl)
            else:
                position = Position(
                    user_address=user_address.lower(),
                    symbol=symbol,
                    exchange=exchange,
                    side=norm_side,
                    size=size_token,
                    entry_price=entry_price,
                    leverage=leverage,
                    margin_used=margin_used,
                    tp=str(tp) if tp is not None else None,
                    sl=str(sl) if sl is not None else None,
                    gp=float(gp) if gp is not None else None,
                    gl=float(gl) if gl is not None else None,
                    status="OPEN",
                    position_id=position_id or order_id,
                )
                session.add(position)

            # Update Order Status or Create Shadow Order
            if order_id:
                # Try to find by UUID (standard) or transaction hash/contract order id
                from sqlalchemy import or_

                o_res = await session.execute(
                    select(Order)
                    .where(
                        or_(Order.id == order_id, Order.exchange_order_id == order_id)
                    )
                    .order_by(Order.id)
                    .limit(1)
                )
                orders = o_res.scalars().all()
                order = orders[0] if orders else None

                if not order:
                    # Create Shadow Order from On-Chain Event
                    order = Order(
                        id=order_id,
                        user_address=user_address.lower(),
                        exchange=exchange,
                        symbol=symbol,
                        side=side.lower(),  # Keep original side for Order record (buy/sell)
                        order_type="market",  # Assumed for now
                        size=size_token,
                        price=entry_price,
                        leverage=leverage,
                        notional_usd=size_token * entry_price,  # Calculated notional
                        status="FILLED",
                        created_at=datetime.utcnow(),
                        filled_at=datetime.utcnow(),
                        filled_size=size_token,
                        avg_fill_price=entry_price,
                    )
                    session.add(order)

                else:
                    order.status = "FILLED"
                    order.filled_at = datetime.utcnow()
                    order.filled_size = size_token
                    order.avg_fill_price = entry_price

            await session.commit()
            print(f"[Ledger] Opened/Increased {side} {symbol} for {user_address}")
            await self._notify_user(
                user_address,
                "trade_filled",
                meta={
                    "symbol": symbol,
                    "side": norm_side,
                    "exchange": exchange,
                    "size_tokens": size_token,
                    "entry_price": entry_price,
                    "leverage": leverage,
                    "margin_used": margin_used,
                },
            )

    async def process_position_close_event(
        self, position_id_hex: str, user_address: str, price: float, pnl: float
    ):
        """Handle on-chain PositionClosed event"""
        async with AsyncSessionLocal() as session:
            account = await self.get_account(user_address, session)

            # Try to find by position_id first
            stmt = select(Position).where(Position.position_id == position_id_hex)
            result = await session.execute(stmt)
            position = result.scalar_one_or_none()

            # If not found by ID, try by user + OPEN status (assuming single position per user in contract if implied)
            # The event gives us user address, but not symbol. If we didn't save position_id, we might have trouble identifying which position closed
            # if the user has multiple positions.
            # However, PositionManager usually implies 1 position per symbol. We don't know the symbol here...
            # But wait, if we didn't save position_id, we can't efficiently find it without symbol.
            # We will rely on position_id being saved correctly on Open.

            if not position:
                # Fallback: Check if user has ONLY ONE open position?
                # Or just log error.
                print(
                    f"[Ledger] Warning: PositionClosed event for unknown position_id {position_id_hex}"
                )
                return

            print(
                f"[Ledger] Closing position {position.symbol} for {user_address} (PnL: {pnl})"
            )

            # Update Ledger
            account.balance += pnl
            account.locked_margin -= position.margin_used  # Release all margin
            account.available_balance = account.balance - account.locked_margin
            account.realized_pnl += pnl

            close_size = position.size
            close_side = position.side.lower()

            position.status = "CLOSED"
            position.closed_at = datetime.utcnow()
            position.margin_used = 0
            position.size = 0
            position.realized_pnl += pnl

            trade_record = Order(
                id=f"close_{position_id_hex}_{datetime.utcnow().timestamp()}",
                user_address=user_address.lower(),
                exchange=position.exchange,
                symbol=position.symbol,
                side=close_side,
                order_type="market",
                size=close_size,
                price=price,
                avg_fill_price=price,
                notional_usd=close_size * price,
                status="FILLED",
                realized_pnl=pnl,
                exchange_order_id=position_id_hex,
                created_at=datetime.utcnow(),
                filled_at=datetime.utcnow(),
            )
            session.add(trade_record)

            await session.commit()
            await self._notify_user(
                user_address,
                "trade_filled",
                meta={
                    "symbol": position.symbol,
                    "side": position.side,
                    "exchange": position.exchange,
                    "close_price": price,
                    "realized_pnl": pnl,
                },
            )

    async def process_trade_close(
        self,
        user_address: str,
        symbol: str,
        close_price: float,
        size_to_close: float = 0,
        exchange: str = "simulation",
    ):
        """Calculate PnL, unlock margin, update balance"""
        print(
            f"[Ledger.process_trade_close] Closing position for {symbol}, size_to_close={size_to_close}, exchange={exchange}"
        )

        async with AsyncSessionLocal() as session:
            account = await self.get_account(user_address, session)

            result = await session.execute(
                select(Position).where(
                    Position.user_address == user_address.lower(),
                    Position.symbol == symbol,
                    Position.exchange == exchange,
                    Position.status == "OPEN",
                )
            )
            positions = result.scalars().all()
            if not positions:
                print(f"[Ledger] No open position found for {symbol}")
                return

            if len(positions) > 1:
                # Defensive: DB may contain duplicate OPEN rows; pick the newest.
                positions = sorted(
                    positions,
                    key=lambda p: ((p.opened_at or datetime.min), (p.id or 0)),
                    reverse=True,
                )

            position = positions[0]

            # Determine size
            close_size = size_to_close if size_to_close > 0 else position.size
            if close_size > position.size:
                close_size = position.size

            # Calculate PnL
            # Long: (Exit - Entry) * Size
            # Short: (Entry - Exit) * Size
            diff = (
                (close_price - position.entry_price)
                if position.side.lower() == "long"
                else (position.entry_price - close_price)
            )
            pnl = diff * close_size

            # Calculate Margin to release
            # pro-rata margin
            margin_released = (close_size / position.size) * position.margin_used

            # Update Ledger
            account.balance += pnl
            account.locked_margin -= margin_released
            account.available_balance = account.balance - account.locked_margin
            account.realized_pnl += pnl

            # Update Position
            if close_size >= position.size - 1e-6:
                # Full Close
                position.status = "CLOSED"
                position.closed_at = datetime.utcnow()
                position.margin_used = 0
                position.size = 0
                position.realized_pnl += pnl
            else:
                # Partial Close
                position.size -= close_size
                position.margin_used -= margin_released
                position.realized_pnl += pnl

            # Record Trade
            # For close orders, we keep the ORIGINAL position side for display purposes
            # This makes it clear in history that we closed a LONG or SHORT position
            trade_record = Order(
                id=f"sim_close_{symbol}_{datetime.utcnow().timestamp()}",
                user_address=user_address.lower(),
                exchange="simulation",
                symbol=symbol,
                side=position.side.lower(),  # Keep original side (long/short) for clarity
                order_type="market",
                size=close_size,
                price=close_price,
                avg_fill_price=close_price,
                notional_usd=close_size * close_price,
                status="FILLED",
                realized_pnl=pnl,
                created_at=datetime.utcnow(),
                filled_at=datetime.utcnow(),
            )
            session.add(trade_record)

            await session.commit()
            print(f"[Ledger] Closed {symbol} PnL: {pnl} USDC")

            # Heuristic liquidation signal: close happened very near liquidation price.
            liquidation_price = float(position.liquidation_price or 0)
            is_full_close = close_size >= (close_size + float(position.size or 0)) - 1e-6
            is_near_liq = (
                liquidation_price > 0
                and close_price > 0
                and abs(close_price - liquidation_price) / liquidation_price <= 0.0025
            )
            event_type = "liquidation" if (is_full_close and is_near_liq) else "trade_closed"
            await self._notify_user(
                user_address,
                event_type,
                meta={
                    "symbol": symbol,
                    "side": position.side,
                    "exchange": exchange,
                    "close_price": close_price,
                    "realized_pnl": pnl,
                    "liquidation_price": liquidation_price if liquidation_price > 0 else None,
                },
            )

    async def update_position_unrealized_pnl(
        self,
        user_address: str,
        symbol: str,
        mark_price: float,
        exchange: str = "simulation",
    ):
        """Update unrealized PnL for a position based on current mark price"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Position)
                .where(
                    Position.user_address == user_address.lower(),
                    Position.symbol == symbol,
                    Position.exchange == exchange,
                    Position.status == "OPEN",
                )
                .order_by(Position.id)
                .limit(1)
            )
            positions = result.scalars().all()

            if not positions:
                return

            position = positions[0]

            # Calculate unrealized PnL
            is_long = position.side.lower() == "long"
            if is_long:
                pnl = (mark_price - position.entry_price) * position.size
            else:
                pnl = (position.entry_price - mark_price) * position.size

            # Update position unrealized PnL
            position.unrealized_pnl = pnl

            # Calculate ROI percentage
            if position.margin_used > 0:
                position.unrealized_pnl_percent = (pnl / position.margin_used) * 100

            await session.commit()

            # Notify user of position update
            await self._notify_user(user_address, "position_update")


ledger_service = LedgerService()
