"""
AI Trigger Service

Handles triggering AI agent for follow-up decisions when GP/GL levels are triggered.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AITriggerService:
    """
    Service to trigger AI agent decisions for GP/GL follow-ups.
    """

    def __init__(self):
        self._runtime = None
        self._chat_service = None

    def set_runtime(self, runtime):
        """Set the AI runtime for generating decisions."""
        self._runtime = runtime

    def set_chat_service(self, chat_service):
        """Set the chat service for sending messages."""
        self._chat_service = chat_service

    async def trigger_gp_followup(
        self,
        user_address: str,
        symbol: str,
        side: str,
        trigger_price: float,
        gp_level: float,
        entry_price: float,
        tp: Optional[float] = None,
        sl: Optional[float] = None,
        session_id: Optional[str] = None,
        exchange: str = "simulation",
    ) -> Dict[str, Any]:
        """
        Trigger AI validation decision when GP (Green Point) is hit.
        
        GP hit means the trade thesis is being validated - AI should provide
        follow-up analysis on whether to:
        - Trail stop loss to breakeven
        - Take partial profits
        - Adjust targets
        - Hold with confidence
        """
        try:
            # Build AI prompt for validation decision
            prompt = self._build_validation_prompt(
                symbol=symbol,
                side=side,
                trigger_price=trigger_price,
                gp_level=gp_level,
                entry_price=entry_price,
                tp=tp,
                sl=sl,
            )

            # Trigger AI via chat service if available
            if self._chat_service:
                result = await self._chat_service.process_message(
                    user_address=user_address,
                    message=prompt,
                    session_id=session_id,
                    tool_states={
                        "write": False,
                        "execution": False,
                        "market_symbol": symbol,
                    },
                )
                return {
                    "status": "triggered",
                    "prompt": prompt,
                    "response": result,
                }

            # Fallback: return prompt for external handling
            logger.info(
                f"[AITrigger] GP validation triggered for {symbol} {side} - "
                f"price {trigger_price} hit GP {gp_level}"
            )

            return {
                "status": "prompt_ready",
                "prompt": prompt,
                "recommendation": self._get_default_validation_recommendation(
                    side=side,
                    trigger_price=trigger_price,
                    entry_price=entry_price,
                    tp=tp,
                    sl=sl,
                ),
            }

        except Exception as e:
            logger.error(f"[AITrigger] Error triggering GP followup: {e}")
            return {"status": "error", "error": str(e)}

    async def trigger_gl_followup(
        self,
        user_address: str,
        symbol: str,
        side: str,
        trigger_price: float,
        gl_level: float,
        entry_price: float,
        tp: Optional[float] = None,
        sl: Optional[float] = None,
        session_id: Optional[str] = None,
        exchange: str = "simulation",
    ) -> Dict[str, Any]:
        """
        Trigger AI invalidation decision when GL (Red Line) is hit.
        
        GL hit means the trade thesis has been invalidated - AI should provide
        follow-up analysis on whether to:
        - Exit position immediately
        - Wait for confirmation
        - Reverse position
        - Assess market conditions
        """
        try:
            # Build AI prompt for invalidation decision
            prompt = self._build_invalidation_prompt(
                symbol=symbol,
                side=side,
                trigger_price=trigger_price,
                gl_level=gl_level,
                entry_price=entry_price,
                tp=tp,
                sl=sl,
            )

            # Trigger AI via chat service if available
            if self._chat_service:
                result = await self._chat_service.process_message(
                    user_address=user_address,
                    message=prompt,
                    session_id=session_id,
                    tool_states={
                        "write": False,
                        "execution": True,  # Enable execution for potential exit
                        "market_symbol": symbol,
                    },
                )
                return {
                    "status": "triggered",
                    "prompt": prompt,
                    "response": result,
                }

            # Fallback: return prompt for external handling
            logger.info(
                f"[AITrigger] GL invalidation triggered for {symbol} {side} - "
                f"price {trigger_price} hit GL {gl_level}"
            )

            return {
                "status": "prompt_ready",
                "prompt": prompt,
                "recommendation": self._get_default_invalidation_recommendation(
                    side=side,
                    trigger_price=trigger_price,
                    entry_price=entry_price,
                    sl=sl,
                ),
            }

        except Exception as e:
            logger.error(f"[AITrigger] Error triggering GL followup: {e}")
            return {"status": "error", "error": str(e)}

    def _build_validation_prompt(
        self,
        symbol: str,
        side: str,
        trigger_price: float,
        gp_level: float,
        entry_price: float,
        tp: Optional[float],
        sl: Optional[float],
    ) -> str:
        """Build prompt for AI validation decision."""
        pnl_pct = ((trigger_price - entry_price) / entry_price * 100) if side == "long" else ((entry_price - trigger_price) / entry_price * 100)
        
        return f"""🎯 VALIDATION TRIGGER - {symbol} {side.upper()}

Your trade thesis is being VALIDATED! Price has hit the Green Point (GP) level.

**Position Details:**
- Symbol: {symbol}
- Side: {side}
- Entry Price: ${entry_price:.2f}
- Current Price: ${trigger_price:.2f}
- GP Level: ${gp_level:.2f}
- Unrealized P&L: {pnl_pct:.1f}%
- Take Profit: ${tp:.2f if tp else 'Not set'}
- Stop Loss: ${sl:.2f if sl else 'Not set'}

**What should you do?**
As the trading AI assistant, analyze the current market conditions and provide a recommendation for:
1. Should we trail the stop loss to protect profits?
2. Should we take partial profits now?
3. Are there any reasons to adjust the original targets?
4. Provide your confidence level and reasoning.

**Important:** This is a VALIDATION signal - the trade is working as expected. Focus on risk management and profit optimization."""

    def _build_invalidation_prompt(
        self,
        symbol: str,
        side: str,
        trigger_price: float,
        gl_level: float,
        entry_price: float,
        tp: Optional[float],
        sl: Optional[float],
    ) -> str:
        """Build prompt for AI invalidation decision."""
        pnl_pct = ((trigger_price - entry_price) / entry_price * 100) if side == "long" else ((entry_price - trigger_price) / entry_price * 100)
        
        return f"""🚨 INVALIDATION TRIGGER - {symbol} {side.upper()}

Your trade thesis has been INVALIDATED! Price has hit the Red Line (GL) level.

**Position Details:**
- Symbol: {symbol}
- Side: {side}
- Entry Price: ${entry_price:.2f}
- Current Price: ${trigger_price:.2f}
- GL Level: ${gl_level:.2f}
- Unrealized P&L: {pnl_pct:.1f}%
- Stop Loss: ${sl:.2f if sl else 'Not set'}

**What should you do?**
As the trading AI assistant, analyze the current market conditions and provide an IMMEDIATE recommendation:
1. Should we exit the position NOW?
2. Is there a potential reversal opportunity?
3. What market conditions caused this invalidation?
4. Provide your action plan with urgency level.

**Important:** This is an INVALIDATION signal - the original thesis is no longer valid. Prioritize capital preservation and quick decision-making."""

    def _get_default_validation_recommendation(
        self,
        side: str,
        trigger_price: float,
        entry_price: float,
        tp: Optional[float],
        sl: Optional[float],
    ) -> Dict[str, Any]:
        """Get default recommendation for validation trigger (when AI is unavailable)."""
        pnl_pct = ((trigger_price - entry_price) / entry_price * 100) if side == "long" else ((entry_price - trigger_price) / entry_price * 100)
        
        recommendation = {
            "action": "trail_stop",
            "confidence": "medium",
            "reasoning": f"Trade is up {pnl_pct:.1f}% - consider trailing stop to breakeven or better",
        }
        
        # If profit is significant, suggest partial profit taking
        if pnl_pct > 5:
            recommendation["action"] = "partial_profit"
            recommendation["partial_pct"] = 0.5
            recommendation["reasoning"] = f"Trade is up {pnl_pct:.1f}% - consider taking 50% partial profits and trail stop"
        
        return recommendation

    def _get_default_invalidation_recommendation(
        self,
        side: str,
        trigger_price: float,
        entry_price: float,
        sl: Optional[float],
    ) -> Dict[str, Any]:
        """Get default recommendation for invalidation trigger (when AI is unavailable)."""
        pnl_pct = ((trigger_price - entry_price) / entry_price * 100) if side == "long" else ((entry_price - trigger_price) / entry_price * 100)
        
        return {
            "action": "exit",
            "confidence": "high",
            "urgency": "immediate",
            "reasoning": f"Trade thesis invalidated. Current loss: {abs(pnl_pct):.1f}%. Exit recommended to preserve capital.",
        }

    async def create_ai_trigger_callback(self) -> callable:
        """Create a callback function for price monitor service."""
        async def callback(context: Dict[str, Any]) -> Dict[str, Any]:
            trigger_type = context.get("trigger_type")
            
            if trigger_type == "validation":
                return await self.trigger_gp_followup(
                    user_address=context.get("user_address"),
                    symbol=context.get("symbol"),
                    side=context.get("side"),
                    trigger_price=context.get("current_price"),
                    gp_level=context.get("trigger_level"),
                    entry_price=context.get("entry_price"),
                    tp=context.get("tp"),
                    sl=context.get("sl"),
                    session_id=context.get("session_id"),
                    exchange=context.get("exchange"),
                )
            elif trigger_type == "invalidation":
                return await self.trigger_gl_followup(
                    user_address=context.get("user_address"),
                    symbol=context.get("symbol"),
                    side=context.get("side"),
                    trigger_price=context.get("current_price"),
                    gl_level=context.get("trigger_level"),
                    entry_price=context.get("entry_price"),
                    tp=context.get("tp"),
                    sl=context.get("sl"),
                    session_id=context.get("session_id"),
                    exchange=context.get("exchange"),
                )
            
            return {"status": "unknown_trigger_type"}

        return callback


# Global instance
ai_trigger_service = AITriggerService()
