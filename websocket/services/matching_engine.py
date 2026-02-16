
import asyncio
import logging
from typing import List, Dict, Optional
import uuid
from datetime import datetime
from sqlalchemy import select, and_, or_

# Local Imports
from database.connection import AsyncSessionLocal
from database.models import Order, Position, PositionRiskConfig
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
                Order.status.in_(['OPEN', 'open', 'PENDING', 'pending']),
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

            risk_map = {}
            try:
                uaddrs = list({p.user_address for p in positions if p and p.user_address})
                if uaddrs:
                    cfg_stmt = select(PositionRiskConfig).where(PositionRiskConfig.user_address.in_(uaddrs))
                    cfg_res = await session.execute(cfg_stmt)
                    cfg_rows = cfg_res.scalars().all()
                    risk_map = {(c.user_address, c.symbol, c.exchange): c for c in cfg_rows}
            except Exception:
                risk_map = {}
            
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
                    cfg = risk_map.get((pos.user_address, pos.symbol, pos.exchange))
                    size_pct = 1.0
                    close_price = price

                    if cfg and getattr(cfg, "tpsl_size_tokens", None) and getattr(pos, "size", 0) and pos.size > 0:
                        try:
                            size_pct = min(1.0, float(cfg.tpsl_size_tokens) / float(pos.size))
                        except Exception:
                            size_pct = 1.0

                    if cfg and action == "TP" and getattr(cfg, "tp_limit_price", None):
                        try:
                            lp = float(cfg.tp_limit_price)
                            if lp > 0:
                                close_price = lp
                        except Exception:
                            pass

                    if cfg and action == "SL" and getattr(cfg, "sl_limit_price", None):
                        try:
                            lp = float(cfg.sl_limit_price)
                            if lp > 0:
                                close_price = lp
                        except Exception:
                            pass

                    # include pos.id to clear triggered leg and avoid re-trigger loops
                    tpsl_triggers.append((pos.id, pos.user_address, pos.symbol, close_price, size_pct, action))

        # EXECUTE OUTSIDE SESSION
        for m in matches:
            oid, uaddr, sym, side, size, lev, price = m
            await self._execute_fill(oid, uaddr, sym, side, size, lev, price)
            
        for t in tpsl_triggers:
            pos_id, uaddr, sym, close_price, size_pct, action = t
            await trade_action_service.close_position(uaddr, sym, close_price=close_price, size_pct=size_pct)

            # Clear the triggered leg to prevent repeated closes when price stays beyond threshold.
            try:
                async with AsyncSessionLocal() as session:
                    stmt = select(Position).where(Position.id == pos_id)
                    res = await session.execute(stmt)
                    p = res.scalar_one_or_none()
                    if p and p.status == "OPEN":
                        if action == "TP":
                            p.tp = None
                        elif action == "SL":
                            p.sl = None
                        await session.commit()
            except Exception:
                pass

    def _check_condition(self, order, current_price):
        # LIMIT
        if order.order_type == 'limit':
            # Fill at current price (<= limit for buy, >= limit for sell) for realistic simulation.
            if order.side == 'buy' and current_price <= order.price:
                return True, current_price
            if order.side == 'sell' and current_price >= order.price:
                return True, current_price
        
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
        def _to_number(text: str) -> Optional[float]:
            import re
            cleaned = re.sub(r"[^0-9.\\-]", "", text)
            try:
                val = float(cleaned)
            except Exception:
                return None
            if not (val > 0):
                return None
            return val

        def _resolve_trigger(raw: Optional[str], mode: str, side: str, entry: float) -> Optional[float]:
            if raw is None:
                return None
            s = str(raw).strip().upper()
            if not s:
                return None
            n = _to_number(s)
            if n is None:
                return None

            if s.endswith("%"):
                if not (entry > 0):
                    return None
                ratio = n / 100.0
                if mode == "TP":
                    return entry * (1 + ratio) if side == "long" else entry * (1 - ratio)
                return entry * (1 - ratio) if side == "long" else entry * (1 + ratio)

            if s.endswith("USD") or s.endswith("$"):
                if not (entry > 0):
                    return None
                # Interpret as absolute price delta from entry (frontend uses same convention).
                if mode == "TP":
                    return entry + n if side == "long" else entry - n
                return entry - n if side == "long" else entry + n

            return n

        try:
            side = "long" if str(pos.side or "").lower() in ("long", "buy") else "short"
            entry = float(getattr(pos, "entry_price", 0) or 0)
            tp = _resolve_trigger(pos.tp, "TP", side, entry) if pos.tp else None
            sl = _resolve_trigger(pos.sl, "SL", side, entry) if pos.sl else None
            if side == "long":
                if tp and current_price >= tp:
                    return "TP"
                if sl and current_price <= sl:
                    return "SL"
            else:
                if tp and current_price <= tp:
                    return "TP"
                if sl and current_price >= sl:
                    return "SL"
        except Exception:
            pass
        return None

    async def _execute_fill(self, order_id, user, symbol, side, size, leverage, price):
        logger.info(f"Filling Order {order_id} {side} {symbol} @ {price}")
        norm_side = 'long' if side.lower() in ['buy', 'long'] else 'short'
        margin = (size * price) / leverage
        
        await ledger_service.process_trade_open(
             user, symbol, norm_side, size, price, leverage, margin, order_id
        )

        # Mark the pending order as filled so UI/queries stop treating it as cancellable/open.
        try:
            async with AsyncSessionLocal() as session:
                stmt = select(Order).where(
                    Order.id == order_id,
                    Order.user_address == str(user).lower(),
                )
                res = await session.execute(stmt)
                o = res.scalar_one_or_none()
                if o:
                    now = datetime.utcnow()
                    o.status = "filled"
                    if hasattr(o, "filled_at"):
                        o.filled_at = now
                    if hasattr(o, "updated_at"):
                        o.updated_at = now
                    if hasattr(o, "filled_size"):
                        try:
                            o.filled_size = float(size) if size is not None else o.filled_size
                        except Exception:
                            pass
                    if hasattr(o, "avg_fill_price"):
                        try:
                            o.avg_fill_price = float(price) if price is not None else o.avg_fill_price
                        except Exception:
                            pass
                    if hasattr(o, "exchange_order_id") and not getattr(o, "exchange_order_id", None):
                        o.exchange_order_id = f"sim_{str(order_id)[:8]}"
                    await session.commit()
        except Exception as e:
            logger.error(f"Failed to update filled order status for {order_id}: {e}")

simulation_matching_engine = SimulationMatchingEngine()
