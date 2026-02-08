
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import datetime
import uuid

from database.connection import AsyncSessionLocal
from database.models import LedgerAccount, Position, Order, FundingHistory
from storage.redis_manager import redis_manager
import json

class LedgerService:
    """
    Manages the Off-Chain Ledger State.
    Source of Truth for User Balances and Positions in Hybrid Mode.
    """

    async def get_account(self, user_address: str, session: Session) -> LedgerAccount:
        """Get or create ledger account"""
        result = await session.execute(
            select(LedgerAccount).where(LedgerAccount.address == user_address.lower())
        )
        account = result.scalar_one_or_none()
        if not account:
            account = LedgerAccount(address=user_address.lower())
            session.add(account)
            await session.flush() # Ensure ID is available
        return account

    async def _notify_user(self, user_address: str, event_type: str = "account_update"):
        """Publish notification to Redis for WebSocket broadcast"""
        try:
            # We fetch latest positions & summary to send the full state for "instant" update
            from services.order_service import OrderService
            order_service = OrderService()
            state = await order_service.get_user_positions(user_address)
            
            message = {
                "type": event_type,
                "address": user_address.lower(),
                "data": state
            }
            await redis_manager.publish(f"user_notifications:{user_address.lower()}", message)
        except Exception as e:
            print(f"[Ledger] Failed to notify user {user_address}: {e}")

    async def process_deposit(self, user_address: str, amount: float, tx_hash: str):
        """Credit user balance from on-chain deposit"""
        async with AsyncSessionLocal() as session:
            account = await self.get_account(user_address, session)
            
            # Check for duplicate processing
            exists = await session.execute(select(FundingHistory).where(FundingHistory.tx_hash == tx_hash))
            if exists.scalar_one_or_none():
                return

            # Update Balance
            account.balance += amount
            account.available_balance = account.balance - account.locked_margin
            
            # Record History
            history = FundingHistory(
                user_address=user_address.lower(),
                type='Deposit',
                asset='USDC',
                amount=amount,
                tx_hash=tx_hash,
                status='Completed'
            )
            session.add(history)
            await session.commit()
            print(f"[Ledger] Deposited {amount} USDC for {user_address}")
            await self._notify_user(user_address, "deposit_confirmed")

    async def process_withdrawal(self, user_address: str, amount: float, tx_hash: str):
        """Debit user balance from on-chain withdrawal"""
        async with AsyncSessionLocal() as session:
            account = await self.get_account(user_address, session)
            
            exists = await session.execute(select(FundingHistory).where(FundingHistory.tx_hash == tx_hash))
            if exists.scalar_one_or_none():
                return

            account.balance -= amount
            account.available_balance = account.balance - account.locked_margin
            
            history = FundingHistory(
                user_address=user_address.lower(),
                type='Withdraw',
                asset='USDC',
                amount=amount,
                tx_hash=tx_hash,
                status='Completed'
            )
            session.add(history)
            await session.commit()
            print(f"[Ledger] Withdrawn {amount} USDC for {user_address}")
            await self._notify_user(user_address, "withdrawal_confirmed")

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
        exchange: str = 'simulation',
        tp: str = None,
        sl: str = None,
    ):
        """Lock margin and open/increase position"""
        
        async with AsyncSessionLocal() as session:
            # Normalize side
            norm_side = 'long' if side.lower() in ('buy', 'long') else 'short'
            
            account = await self.get_account(user_address, session)
            
            # Update Ledger
            account.locked_margin += margin_used
            account.available_balance = account.balance - account.locked_margin
            
            # Create/Update Position
            # Logic to merge if exists
            result = await session.execute(
                select(Position).where(
                    Position.user_address == user_address.lower(),
                    Position.symbol == symbol,
                    Position.exchange == exchange,
                    Position.status == 'OPEN'
                )
            )
            position = result.scalar_one_or_none()
            
            if position:
                # Merge logic (weighted avg entry)
                total_size = position.size + size_token
                new_entry = ((position.entry_price * position.size) + (entry_price * size_token)) / total_size
                
                position.entry_price = new_entry
                position.size = total_size
                position.margin_used += margin_used
                if tp is not None:
                    position.tp = str(tp)
                if sl is not None:
                    position.sl = str(sl)
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
                    status='OPEN',
                    position_id=position_id
                )
                session.add(position)
                
            # Update Order Status or Create Shadow Order
            if order_id:
                # Try to find by UUID (standard) or transaction hash/contract order id
                from sqlalchemy import or_
                o_res = await session.execute(
                    select(Order).where(
                        or_(
                            Order.id == order_id,
                            Order.exchange_order_id == order_id
                        )
                    )
                )
                order = o_res.scalar_one_or_none()
                
                if not order:
                    # Create Shadow Order from On-Chain Event
                    order = Order(
                        id=order_id,
                        user_address=user_address.lower(),
                        exchange=exchange,
                        symbol=symbol,
                        side=side.lower(), # Keep original side for Order record (buy/sell)
                        order_type='market', # Assumed for now
                        size=size_token,
                        price=entry_price,
                        leverage=leverage,
                        notional_usd=size_token * entry_price, # Calculated notional
                        status='FILLED',
                        created_at=datetime.utcnow()
                    )
                    session.add(order)
                
                else:
                    order.status = 'FILLED'
                    order.filled_at = datetime.utcnow()
                    order.filled_size = size_token
                    order.avg_fill_price = entry_price
            
            await session.commit()
            print(f"[Ledger] Opened/Increased {side} {symbol} for {user_address}")
            await self._notify_user(user_address, "trade_filled")

    async def process_position_close_event(
        self,
        position_id_hex: str,
        user_address: str,
        price: float,
        pnl: float
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
                print(f"[Ledger] Warning: PositionClosed event for unknown position_id {position_id_hex}")
                return

            print(f"[Ledger] Closing position {position.symbol} for {user_address} (PnL: {pnl})")
            
            # Update Ledger
            account.balance += pnl
            account.locked_margin -= position.margin_used # Release all margin
            account.available_balance = account.balance - account.locked_margin
            account.realized_pnl += pnl
            
            # Close Position
            position.status = 'CLOSED'
            position.closed_at = datetime.utcnow()
            position.margin_used = 0
            position.size = 0
            position.realized_pnl += pnl
            
            # Record Trade in Order History (Shadow Order for Close)
            trade_record = Order(
                id=f"close_{position_id_hex}_{datetime.utcnow().timestamp()}",
                user_address=user_address.lower(),
                exchange=position.exchange,
                symbol=position.symbol,
                side='sell' if position.side.lower() == 'long' else 'buy',
                order_type='market',
                size=0, # or original size? usually we show close size here
                price=price,
                avg_fill_price=price,
                notional_usd=0, # Can calc if needed
                status='FILLED',
                realized_pnl=pnl,
                exchange_order_id=position_id_hex,
                created_at=datetime.utcnow(),
                filled_at=datetime.utcnow()
            )
            session.add(trade_record)
            
            await session.commit()
            await self._notify_user(user_address, "trade_filled")

    async def process_trade_close(
        self,
        user_address: str,
        symbol: str,
        close_price: float,
        size_to_close: float = 0
    ):
        """Calculate PnL, unlock margin, update balance"""
        async with AsyncSessionLocal() as session:
            account = await self.get_account(user_address, session)
            
            result = await session.execute(
                select(Position).where(
                    Position.user_address == user_address.lower(),
                    Position.symbol == symbol,
                    Position.status == 'OPEN'
                )
            )
            position = result.scalar_one_or_none()
            
            if not position:
                print(f"[Ledger] No open position found for {symbol}")
                return

            # Determine size
            close_size = size_to_close if size_to_close > 0 else position.size
            if close_size > position.size:
                close_size = position.size
                
            # Calculate PnL
            # Long: (Exit - Entry) * Size
            # Short: (Entry - Exit) * Size
            diff = (close_price - position.entry_price) if position.side.lower() == 'long' else (position.entry_price - close_price)
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
                position.status = 'CLOSED'
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
            trade_record = Order(
                id=f"sim_close_{symbol}_{datetime.utcnow().timestamp()}",
                user_address=user_address.lower(),
                exchange='simulation',
                symbol=symbol,
                side='sell' if position.side.lower() == 'long' else 'buy',
                order_type='market',
                size=close_size,
                price=close_price,
                avg_fill_price=close_price,
                notional_usd=close_size * close_price,
                status='FILLED',
                realized_pnl=pnl,
                created_at=datetime.utcnow(),
                filled_at=datetime.utcnow()
            )
            session.add(trade_record)
            
            await session.commit()
            print(f"[Ledger] Closed {symbol} PnL: {pnl} USDC")
            await self._notify_user(user_address, "trade_closed")

ledger_service = LedgerService()
