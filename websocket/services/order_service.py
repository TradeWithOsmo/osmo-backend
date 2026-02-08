"""
Order Service - Business Logic Layer

Orchestrates order placement, validation, and routing across exchanges.
"""

from typing import Dict, Any, List, Optional
import uuid
from datetime import datetime
import sys
import os

from database.models import Order, Position
from database.connection import AsyncSessionLocal
from connectors.init_connectors import connector_registry


class OrderService:
    """
    Core business logic for order management.
    Exchange-agnostic orchestration layer.
    """

    @staticmethod
    def _normalize_tpsl_value(value: Optional[Any]) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            if float(value).is_integer():
                return str(int(value))
            return str(float(value))
        return str(value).strip()
    
    async def place_order(
        self,
        user_address: str,
        symbol: str,
        side: str,
        order_type: str,
        amount_usd: float,
        leverage: int = 1,
        price: float = None,
        stop_price: float = None,
        tp: float = None,
        sl: float = None,
        exchange: str = None,
        reduce_only: bool = False,
        post_only: bool = False,
        time_in_force: str = 'GTC',
        trigger_condition: str = None
    ) -> Dict[str, Any]:
        """
        Unified order placement across exchanges.
        
        Args:
            user_address: User's wallet address
            symbol: Trading pair (BTC-USD, EURUSD)
            side: 'buy' or 'sell'
            order_type: 'market', 'limit', 'stop_limit'
            amount_usd: Position size in USD
            leverage: Leverage multiplier
            price: Limit price (for limit orders)
            stop_price: Stop trigger price
            exchange: Force specific exchange, or auto-detect from symbol
            reduce_only: Close position only (default False)
            post_only: Limit order only (default False)
            time_in_force: 'GTC', 'IOC', 'FOK' (default 'GTC')
        
        Returns:
            Order record with status
        """
        
        # 1. Auto-detect exchange if not specified
        if not exchange:
            exchange = self._detect_exchange(symbol)

        tp_value = self._normalize_tpsl_value(tp)
        sl_value = self._normalize_tpsl_value(sl)
        
        if exchange == 'simulation':
             # Simulation doesn't need a connector
             connector = None
        else:
            # 2. Get connector
            connector = connector_registry.get_connector(exchange)
            if not connector:
                raise ValueError(f"Exchange {exchange} not found or not initialized")
        
        # 3. Validate order (risk checks)
        await self._validate_order(user_address, symbol, amount_usd, leverage)
        
        # 4. Calculate position size (Legacy Connector Path)
        current_price = 0
        size = 0
        
        if connector:
            try:
                market_data = await connector.fetch(symbol.split('-')[0], data_type='price')
                current_price = float(market_data.get('data', {}).get('price', 0))
            except Exception as e:
                print(f"[OrderService] Warning: Could not fetch price for {symbol}: {e}")
                current_price = 0
            
            if current_price == 0:
                # If price is provided in arguments (Limit Order), use it?
                if price and price > 0:
                    current_price = price
                else:
                    raise ValueError(f"Cannot fetch current price for {symbol}")
            
            # Size calculation
            if exchange == 'hyperliquid':
                # Crypto: size = USD / price
                size = amount_usd / current_price
            elif exchange == 'onchain':
                # On-chain: size is AmountUSD (collateral)
                size = amount_usd
            else:
                # Ostium RWA: notional in USD
                size = amount_usd
        
        if exchange == 'simulation':
            # Simulation Mode: Interact directly with LedgerService
            from services.ledger_service import ledger_service
            
            # Checks
            if not price or price <= 0:
                 # Market Order Price Fetch
                 try:
                     p_conn = connector_registry.get_connector('hyperliquid')
                     if not p_conn: p_conn = connector_registry.get_connector('ostium')
                     if p_conn:
                         md = await p_conn.fetch(symbol.split('-')[0], data_type='price')
                         current_price = float(md.get('data', {}).get('price', 0))
                     else:
                         current_price = 0
                 except:
                     current_price = 0
                 
                 if current_price <= 0:
                     raise ValueError(f"Could not fetch price for simulation")
            else:
                current_price = price

            # Calculate Tokens
            size_tokens = (amount_usd / current_price) if current_price > 0 else 0
            margin_used = amount_usd / leverage if leverage > 0 else amount_usd

            # Execute via Ledger (OR Match Engine for Limit/Stop)
            order_id = str(uuid.uuid4())
            is_pending = order_type in ['limit', 'stop_market', 'stop_limit']
            
            if is_pending:
                 # It's a Pending Order.
                 # Do NOT call ledger_service.process_trade_open yet.
                 # Just return 'pending' status. The matching_engine will pick it up.
                 
                 # NOTE: Ideally we should lock margin here to prevent overspending, 
                 # but for V1 we check margin on Fill.
                 
                 # Create DB Record is handled below (outside this block).
                 # We just set response to Pending.
                 exchange_response = {
                     "status": "pending", # or 'open'
                     "exchange_order_id": f"sim_{order_id[:8]}"
                 }
                 # We still calculate size/margin for reference in the Order record
                 size = size_tokens
                 
            else:
                # Market Order -> Instant Fill
                await ledger_service.process_trade_open(
                    user_address=user_address,
                    symbol=symbol,
                    side=side,
                    size_token=size_tokens,
                    entry_price=current_price,
                    leverage=leverage,
                    margin_used=margin_used,
                    order_id=order_id,
                    tp=tp_value,
                    sl=sl_value,
                )
                
                # Mock Response
                exchange_response = {
                    "status": "filled", 
                    "exchange_order_id": f"sim_{order_id[:8]}"
                }
                size = size_tokens
            
            # Mock Response Logic moved inside if/else block above

        else: 
            # 5. Submit to exchange
            try:
                exchange_response = await connector.place_order(
                    user_address=user_address,
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    size=size,
                    price=price,
                    stop_price=stop_price,
                    leverage=leverage,
                    reduce_only=reduce_only,
                    post_only=post_only,
                    time_in_force=time_in_force,
                    trigger_condition=trigger_condition
                )
            except NotImplementedError as e:
                # Handle Ostium not implemented gracefully
                raise ValueError(f"Order placement not supported on {exchange}: {str(e)}")
        
        # 6. Store in database
        # If order_id was generated in simulation, use it. But wait, ledger_service might have already created the record!
        # If ledger_service created it, we should Check existence or Update, not just Add.
        
        # Actually, simpler: If exchange == 'simulation', we assume ledger_service created the order record.
        # But we might want to update it with more details if ledger_service created a minimal one?
        # ledger_service creates a fairly complete one now.
        
        if exchange == 'simulation':
            # Skip duplicate insertion, but ensure ID corresponds to return value
            # The order_id variable in the simulation block is local to that scope in Python 3? No, function scope.
            # But line 174 `order_id = str(uuid.uuid4())` unconditionally overwrites it.
            
            # Let's recover the simulation order ID if set
            # We need to restructure slightly to not overwrite order_id
            pass
        else:
             order_id = str(uuid.uuid4())
             
        # Refactored Logic:
        if exchange == 'simulation':
            # Ledger service created the order if MARKET/FILLED. 
            # If PENDING, we skipped ledger call, so we MUST create the order record here.
            
            is_pending = exchange_response.get('status') == 'pending'
            
            if is_pending:
                 # Create Pending Order Record
                 async with AsyncSessionLocal() as session:
                    order = Order(
                        id=order_id, # This is the UUID from simulation block
                        user_address=user_address.lower(),
                        exchange=exchange,
                        symbol=symbol,
                        side=side,
                        order_type=order_type,
                        price=price,
                        stop_price=stop_price,
                        size=size,
                        notional_usd=amount_usd,
                        leverage=leverage,
                        reduce_only=reduce_only,
                        post_only=post_only,
                        time_in_force=time_in_force,
                        status='OPEN', # Use OPEN for pending orders
                        created_at=datetime.utcnow(),
                        filled_size=0,
                        trigger_condition='BELOW' if side == 'sell' else 'ABOVE', # Simple heuristic for now
                        trigger_price=stop_price
                    )
                    session.add(order)
                    await session.commit()

            if tp_value is not None or sl_value is not None:
                await self.update_position_tpsl(
                    user_address=user_address,
                    symbol=symbol,
                    tp=tp_value,
                    sl=sl_value,
                    exchange=exchange,
                )
            
            return {
                "order_id": order_id,
                "exchange": exchange,
                "symbol": symbol,
                "status": exchange_response.get('status'),
                "exchange_order_id": exchange_response.get('exchange_order_id'),
                "message": "Order placed on simulation"
            }

        # For non-simulation, we continue to insert.
        order_id = str(uuid.uuid4())
        async with AsyncSessionLocal() as session:
             # ... existing insert logic ...
            order = Order(
                id=order_id,
                user_address=user_address.lower(),
                exchange=exchange,
                symbol=symbol,
                side=side,
                order_type=order_type,
                price=price,
                stop_price=stop_price,
                size=size,
                notional_usd=amount_usd,
                leverage=leverage,
                reduce_only=reduce_only,
                post_only=post_only,
                time_in_force=time_in_force,
                status=exchange_response.get('status', 'pending'),
                exchange_order_id=exchange_response.get('exchange_order_id'),
                created_at=datetime.utcnow(),
                # Populate fill details if filled (Simulation)
                filled_at=datetime.utcnow() if exchange_response.get('status') == 'filled' else None,
                filled_size=size if exchange_response.get('status') == 'filled' else 0,
                avg_fill_price=price if exchange_response.get('status') == 'filled' else None
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
        
        # 7. Optimistic Shadow Update for On-chain
        if exchange == 'onchain':
            try:
                # We reuse the logic from report_onchain_order to update shadow position record
                await self.report_onchain_order(
                    user_address=user_address,
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    amount_usd=amount_usd,
                    leverage=leverage,
                    tx_hash=order.exchange_order_id,
                    price=price,
                    tp=tp_value,
                    sl=sl_value,
                    exchange=exchange
                )
            except Exception as e:
                print(f"[OrderService] Warning: Failed to update optimistic shadow position: {e}")

        if tp_value is not None or sl_value is not None:
            try:
                await self.update_position_tpsl(
                    user_address=user_address,
                    symbol=symbol,
                    tp=tp_value,
                    sl=sl_value,
                    exchange=exchange,
                )
            except Exception as e:
                print(f"[OrderService] Warning: Failed to persist TP/SL on {exchange}: {e}")

        return {
            "order_id": order_id,
            "exchange": exchange,
            "symbol": symbol,
            "status": order.status,
            "exchange_order_id": order.exchange_order_id,
            "message": f"Order placed on {exchange}"
        }
    
    async def report_onchain_order(
        self,
        user_address: str,
        symbol: str,
        side: str,
        order_type: str,
        amount_usd: float,
        leverage: int = 1,
        tx_hash: str = None,
        price: float = None,
        stop_price: float = None,
        tp: Optional[Any] = None,
        sl: Optional[Any] = None,
        exchange: str = 'onchain'
    ) -> Dict[str, Any]:
        """
        Record a successful on-chain transaction reported by frontend.
        Creates a 'shadow' order and position for immediate tracking.
        """
        order_id = str(uuid.uuid4())
        tp_value = self._normalize_tpsl_value(tp)
        sl_value = self._normalize_tpsl_value(sl)
        
        async with AsyncSessionLocal() as session:
            # 0. Fetch current price if not provided (for market orders)
            if not price or price <= 0:
                try:
                    price_exchange = self._detect_exchange(symbol)
                    connector = connector_registry.get_connector(price_exchange)
                    if connector:
                        base_coin = symbol.split('-')[0]
                        market_data = await connector.fetch(base_coin, data_type='price')
                        price = float(market_data.get('data', {}).get('price', 0))
                except Exception as e:
                    print(f"[OrderService] Warning: Could not fetch price for shadow {symbol}: {e}")

            # Calculate token size (amount_usd / price)
            size_tokens = (amount_usd / price) if price and price > 0 else 0
            
            # 1. Save Order Record
            order = Order(
                id=order_id,
                user_address=user_address.lower(),
                exchange=exchange,
                symbol=symbol,
                side=side,
                order_type=order_type,
                price=price,
                stop_price=stop_price,
                size=size_tokens, 
                notional_usd=amount_usd,
                leverage=leverage,
                status='confirmed', # Confirmed on blockchain
                exchange_order_id=tx_hash,
                created_at=datetime.utcnow()
            )
            session.add(order)
            
            # 2. Check if we should create a shadow position record
            # This ensures the position shows up even if indexing is slow
            # First, check if a position already exists for this symbol
            from sqlalchemy import select
            pos_result = await session.execute(
                select(Position).where(
                    Position.user_address == user_address.lower(),
                    Position.symbol == symbol,
                    Position.exchange == exchange
                )
            )
            position = pos_result.scalar_one_or_none()
            
            if not position:
                # Create a new shadow position
                position = Position(
                    user_address=user_address.lower(),
                    symbol=symbol,
                    exchange=exchange,
                    side='long' if side == 'buy' else 'short',
                    size=size_tokens,
                    entry_price=price or 0, # Best guess if price wasn't provided (market)
                    leverage=leverage,
                    margin_used=amount_usd / leverage if leverage > 0 else amount_usd,
                    tp=tp_value,
                    sl=sl_value,
                    opened_at=datetime.utcnow(),
                    status='OPEN'  # Important: Force open for shadow position
                )
                session.add(position)
            else:
                # Update existing shadow position
                
                # Check if we are opening fresh or updating
                if position.status != 'OPEN':
                    # treat as new
                    position.side = 'long' if side == 'buy' else 'short'
                    position.size = size_tokens
                    position.entry_price = price or 0
                    position.margin_used = amount_usd / leverage if leverage > 0 else amount_usd
                    position.opened_at = datetime.utcnow()
                    position.status = 'OPEN'
                    # Reset generic fields if needed
                else:
                    # Netting Logic
                    incoming_side = 'long' if side == 'buy' else 'short'
                    
                    if position.side == incoming_side:
                        # Increase Position
                        # Weighted Average Entry Price
                        total_size = position.size + size_tokens
                        if total_size > 0:
                            position.entry_price = ((position.entry_price * position.size) + (price * size_tokens)) / total_size
                        
                        position.size = total_size
                        position.margin_used += (amount_usd / leverage if leverage > 0 else amount_usd)
                        
                    else:
                        # Decrease / Close / Flip Position
                        # Use epsilon for floating point comparison
                        if size_tokens >= position.size - 1e-6:
                            # Full Close or Flip
                            remaining = size_tokens - position.size
                            if remaining > 1e-6:
                                # Flip
                                position.side = incoming_side
                                position.size = remaining
                                position.entry_price = price or 0 # New price for the flip part
                                position.margin_used = (remaining * price) / leverage if leverage > 0 else 0 
                                # (Approx margin calc for flip)
                            else:
                                # Optimistic: Keep it OPEN so it doesn't disappear from UI
                                # But mark the closing timestamp
                                position.closed_at = datetime.utcnow()
                                # We don't set size to 0 yet, let the indexer do the real update.
                                # This prevents the "hidden" position issue.
                                pass
                        else:
                            # Partial Close
                            position.size -= size_tokens
                            # Entry price doesn't change on reduce
                            # Margin reduces proportionally
                            if position.size > 0:
                                position.margin_used = position.margin_used * (1 - (size_tokens / position.size))

                position.updated_at = datetime.utcnow()
                if tp_value is not None:
                    position.tp = tp_value
                if sl_value is not None:
                    position.sl = sl_value
                
            await session.commit()
            
        return {
            "order_id": order_id,
            "status": "reported",
            "message": "Order reported and shadow record created"
        }

    def _detect_exchange(self, symbol: str) -> str:
        """Auto-detect exchange from symbol"""
        # Crypto symbols → Hyperliquid
        # TODO: Better detection logic or mapping table
        crypto_symbols = ['BTC', 'ETH', 'SOL', 'LINK', 'AVAX', 'MATIC', 'ARB', 'DOGE', 'ATOM']
        
        # Check if symbol starts with crypto ticker
        for coin in crypto_symbols:
            if symbol.startswith(coin):
                # If explicit onchain requested via symbol convention (e.g. BTC-USD-ONCHAIN)
                if 'ONCHAIN' in symbol.upper():
                    return 'onchain'
                return 'hyperliquid'
        
        # Everything else → Ostium (RWA)
        return 'ostium'
    
    async def _validate_order(
        self, 
        user_address: str, 
        symbol: str, 
        amount_usd: float, 
        leverage: int
    ):
        """
        Validate order against risk limits.
        
        Note: This is a SANITY CHECK layer. Actual leverage enforcement 
        is done by the exchanges themselves:
        - Hyperliquid: Max leverage per coin (3x-50x) + margin tiers
        - Ostium: Max leverage per market (typically 50x)
        - Onchain: Max leverage defined in RiskManager contract
        
        We only validate obvious errors before submitting to exchange.
        """
        
        # Sanity check: Leverage too high (exchange will enforce actual limits)
        if leverage > 100:
            raise ValueError("Leverage sanity check failed: max 100x")
        
        # Minimum order size
        if amount_usd < 10:
            raise ValueError("Minimum order size is $10")
        
        # TODO: Implement additional validation
        # - Check user balance
        # - Check daily volume limits
        # - Query exchange max leverage for symbol (optional pre-check)
        pass
    
    async def cancel_order(
        self, 
        user_address: str, 
        order_id: str
    ) -> Dict[str, Any]:
        """Cancel pending order"""
        
        async with AsyncSessionLocal() as session:
            # Fetch order from DB
            from sqlalchemy import select
            result = await session.execute(
                select(Order).where(
                    Order.id == order_id,
                    Order.user_address == user_address.lower()
                )
            )
            order = result.scalar_one_or_none()
            
            if not order:
                raise ValueError(f"Order {order_id} not found")
            
            if order.status not in ['pending', 'open', 'confirmed']:
                raise ValueError(f"Cannot cancel order with status {order.status}")
            
            # Get connector
            connector = connector_registry.get_connector(order.exchange)
            
            # Cancel on exchange
            try:
                await connector.cancel_order(user_address, order.exchange_order_id)
            except NotImplementedError:
                raise ValueError(f"Order cancellation not supported on {order.exchange}")
            except Exception as e:
                # Log error but maybe mark as failed?
                print(f"[OrderService] Cancellation failed: {e}")
                raise e
            
            # Update DB
            order.status = 'cancelled'
            order.updated_at = datetime.utcnow()
            await session.commit()
        
        return {"order_id": order_id, "status": "cancelled"}
    
    async def get_user_orders(
        self, 
        user_address: str, 
        status: str = None
    ) -> List[Dict]:
        """Get user's order history across all exchanges and DB"""
        
        all_orders = []
        db_order_ids = set()

        # 1. Fetch from DB (Shadow & History)
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select, or_
            
            stmt = select(Order).where(Order.user_address == user_address.lower())
            
            if status:
                if status.lower() == 'pending':
                    stmt = stmt.where(Order.status.in_(['pending', 'open', 'confirmed']))
                elif status.lower() == 'history':
                    stmt = stmt.where(Order.status.in_(['filled', 'cancelled', 'rejected', 'FILLED', 'CANCELLED']))
                elif status.lower() == 'filled':
                    stmt = stmt.where(Order.status.in_(['filled', 'FILLED']))
                else:
                    stmt = stmt.where(Order.status == status)
            
            stmt = stmt.order_by(Order.created_at.desc())
            
            result = await session.execute(stmt)
            db_orders = result.scalars().all()
            
            for order in db_orders:
                all_orders.append({
                    "id": order.id,
                    "exchange": order.exchange,
                    "symbol": order.symbol,
                    "side": order.side,
                    "order_type": order.order_type,
                    "size": order.size,
                    "notional_usd": order.notional_usd,
                    "price": order.price,
                    "stop_price": order.stop_price,
                    "leverage": order.leverage,
                    "status": order.status,
                    "filled_size": order.filled_size,
                    "avg_fill_price": order.avg_fill_price,
                    "exchange_order_id": order.exchange_order_id,
                    "realized_pnl": order.realized_pnl,
                    "created_at": order.created_at.isoformat() if order.created_at else None,
                    "filled_at": order.filled_at.isoformat() if order.filled_at else None
                })
                if order.exchange_order_id:
                    db_order_ids.add(order.exchange_order_id.lower())
                db_order_ids.add(order.id.lower())

        # 2. Query On-chain connector for real-time status (Disabled temporarily to fix hang)
        # onchain_connector = connector_registry.get_connector('onchain')
        # if onchain_connector:
        #     try:
        #         onchain_orders = await onchain_connector.get_user_orders(user_address, status)
        #         for o in onchain_orders:
        #             # Deduplicate if already in DB (using exchange_order_id or id)
        #             oid = o.get('id', '').lower()
        #             eoid = o.get('exchange_order_id', '').lower()
        #             if oid not in db_order_ids and eoid not in db_order_ids:
        #                 # Normalize to DB format
        #                 all_orders.append({
        #                     "id": o['id'],
        #                     "exchange": 'onchain',
        #                     "symbol": o['symbol'],
        #                     "side": o['side'],
        #                     "order_type": o.get('type', 'market'),
        #                     "size": o.get('size', 0),
        #                     "notional_usd": o.get('amount_usd', 0),
        #                     "price": o['price'],
        #                     "stop_price": None,
        #                     "leverage": o['leverage'],
        #                     "status": o['status'],
        #                     "filled_size": 0,
        #                     "avg_fill_price": 0,
        #                     "exchange_order_id": o['id'],
        #                     "created_at": None,
        #                     "filled_at": None
        #                 })
        #     except Exception as e:
        #         print(f"[OrderService] Error fetching On-chain orders: {e}")

        return all_orders
    
    async def get_user_positions(
        self, 
        user_address: str
    ) -> Dict[str, Any]:
        """Get user's active positions across all exchanges with account summary"""
        
        all_positions = []
        successful_exchanges = set()
        overall_summary = {
            "account_value": 0,
            "total_margin_used": 0,
            "free_collateral": 0,
            "margin_usage": 0,
            "leverage": 0
        }
        
        # Query Hyperliquid positions
        hl_connector = connector_registry.get_connector('hyperliquid')
        if hl_connector:
            try:
                hl_data = await hl_connector.get_user_positions(user_address)
                hl_positions = hl_data.get('positions', [])
                hl_summary = hl_data.get('summary', {})
                
                for pos in hl_positions:
                    pos['exchange'] = 'hyperliquid'
                    all_positions.append(pos)
                
                # Aggregate HL summary
                overall_summary["account_value"] += hl_summary.get("account_value", 0)
                overall_summary["total_margin_used"] += hl_summary.get("total_margin_used", 0)
                overall_summary["free_collateral"] += hl_summary.get("free_collateral", 0)
                
                successful_exchanges.add('hyperliquid')
            except Exception as e:
                print(f"[OrderService] Error fetching Hyperliquid positions: {e}")
        
        # Query Ostium positions
        ostium_connector = connector_registry.get_connector('ostium')
        if ostium_connector:
            try:
                # Ostium currently returns a list (NotImplementedError usually)
                ostium_result = await ostium_connector.get_user_positions(user_address)
                if isinstance(ostium_result, list):
                    for pos in ostium_result:
                        pos['exchange'] = 'ostium'
                        all_positions.append(pos)
                elif isinstance(ostium_result, dict):
                    # If it later returns summary
                    for pos in ostium_result.get('positions', []):
                        pos['exchange'] = 'ostium'
                        all_positions.append(pos)
                    # Aggregate summary if available
                    # ...
                successful_exchanges.add('ostium')
            except NotImplementedError:
                pass
            except Exception as e:
                print(f"[OrderService] Error fetching Ostium positions: {e}")

        # Query On-chain positions
        onchain_connector = connector_registry.get_connector('onchain')
        if onchain_connector:
            try:
                onchain_balances = {}
                # 1. Get Balances
                if hasattr(onchain_connector, 'get_user_balances'):
                    onchain_balances = await onchain_connector.get_user_balances(user_address)
                    overall_summary["account_value"] += onchain_balances.get("account_value", 0)
                    overall_summary["free_collateral"] += onchain_balances.get("free_collateral", 0)
                    overall_summary["total_margin_used"] += onchain_balances.get("total_margin_used", 0)
        
                # 2. Get Positions
                onchain_result = await onchain_connector.get_user_positions(user_address)
                for pos in onchain_result:
                    pos['exchange'] = 'onchain'
                    all_positions.append(pos)
                successful_exchanges.add('onchain')
                print(f"[OrderService] On-chain Summary for {user_address}: {onchain_balances}")
            except Exception as e:
                print(f"[OrderService] Error fetching On-chain positions/balances: {e}")

        # Query Local Ledger Balance (Simulation/Hybrid Mode)
        # We SYNC the ledger balance with the on-chain vault balance to ensure they are the same.
        # This prevents double-counting and ensures simulation trades use 'real' collateral levels.
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select
                from database.models import LedgerAccount
                acc_res = await session.execute(
                    select(LedgerAccount).where(LedgerAccount.address == user_address.lower())
                )
                account = acc_res.scalar_one_or_none()
                
                if account:
                    # Sync Ledger with On-chain (if on-chain was successful)
                    if 'onchain' in successful_exchanges:
                        # Sync Ledger with On-chain
                        account.balance = onchain_balances.get("account_value", 0)
                        account.locked_margin = onchain_balances.get("total_margin_used", 0)
                        account.available_balance = onchain_balances.get("free_collateral", 0)
                        await session.commit()
                        print(f"[OrderService] Synced Ledger for {user_address} with On-chain: {account.balance}")
                        # We do NOT add to overall_summary here because on-chain already did.
                    else:
                        # On-chain not available/successful, so we use Ledger as the source for the summary
                        overall_summary["account_value"] += account.balance
                        overall_summary["free_collateral"] += account.available_balance
                        overall_summary["total_margin_used"] += account.locked_margin
                        print(f"[OrderService] Using Ledger for {user_address} summary (On-chain not successful)")
        except Exception as e:
            print(f"[OrderService] Error fetching/syncing LedgerAccount: {e}")


        
        # Query Local DB for Shadow Positions and TP/SL
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select
                db_result = await session.execute(
                    select(Position).where(Position.user_address == user_address.lower())
                )
                db_positions = db_result.scalars().all()
                
                # 1. Map symbols for TP/SL (for general use)
                tpsl_map = {p.symbol: {'tp': p.tp, 'sl': p.sl} for p in db_positions}

                # 2. Identify and merge Shadow Positions
                # We need to match DB positions with connector positions.
                # Since multiple positions can exist for same symbol (some connectors don't merge),
                # we track which connector positions have been "matched".
                matched_pos_ids = set()
                
                for db_pos in db_positions:
                    if db_pos.status != 'OPEN': continue # Skip closed positions

                    # Try to find a matching active position from a connector
                    found_active = False
                    for pos in all_positions:
                        # Match by symbol and exchange, and ensure it's not already matched
                        # Match by position_id (best), or symbol+exchange
                        match_id = (pos.get('id') == db_pos.position_id) if db_pos.position_id else False
                        match_symbol = (pos.get('symbol') == db_pos.symbol and pos.get('exchange') == db_pos.exchange)

                        if (match_id or match_symbol) and pos.get('id') not in matched_pos_ids:
                            
                            matched_pos_ids.add(pos.get('id'))
                            found_active = True
                            print(f"[OrderService] Merging DB position {db_pos.id} with active {pos.get('id')} ({pos.get('symbol')}) - Connector Size: {pos.get('size')} DB Size: {db_pos.size}")
                            
                            # Merge TP/SL
                            pos['tp'] = db_pos.tp
                            pos['sl'] = db_pos.sl
                            
                            # Fallback logic for indexing lag
                            if pos.get('entry_price', 0) == 0 and db_pos.entry_price > 0:
                                pos['entry_price'] = db_pos.entry_price
                            
                            if pos.get('size', 0) == 0 and db_pos.size > 0:
                                pos['size'] = db_pos.size
                                pos['size_tokens'] = db_pos.size
                                # Update position value if we have a mark price (or entry)
                                fallback_price = pos.get('mark_price') or pos.get('entry_price') or 0
                                pos['position_value'] = db_pos.size * fallback_price

                            # Recalculate Liquidation Price if we recovered the entry price
                            if pos.get('liquidation_price', 0) == 0:
                                try:
                                    s_usd = pos.get('position_value', 0)
                                    m_usd = pos.get('margin_used', 0)
                                    ep = pos.get('entry_price', 0)
                                    if s_usd > 0 and ep > 0 and m_usd > 0:
                                        max_loss_ratio = (m_usd * 0.8) / s_usd
                                        if pos.get('side') == 'long':
                                            pos['liquidation_price'] = ep * (1 - max_loss_ratio)
                                        else:
                                            pos['liquidation_price'] = ep * (1 + max_loss_ratio)
                                except Exception:
                                    pass
                            break # Found match for this db_pos, move to next
                    
                    if not found_active:
                        # 3. Handle Pure Shadow Positions (Found in DB but not in Connectors)
                        # Freshness Check: If we successfully queried the exchange connector 
                        # and this position wasn't found, it might be stale/closed.
                        # We only show it if it's very recent (last 60s) to allow for indexing lag.
                        if db_pos.exchange in successful_exchanges:
                            from datetime import timedelta
                            now = datetime.utcnow()
                            # Use opened_at or updated_at to check for freshness
                            ref_time = db_pos.updated_at or db_pos.opened_at or now
                            if now - ref_time > timedelta(seconds=60):
                                print(f"[OrderService] Skipping stale shadow position for {db_pos.symbol} on {db_pos.exchange} (ref_time: {ref_time})")
                                continue

                        # Create shadow position object
                        shadow_pos = {
                            "id": f"shadow_{db_pos.id}",
                            "symbol": db_pos.symbol,
                            "side": db_pos.side,
                            "size": db_pos.size,
                            "size_tokens": db_pos.size,
                            "entry_price": db_pos.entry_price,
                            "mark_price": db_pos.entry_price, # Placeholder
                            "unrealized_pnl": 0,
                            "leverage": db_pos.leverage,
                            "margin_used": db_pos.margin_used,
                            "exchange": db_pos.exchange,
                            "is_shadow": True,
                            "tp": db_pos.tp,
                            "sl": db_pos.sl
                        }
                        all_positions.append(shadow_pos)

        except Exception as e:
            print(f"[OrderService] Error merging shadow positions/TPSL: {e}")

        # Final calculations for aggregated summary
        if overall_summary["account_value"] > 0:
            overall_summary["margin_usage"] = (overall_summary["total_margin_used"] / overall_summary["account_value"]) * 100
            
            total_notional = 0
            for p in all_positions:
                # Simple estimation if not provided
                notional = p.get('size', 0) * p.get('mark_price', p.get('entry_price', 0))
                total_notional += notional
            overall_summary["leverage"] = total_notional / overall_summary["account_value"]

        return {
            "positions": all_positions,
            "summary": overall_summary
        }

    async def update_position_tpsl(
        self,
        user_address: str,
        symbol: str,
        tp: Optional[Any] = None,
        sl: Optional[Any] = None,
        exchange: str = None
    ) -> Dict[str, Any]:
        """Update TP/SL for a position"""

        tp_value = self._normalize_tpsl_value(tp)
        sl_value = self._normalize_tpsl_value(sl)
        
        if not exchange:
            exchange = self._detect_exchange(symbol)
            
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select
            
            # Find existing position record
            # Note: Since actual positions are often fetched from connectors, 
            # we might need to create a shadow record here if it doesn't exist yet 
            # (or if the syncer hasn't run).
            
            result = await session.execute(
                select(Position).where(
                    Position.user_address == user_address.lower(),
                    Position.symbol == symbol,
                    Position.exchange == exchange
                )
            )
            position = result.scalar_one_or_none()
            
            if not position:
                # Create shadow position for TP/SL storage
                # Values like size/entry_price might be 0 until synced
                position = Position(
                    user_address=user_address.lower(),
                    symbol=symbol,
                    exchange=exchange,
                    side='unknown', # Will be updated by syncer
                    size=0,
                    entry_price=0,
                    leverage=1,
                    margin_used=0,
                    tp=tp_value,
                    sl=sl_value
                )
                session.add(position)
            else:
                if tp_value is not None:
                    position.tp = tp_value
                if sl_value is not None:
                    position.sl = sl_value
                position.updated_at = datetime.utcnow()
            
            await session.commit()
            
            return {
                "symbol": symbol,
                "tp": position.tp,
                "sl": position.sl,
                "status": "updated"
            }

    def _normalize_position_side(self, side: Optional[str]) -> Optional[str]:
        raw = str(side or "").strip().lower()
        if raw in {"long", "buy"}:
            return "long"
        if raw in {"short", "sell"}:
            return "short"
        return None

    def _compute_tpsl_from_entry_pct(
        self,
        *,
        side: Optional[str],
        entry_price: Optional[float],
        tp_pct: Optional[float],
        sl_pct: Optional[float],
    ) -> Dict[str, Optional[str]]:
        normalized_side = self._normalize_position_side(side)
        try:
            entry = float(entry_price or 0)
        except Exception:
            entry = 0.0
        if entry <= 0 or normalized_side is None:
            return {"tp": None, "sl": None}

        tp_value: Optional[str] = None
        sl_value: Optional[str] = None

        if tp_pct is not None:
            ratio = max(0.0, float(tp_pct)) / 100.0
            tp_price = entry * (1.0 + ratio) if normalized_side == "long" else entry * (1.0 - ratio)
            tp_value = self._normalize_tpsl_value(tp_price)

        if sl_pct is not None:
            ratio = max(0.0, float(sl_pct)) / 100.0
            sl_price = entry * (1.0 - ratio) if normalized_side == "long" else entry * (1.0 + ratio)
            sl_value = self._normalize_tpsl_value(sl_price)

        return {"tp": tp_value, "sl": sl_value}

    async def update_all_positions_tpsl(
        self,
        user_address: str,
        tp: Optional[Any] = None,
        sl: Optional[Any] = None,
        tp_pct: Optional[float] = None,
        sl_pct: Optional[float] = None,
        exchange: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Bulk TP/SL update for all open positions.

        Modes:
        - Absolute replace via tp/sl
        - Entry-relative via tp_pct/sl_pct (percent from each position entry)
        """
        tp_value = self._normalize_tpsl_value(tp)
        sl_value = self._normalize_tpsl_value(sl)
        if tp_value is None and sl_value is None and tp_pct is None and sl_pct is None:
            raise ValueError("Provide tp/sl or tp_pct/sl_pct to adjust positions")

        positions_packet = await self.get_user_positions(user_address=user_address)
        positions = positions_packet.get("positions", []) if isinstance(positions_packet, dict) else []

        updated: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        for pos in positions:
            if not isinstance(pos, dict):
                continue

            symbol = str(pos.get("symbol") or "").strip()
            pos_exchange = str(pos.get("exchange") or "").strip() or None
            if not symbol:
                continue
            if exchange and pos_exchange and str(exchange).lower() != pos_exchange.lower():
                continue

            next_tp = tp_value
            next_sl = sl_value
            if tp_pct is not None or sl_pct is not None:
                computed = self._compute_tpsl_from_entry_pct(
                    side=pos.get("side"),
                    entry_price=pos.get("entry_price") or pos.get("mark_price"),
                    tp_pct=tp_pct,
                    sl_pct=sl_pct,
                )
                if tp_pct is not None:
                    next_tp = computed.get("tp")
                if sl_pct is not None:
                    next_sl = computed.get("sl")

            if next_tp is None and next_sl is None:
                skipped.append(
                    {
                        "symbol": symbol,
                        "exchange": pos_exchange,
                        "reason": "No valid TP/SL computed for this position",
                    }
                )
                continue

            try:
                result = await self.update_position_tpsl(
                    user_address=user_address,
                    symbol=symbol,
                    tp=next_tp,
                    sl=next_sl,
                    exchange=pos_exchange,
                )
                updated.append(
                    {
                        "symbol": symbol,
                        "exchange": pos_exchange,
                        "tp": result.get("tp"),
                        "sl": result.get("sl"),
                    }
                )
            except Exception as exc:
                errors.append({"symbol": symbol, "exchange": pos_exchange, "error": str(exc)})

        return {
            "status": "updated",
            "updated_count": len(updated),
            "skipped_count": len(skipped),
            "error_count": len(errors),
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }

order_service = OrderService()
