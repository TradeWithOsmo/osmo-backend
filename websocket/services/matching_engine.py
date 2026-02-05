
import asyncio
import logging
from typing import List, Dict, Optional
import uuid
from datetime import datetime
from sqlalchemy import select, and_, or_

# Local Imports
from database.connection import AsyncSessionLocal
from database.models import Order, Position
from services.ledger_service import ledger_service
from services.trade_action_service import trade_action_service
from connectors.init_connectors import connector_registry

logger = logging.getLogger(__name__)

class SimulationMatchingEngine:
    """
    Backend Matching Engine for Simulation Mode.
    Matches Pending Orders (Limit, Stop) against Live Oracle Prices.
    Triggers TP/SL and Stop Orders.
    """
    
    def __init__(self):
        self.is_running = False
        self._price_cache = {} # Symbol -> Price
        
    async def start(self):
        if self.is_running: return
        self.is_running = True
        logger.info("Simulation Matching Engine Started")
        
        while self.is_running:
            try:
                await self.process_matching_cycle()
                await asyncio.sleep(1) # Match every 1 second
            except Exception as e:
                logger.error(f"Error in matching matching cycle: {e}")
                await asyncio.sleep(5)
                
    async def stop(self):
        self.is_running = False

    async def _fetch_prices(self, symbols: List[str]):
        """Update price cache for needed symbols"""
        unique_symbols = list(set(symbols))
        for symbol in unique_symbols:
            try:
                base = symbol.split('-')[0]
                # Priority: Hyperliquid -> Ostium
                conn = connector_registry.get_connector('hyperliquid')
                if not conn: conn = connector_registry.get_connector('ostium')
                
                if conn:
                    data = await conn.fetch(base, data_type='price')
                    price = float(data.get('data', {}).get('price', 0))
                    if price > 0:
                        self._price_cache[symbol] = price
            except Exception as e:
                logger.warn(f"Failed to fetch price for {symbol}: {e}")

    async def process_matching_cycle(self):
        """Main Loop: Check Open Orders and Positions against Prices"""
        async with AsyncSessionLocal() as session:
            # 1. Get Open PENDING Orders (Limit, Stop) for Simulation
            # status='OPEN' means Pending in our logic for Limit/Stop
            stmt = select(Order).where(
                Order.exchange == 'simulation',
                Order.status.in_(['OPEN', 'pending']), 
                Order.filled_size == 0 # Fully unfilled
            )
            result = await session.execute(stmt)
            pending_orders = result.scalars().all()
            
            # 2. Get Open Positions with TP/SL
            stmt_pos = select(Position).where(
                Position.status == 'OPEN',
                or_(Position.tp.isnot(None), Position.sl.isnot(None))
            )
            res_pos = await session.execute(stmt_pos)
            positions = res_pos.scalars().all()
            
            # 3. Fetch Prices
            symbols_needed = [o.symbol for o in pending_orders] + [p.symbol for p in positions]
            if not symbols_needed: return
            
            await self._fetch_prices(symbols_needed)
            
            # 4. Match Orders
            # Collect matches first to avoid long-running session usage
            matches = []
            for order in pending_orders:
                price = self._price_cache.get(order.symbol)
                if not price: continue
                
                # Check logic
                triggered, fill_price = self._check_condition(order, price)
                if triggered:
                    matches.append((order.id, order.user_address, order.symbol, order.side, order.size, order.leverage, fill_price))
            
            # 5. Match TP/SL
            tpsl_triggers = []
            for pos in positions:
                price = self._price_cache.get(pos.symbol)
                if not price: continue
                
                action = self._check_tpsl_condition(pos, price)
                if action:
                    tpsl_triggers.append((pos.user_address, pos.symbol))

        # EXECUTE OUTSIDE SESSION
        for m in matches:
            oid, uaddr, sym, side, size, lev, price = m
            await self._execute_fill(oid, uaddr, sym, side, size, lev, price)
            
        for t in tpsl_triggers:
            uaddr, sym = t
            await trade_action_service.close_position(uaddr, sym, 1.0)

    def _check_condition(self, order, current_price):
        # LIMIT
        if order.order_type == 'limit':
            if order.side == 'buy' and current_price <= order.price: return True, order.price
            if order.side == 'sell' and current_price >= order.price: return True, order.price
        
        # STOP
        elif 'stop' in order.order_type:
             cond = order.trigger_condition
             trig = order.trigger_price
             # Ensure trigger_price is set, if not default to price?
             if trig is None: trig = order.price 

             if (cond == 'ABOVE' and current_price >= trig) or \
                (cond == 'BELOW' and current_price <= trig):
                 # Triggered
                 if order.order_type == 'stop_market': return True, current_price
                 # Stop Limit not fully implemented in V1 this way, handling simple fills
        return False, 0

    def _check_tpsl_condition(self, pos, current_price):
        try:
            tp = float(pos.tp) if pos.tp else None
            sl = float(pos.sl) if pos.sl else None
            is_long = pos.side.lower() == 'long'
            if is_long:
                if tp and current_price >= tp: return 'TP'
                if sl and current_price <= sl: return 'SL'
            else:
                if tp and current_price <= tp: return 'TP'
                if sl and current_price >= sl: return 'SL'
        except: pass
        return None

    async def _execute_fill(self, order_id, user, symbol, side, size, leverage, price):
        logger.info(f"Filling Order {order_id} {side} {symbol} @ {price}")
        norm_side = 'long' if side.lower() in ['buy', 'long'] else 'short'
        margin = (size * price) / leverage
        
        await ledger_service.process_trade_open(
             user, symbol, norm_side, size, price, leverage, margin, order_id
        )

simulation_matching_engine = SimulationMatchingEngine()
