from __future__ import annotations

import os
from typing import Any, Dict, Optional

from ..Orchestrator.execution_adapter import ExecutionAdapter


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "on", "yes"}:
            return True
        if normalized in {"0", "false", "off", "no"}:
            return False
        return default
    return bool(value)


async def place_order(
    symbol: str,
    side: str,
    amount_usd: float,
    tool_states: Optional[Dict[str, Any]] = None,
    leverage: int = 1,
    order_type: str = "market",
    price: Optional[float] = None,
    stop_price: Optional[float] = None,
    tp: Optional[float] = None,
    sl: Optional[float] = None,
    gp: Optional[float] = None,
    gl: Optional[float] = None,
    user_address: Optional[str] = None,
    exchange: Optional[str] = None,
    reduce_only: bool = False,
    post_only: bool = False,
    time_in_force: str = "GTC",
    trigger_condition: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Place a trade order (open a position).

    If 'execution' is enabled and 'policy_mode' is 'auto_exec', the order is executed immediately.
    Otherwise, a proposal is returned for human approval (HITL flow).

    Args:
        symbol: The trading pair symbol (e.g. BTC-USD).
        side: "buy"/"long" or "sell"/"short".
        amount_usd: Position size in USD.
        tool_states: Runtime configuration states (injected by orchestrator).
        leverage: Leverage multiplier (default 1).
        order_type: "market", "limit", "stop_market", or "stop_limit".
        price: Limit price (required for limit orders).
        stop_price: Trigger price (required for stop orders).
        tp: Take profit price.
        sl: Stop loss price.
        gp: Validation level (Green Point) - triggers AI validation decision when hit.
        gl: Invalidation level (Red Line) - triggers AI invalidation decision when hit.
        user_address: The user's wallet address (required for execution).
        exchange: Target exchange (default: simulation).
    """
    tool_states = tool_states or {}

    # Normalize inputs
    symbol = str(symbol).strip().upper()
    raw_side = str(side).strip().lower()
    if raw_side in {"buy", "long"}:
        side = "buy"
    elif raw_side in {"sell", "short"}:
        side = "sell"
    else:
        return {"error": "Invalid side. Use buy/sell or long/short."}

    # Resolve configuration
    policy_mode = str(tool_states.get("policy_mode", "advice_only")).lower()
    execution_enabled = _parse_bool(tool_states.get("execution"), default=False)
    can_auto_execute = policy_mode == "auto_exec" and execution_enabled

    # Hard gate: if execution tools are disabled, block order placement entirely.
    # Frontend uses the "Auto Execution" toggle to control this.
    if not execution_enabled:
        return {
            "error": "Execution disabled. Enable Auto Execution to allow placing orders."
        }

    # Resolve user address: prefer explicit arg, then tool_states
    resolved_address = user_address or tool_states.get("user_address")

    # Resolve exchange: Check FORCE_EXECUTION_MODE environment variable first
    force_mode = os.getenv("FORCE_EXECUTION_MODE", "auto").lower().strip()
    if force_mode == "simulation":
        resolved_exchange = "simulation"
    elif force_mode == "onchain":
        resolved_exchange = "onchain"
    else:
        # Auto mode: use explicit arg or tool_states default
        resolved_exchange = exchange or tool_states.get(
            "execution_exchange", "simulation"
        )

    # 1. Validate constraints
    max_notional = float(tool_states.get("max_notional_usd", 5000) or 5000)
    max_leverage = int(tool_states.get("max_leverage", 50) or 50)

    if amount_usd > max_notional:
        return {"error": f"Blocked by max_notional_usd ({max_notional})."}
    if leverage > max_leverage:
        return {"error": f"Blocked by max_leverage ({max_leverage}x)."}

    if not resolved_address:
        # Without user address, we can't execute OR propose effectively linked to a user?
        # Acutally, for proposal, maybe we don't strictly need it if the frontend fills it in?
        # But backend logic usually requires it.
        return {"error": "Missing user_address. Ensure wallet is connected."}

    # 2. Construct Order Arguments
    order_args = {
        "user_address": resolved_address,
        "symbol": symbol,
        "side": side,
        "amount_usd": float(amount_usd),
        "leverage": int(leverage),
        "order_type": order_type,
        "exchange": resolved_exchange,
        "reduce_only": bool(reduce_only),
        "post_only": bool(post_only),
        "time_in_force": str(time_in_force or "GTC"),
        "trigger_condition": trigger_condition,
    }
    if price is not None:
        order_args["price"] = float(price)
    if stop_price is not None:
        order_args["stop_price"] = float(stop_price)
    if tp is not None:
        order_args["tp"] = float(tp)
    if sl is not None:
        order_args["sl"] = float(sl)
    if gp is not None:
        order_args["gp"] = float(gp)
    if gl is not None:
        order_args["gl"] = float(gl)

    # 3. Decide: Execute or Propose?
    if can_auto_execute:
        # EXECUTE
        result = await ExecutionAdapter.place_order(**order_args)
        # If result has error key, tool result will capture it.
        return result
    else:
        # PROPOSE (HITL)
        # We return a specially formatted dict that the ToolResult wrapper will likely pass through.
        # However, ToolResult expects 'data' to contain this.
        # The tool function returns the 'data' part of ToolResult.
        return {
            "status": "proposal",
            "order": order_args,
            "reason": "Human approval required (HITL).",
            # We return 'ok': True implicitly by returning a dict without 'error' key (unless we want to fail).
            # But here we want the tool call to be considered Successful, just creating a proposal.
        }
