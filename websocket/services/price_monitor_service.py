"""
Price Monitor Service

Monitors live prices and triggers AI follow-up decisions when:
- Price crosses GP (validation) level -> trigger validation decision
- Price crosses GL (invalidation) level -> trigger invalidation decision

The service integrates with:
- latest_prices from main.py (live price feed)
- TradeSetup model (validation/invalidation levels)
- AI Agent runtime for generating follow-up decisions
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable

from database.connection import AsyncSessionLocal
from database.models import Position, TradeSetup
from sqlalchemy import select, and_
from storage.redis_manager import redis_manager

logger = logging.getLogger(__name__)


class PriceMonitorService:
    """
    Monitors prices and triggers AI decisions when GP/GL levels are crossed.
    """

    def __init__(self):
        self.running = False
        self.check_interval = 2.0  # Check every 2 seconds
        self.latest_prices: Dict[str, dict] = {}
        self._ai_trigger_callback: Optional[Callable] = None
        self._triggered_setups: Dict[str, set] = {}  # user_address -> set of triggered setup ids

    def set_ai_trigger_callback(self, callback: Callable):
        """Set callback function to trigger AI agent decisions."""
        self._ai_trigger_callback = callback

    def update_prices(self, prices: Dict[str, dict]):
        """Update latest prices from external price feed."""
        self.latest_prices = prices

    async def start(self, latest_prices: Dict[str, dict] = None):
        """Start the price monitor service."""
        if self.running:
            return

        if latest_prices:
            self.latest_prices = latest_prices

        self.running = True
        asyncio.create_task(self._monitor_loop())
        logger.info("[PriceMonitor] Started monitoring GP/GL levels")

    async def stop(self):
        """Stop the price monitor service."""
        self.running = False
        logger.info("[PriceMonitor] Stopped")

    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self.running:
            try:
                await self._check_all_setups()
            except Exception as e:
                logger.error(f"[PriceMonitor] Error in monitor loop: {e}")

            await asyncio.sleep(self.check_interval)

    async def _check_all_setups(self):
        """Check all active trade setups against current prices."""
        try:
            async with AsyncSessionLocal() as session:
                # Get all active trade setups with GP/GL defined
                result = await session.execute(
                    select(TradeSetup).where(
                        and_(
                            TradeSetup.status == "active",
                            TradeSetup.gp_triggered == False,
                            TradeSetup.gl_triggered == False,
                        )
                    )
                )
                setups = result.scalars().all()

                for setup in setups:
                    await self._check_setup(setup, session)

                await session.commit()

        except Exception as e:
            logger.error(f"[PriceMonitor] Error checking setups: {e}")

    async def _check_setup(self, setup: TradeSetup, session):
        """Check a single trade setup against current price."""
        symbol = setup.symbol
        if symbol not in self.latest_prices:
            return

        price_data = self.latest_prices.get(symbol, {})
        current_price = float(price_data.get("price", 0))

        if current_price <= 0:
            return

        side = str(setup.side or "").strip().lower()
        gp = setup.gp
        gl = setup.gl

        # Determine trigger conditions based on side
        # Long: GP above entry (validation), GL below entry (invalidation)
        # Short: GP below entry (validation), GL above entry (invalidation)

        gp_triggered = False
        gl_triggered = False

        if side == "long":
            # Long position:
            # GP triggered when price >= GP (validation - trade thesis confirmed)
            # GL triggered when price <= GL (invalidation - stop hit)
            if gp is not None and current_price >= gp and not setup.gp_triggered:
                gp_triggered = True
            if gl is not None and current_price <= gl and not setup.gl_triggered:
                gl_triggered = True
        elif side == "short":
            # Short position:
            # GP triggered when price <= GP (validation - trade thesis confirmed)
            # GL triggered when price >= GL (invalidation - stop hit)
            if gp is not None and current_price <= gp and not setup.gp_triggered:
                gp_triggered = True
            if gl is not None and current_price >= gl and not setup.gl_triggered:
                gl_triggered = True

        # Handle GP trigger
        if gp_triggered:
            await self._handle_gp_trigger(setup, current_price, session)

        # Handle GL trigger
        if gl_triggered:
            await self._handle_gl_trigger(setup, current_price, session)

    async def _handle_gp_trigger(self, setup: TradeSetup, trigger_price: float, session):
        """Handle GP (validation) level trigger."""
        logger.info(
            f"[PriceMonitor] GP TRIGGERED for {setup.symbol} {setup.side} "
            f"at price {trigger_price} (GP: {setup.gp}) - user: {setup.user_address}"
        )

        setup.gp_triggered = True
        setup.gp_triggered_at = datetime.utcnow()
        setup.gp_trigger_price = trigger_price

        # Notify user via WebSocket
        await self._notify_user(
            user_address=setup.user_address,
            event_type="gp_triggered",
            data={
                "setup_id": setup.id,
                "symbol": setup.symbol,
                "side": setup.side,
                "trigger_type": "validation",
                "trigger_price": trigger_price,
                "gp_level": setup.gp,
                "message": f"Validation level (GP) reached for {setup.symbol} {setup.side} position",
                "ai_note": setup.gp_note,
            },
        )

        # Trigger AI follow-up decision
        if self._ai_trigger_callback and not setup.gp_decision_triggered:
            await self._trigger_ai_decision(
                setup=setup,
                trigger_type="validation",
                trigger_price=trigger_price,
                session=session,
            )

    async def _handle_gl_trigger(self, setup: TradeSetup, trigger_price: float, session):
        """Handle GL (invalidation) level trigger."""
        logger.info(
            f"[PriceMonitor] GL TRIGGERED for {setup.symbol} {setup.side} "
            f"at price {trigger_price} (GL: {setup.gl}) - user: {setup.user_address}"
        )

        setup.gl_triggered = True
        setup.gl_triggered_at = datetime.utcnow()
        setup.gl_trigger_price = trigger_price

        # Notify user via WebSocket
        await self._notify_user(
            user_address=setup.user_address,
            event_type="gl_triggered",
            data={
                "setup_id": setup.id,
                "symbol": setup.symbol,
                "side": setup.side,
                "trigger_type": "invalidation",
                "trigger_price": trigger_price,
                "gl_level": setup.gl,
                "message": f"Invalidation level (GL) reached for {setup.symbol} {setup.side} position",
                "ai_note": setup.gl_note,
            },
        )

        # Trigger AI follow-up decision
        if self._ai_trigger_callback and not setup.gl_decision_triggered:
            await self._trigger_ai_decision(
                setup=setup,
                trigger_type="invalidation",
                trigger_price=trigger_price,
                session=session,
            )

    async def _trigger_ai_decision(
        self,
        setup: TradeSetup,
        trigger_type: str,  # "validation" or "invalidation"
        trigger_price: float,
        session,
    ):
        """Trigger AI agent to generate follow-up decision."""
        try:
            if not self._ai_trigger_callback:
                return

            # Build context for AI decision
            context = {
                "user_address": setup.user_address,
                "session_id": setup.session_id,
                "symbol": setup.symbol,
                "side": setup.side,
                "exchange": setup.exchange,
                "entry_price": setup.entry_price,
                "current_price": trigger_price,
                "trigger_type": trigger_type,
                "trigger_level": setup.gp if trigger_type == "validation" else setup.gl,
                "tp": setup.tp,
                "sl": setup.sl,
                "setup_id": setup.id,
            }

            # Call AI trigger callback
            decision_result = await self._ai_trigger_callback(context)

            if decision_result:
                # Mark decision as triggered
                if trigger_type == "validation":
                    setup.gp_decision_triggered = True
                else:
                    setup.gl_decision_triggered = True

                logger.info(
                    f"[PriceMonitor] AI decision triggered for {trigger_type} "
                    f"on {setup.symbol} - result: {decision_result}"
                )

                # Notify user of AI decision
                await self._notify_user(
                    user_address=setup.user_address,
                    event_type="ai_decision_triggered",
                    data={
                        "setup_id": setup.id,
                        "symbol": setup.symbol,
                        "trigger_type": trigger_type,
                        "decision": decision_result,
                    },
                )

        except Exception as e:
            logger.error(f"[PriceMonitor] Error triggering AI decision: {e}")

    async def _notify_user(self, user_address: str, event_type: str, data: Dict[str, Any]):
        """Notify user via Redis WebSocket broadcast."""
        try:
            message = {
                "type": event_type,
                "address": user_address.lower(),
                "data": data,
                "timestamp": datetime.utcnow().isoformat(),
            }
            await redis_manager.publish(
                f"user_notifications:{user_address.lower()}", message
            )
        except Exception as e:
            logger.error(f"[PriceMonitor] Failed to notify user {user_address}: {e}")

    async def create_trade_setup(
        self,
        user_address: str,
        symbol: str,
        side: str,
        entry_price: float,
        exchange: str = "simulation",
        session_id: Optional[str] = None,
        position_id: Optional[int] = None,
        tp: Optional[float] = None,
        sl: Optional[float] = None,
        gp: Optional[float] = None,
        gl: Optional[float] = None,
        gp_note: Optional[str] = None,
        gl_note: Optional[str] = None,
    ) -> TradeSetup:
        """Create a new trade setup with GP/GL levels."""
        async with AsyncSessionLocal() as session:
            setup = TradeSetup(
                user_address=user_address.lower(),
                session_id=session_id,
                position_id=position_id,
                exchange=exchange,
                symbol=symbol,
                side=side.lower(),
                entry_price=entry_price,
                tp=tp,
                sl=sl,
                gp=gp,
                gl=gl,
                gp_note=gp_note,
                gl_note=gl_note,
                status="active",
            )
            session.add(setup)
            await session.commit()
            await session.refresh(setup)

            logger.info(
                f"[PriceMonitor] Created trade setup for {symbol} {side} "
                f"GP={gp} GL={gl} - user: {user_address}"
            )

            return setup

    async def update_position_gpgl(
        self,
        user_address: str,
        symbol: str,
        exchange: str = "simulation",
        gp: Optional[float] = None,
        gl: Optional[float] = None,
    ) -> bool:
        """Update GP/GL levels for an existing position."""
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Position).where(
                        and_(
                            Position.user_address == user_address.lower(),
                            Position.symbol == symbol,
                            Position.exchange == exchange,
                            Position.status == "OPEN",
                        )
                    )
                )
                positions = result.scalars().all()

                if not positions:
                    return False

                position = positions[0]

                if gp is not None:
                    position.gp = float(gp)
                    position.gp_triggered = False  # Reset trigger
                if gl is not None:
                    position.gl = float(gl)
                    position.gl_triggered = False  # Reset trigger

                await session.commit()

                logger.info(
                    f"[PriceMonitor] Updated position GP/GL for {symbol} "
                    f"GP={gp} GL={gl} - user: {user_address}"
                )

                return True

        except Exception as e:
            logger.error(f"[PriceMonitor] Error updating position GP/GL: {e}")
            return False

    async def get_active_setups(self, user_address: str) -> List[Dict[str, Any]]:
        """Get all active trade setups for a user."""
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(TradeSetup).where(
                        and_(
                            TradeSetup.user_address == user_address.lower(),
                            TradeSetup.status == "active",
                        )
                    )
                )
                setups = result.scalars().all()

                return [
                    {
                        "id": s.id,
                        "symbol": s.symbol,
                        "side": s.side,
                        "entry_price": s.entry_price,
                        "tp": s.tp,
                        "sl": s.sl,
                        "gp": s.gp,
                        "gl": s.gl,
                        "gp_triggered": s.gp_triggered,
                        "gl_triggered": s.gl_triggered,
                        "gp_triggered_at": s.gp_triggered_at.isoformat() if s.gp_triggered_at else None,
                        "gl_triggered_at": s.gl_triggered_at.isoformat() if s.gl_triggered_at else None,
                        "status": s.status,
                        "created_at": s.created_at.isoformat() if s.created_at else None,
                    }
                    for s in setups
                ]

        except Exception as e:
            logger.error(f"[PriceMonitor] Error getting active setups: {e}")
            return []

    async def cancel_setup(self, setup_id: int, user_address: str) -> bool:
        """Cancel a trade setup."""
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(TradeSetup).where(
                        and_(
                            TradeSetup.id == setup_id,
                            TradeSetup.user_address == user_address.lower(),
                        )
                    )
                )
                setups = result.scalars().all()

                if not setups:
                    return False

                setup = setups[0]
                setup.status = "cancelled"
                await session.commit()

                logger.info(
                    f"[PriceMonitor] Cancelled trade setup {setup_id} - user: {user_address}"
                )

                return True

        except Exception as e:
            logger.error(f"[PriceMonitor] Error cancelling setup: {e}")
            return False


# Global instance
price_monitor_service = PriceMonitorService()
