"""
Order Service - Business Logic Layer

Orchestrates order placement, validation, and routing across exchanges.
"""

from typing import Dict, Any, List
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
        exchange: str = None
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
        
        Returns:
            Order record with status
        """
        
        # 1. Auto-detect exchange if not specified
        if not exchange:
            exchange = self._detect_exchange(symbol)
        
        # 2. Get connector
        connector = connector_registry.get_connector(exchange)
        if not connector:
            raise ValueError(f"Exchange {exchange} not found or not initialized")
        
        # 3. Validate order (risk checks)
        await self._validate_order(user_address, symbol, amount_usd, leverage)
        
        # 4. Calculate position size
        # For crypto: amount_usd / current_price = size in BTC/ETH
        # For forex: amount_usd directly (notional)
        try:
            market_data = await connector.fetch(symbol.split('-')[0], data_type='price')
            current_price = float(market_data.get('data', {}).get('price', 0))
        except Exception as e:
            print(f"[OrderService] Warning: Could not fetch price for {symbol}: {e}")
            current_price = 0
        
        if current_price == 0:
            raise ValueError(f"Cannot fetch current price for {symbol}")
        
        # Size calculation
        if exchange == 'hyperliquid':
            # Crypto: size = USD / price
            size = amount_usd / current_price
        else:
            # Ostium RWA: notional in USD
            size = amount_usd
        
        # 5. Submit to exchange
        try:
            exchange_response = await connector.place_order(
                user_address=user_address,
                symbol=symbol,
                side=side,
                order_type=order_type,
                size=size,
                price=price,
                stop_price=stop_price
            )
        except NotImplementedError as e:
            # Handle Ostium not implemented gracefully
            raise ValueError(f"Order placement not supported on {exchange}: {str(e)}")
        
        # 6. Store in database
        order_id = str(uuid.uuid4())
        async with AsyncSessionLocal() as session:
            order = Order(
                id=order_id,
                user_address=user_address,
                exchange=exchange,
                symbol=symbol,
                side=side,
                order_type=order_type,
                price=price,
                stop_price=stop_price,
                size=size,
                notional_usd=amount_usd,
                leverage=leverage,
                status=exchange_response.get('status', 'pending'),
                exchange_order_id=exchange_response.get('exchange_order_id'),
                created_at=datetime.utcnow()
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
        
        return {
            "order_id": order_id,
            "exchange": exchange,
            "symbol": symbol,
            "status": order.status,
            "exchange_order_id": order.exchange_order_id,
            "message": f"Order placed on {exchange}"
        }
    
    def _detect_exchange(self, symbol: str) -> str:
        """Auto-detect exchange from symbol"""
        # Crypto symbols → Hyperliquid
        crypto_symbols = ['BTC', 'ETH', 'SOL', 'LINK', 'AVAX', 'MATIC', 'ARB', 'DOGE', 'ATOM']
        
        # Check if symbol starts with crypto ticker
        for coin in crypto_symbols:
            if symbol.startswith(coin):
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
                    Order.user_address == user_address
                )
            )
            order = result.scalar_one_or_none()
            
            if not order:
                raise ValueError(f"Order {order_id} not found")
            
            if order.status != 'pending':
                raise ValueError(f"Cannot cancel order with status {order.status}")
            
            # Get connector
            connector = connector_registry.get_connector(order.exchange)
            
            # Cancel on exchange
            try:
                await connector.cancel_order(user_address, order.exchange_order_id)
            except NotImplementedError:
                raise ValueError(f"Order cancellation not supported on {order.exchange}")
            
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
        """Get user's order history"""
        
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select
            
            if status:
                query = select(Order).where(
                    Order.user_address == user_address,
                    Order.status == status
                ).order_by(Order.created_at.desc())
            else:
                query = select(Order).where(
                    Order.user_address == user_address
                ).order_by(Order.created_at.desc())
            
            result = await session.execute(query)
            orders = result.scalars().all()
            
            return [
                {
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
                    "created_at": order.created_at.isoformat() if order.created_at else None,
                    "filled_at": order.filled_at.isoformat() if order.filled_at else None
                }
                for order in orders
            ]
    
    async def get_user_positions(
        self, 
        user_address: str
    ) -> Dict[str, Any]:
        """Get user's active positions across all exchanges with account summary"""
        
        all_positions = []
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
            except NotImplementedError:
                pass
            except Exception as e:
                print(f"[OrderService] Error fetching Ostium positions: {e}")
        
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
