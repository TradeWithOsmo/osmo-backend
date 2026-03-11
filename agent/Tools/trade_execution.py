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


def _normalize_order_type(value: Any) -> str:
    raw = str(value or "").strip().lower().replace(" ", "_")
    aliases = {
        "mkt": "market",
        "market_order": "market",
        "limit_order": "limit",
        "stop": "stop_market",
        "stoploss": "stop_market",
        "stop_loss": "stop_market",
        "stoplimit": "stop_limit",
    }
    normalized = aliases.get(raw, raw)
    if normalized not in {"market", "limit", "stop_market", "stop_limit"}:
        return "market"
    return normalized


def _resolve_amount_usd(
    amount_usd: Optional[float],
    size_pct: Optional[float],
    tool_states: Dict[str, Any],
) -> tuple:
    """
    Resolve the final amount_usd to use for the order.

    Priority:
      1. If size_pct is provided (e.g. 0.25, 0.5, 0.75, 1.0), compute from
         free_collateral_usd injected in tool_states.
      2. Otherwise fall back to the explicit amount_usd argument.

    Returns (resolved_amount_usd, error_message_or_None).
    """
    if size_pct is not None:
        try:
            pct = float(size_pct)
        except (TypeError, ValueError):
            return 0.0, "size_pct must be a number between 0 and 1 (e.g. 0.25 for 25%)."

        if pct <= 0 or pct > 1:
            return 0.0, f"size_pct must be between 0 (exclusive) and 1 (inclusive). Got {pct}."

        # Use free_collateral_usd injected by agent router at runtime.
        # Falls back to trading_balance_usd which is also set there.
        free_collateral = (
            tool_states.get("free_collateral_usd")
            or tool_states.get("trading_balance_usd")
            or 0
        )
        try:
            free_collateral = float(free_collateral)
        except (TypeError, ValueError):
            free_collateral = 0.0

        if free_collateral <= 0:
            return 0.0, (
                "Cannot resolve size_pct: free_collateral_usd is 0 or not available. "
                "Please pass an explicit amount_usd instead."
            )

        computed = round(free_collateral * pct, 2)
        if computed < 10:
            return 0.0, (
                f"Computed order size ${computed:.2f} ({int(pct*100)}% of ${free_collateral:.2f} "
                f"free collateral) is below the minimum $10."
            )
        return computed, None

    # No size_pct — use explicit amount_usd
    if amount_usd is None:
        return 0.0, "Provide either amount_usd (USD value) or size_pct (e.g. 0.25 for 25% of balance)."
    try:
        val = float(amount_usd)
    except (TypeError, ValueError):
        return 0.0, "amount_usd must be a number."
    if val <= 0:
        return 0.0, "amount_usd must be greater than 0."
    return val, None


async def place_order(
    symbol: str,
    side: str,
    amount_usd: Optional[float] = None,
    size_pct: Optional[float] = None,
    tool_states: Optional[Dict[str, Any]] = None,
    leverage: int = 1,
    order_type: str = "market",
    price: Optional[float] = None,
    stop_price: Optional[float] = None,
    tp: Optional[float] = None,
    sl: Optional[float] = None,
    gp: Optional[float] = None,
    gl: Optional[float] = None,
    validation: Optional[float] = None,
    invalidation: Optional[float] = None,
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
        amount_usd: Exact position size in USD. Use this OR size_pct.
        size_pct: Fraction of user's free balance (0.25=25%, 0.5=50%, 0.75=75%, 1.0=100%).
                  PREFERRED over amount_usd — system auto-fetches balance and computes USD.
                  Always prefer size_pct unless the user explicitly specifies a dollar amount.
        tool_states: Runtime configuration states (injected by orchestrator).
        leverage: Leverage multiplier (default 1).
        order_type: "market", "limit", "stop_market", or "stop_limit".
        price: Limit price (required for limit orders).
        stop_price: Trigger price (required for stop orders).
        tp: Take profit price.
        sl: Stop loss price.
        gp: Validation level (Green Point).
        gl: Invalidation level (Red Line).
        validation: Alias for gp.
        invalidation: Alias for gl.
        user_address: The user's wallet address (injected from runtime).
        exchange: Target exchange (simulation/onchain).
    """
    tool_states = tool_states or {}

    # Support both gp/gl and validation/invalidation naming.
    if gp is None and validation is not None:
        gp = validation
    if gl is None and invalidation is not None:
        gl = invalidation

    # Normalize inputs
    symbol = str(symbol).strip().upper()
    raw_side = str(side).strip().lower()
    if raw_side in {"buy", "long"}:
        side = "buy"
    elif raw_side in {"sell", "short"}:
        side = "sell"
    else:
        return {"error": "Invalid side. Use buy/sell or long/short."}

    # --- Resolve amount_usd from size_pct or explicit value ---
    resolved_amount, amt_error = _resolve_amount_usd(amount_usd, size_pct, tool_states)
    if amt_error:
        return {"error": amt_error}

    # Cache balance info for transparency in response
    free_collateral = float(
        tool_states.get("free_collateral_usd")
        or tool_states.get("trading_balance_usd")
        or 0
    )

    # Resolve configuration
    policy_mode = str(tool_states.get("policy_mode", "hitl")).lower()
    execution_enabled = _parse_bool(tool_states.get("execution"), default=True)
    can_auto_execute = policy_mode == "auto_exec" and execution_enabled

    requested_order_type = _normalize_order_type(order_type)
    prefer_market_orders = _parse_bool(
        tool_states.get("prefer_market_orders"), default=True
    )
    allow_non_market_orders = _parse_bool(
        tool_states.get("allow_non_market_orders"), default=False
    )
    normalized_order_type = requested_order_type
    if prefer_market_orders and not allow_non_market_orders:
        normalized_order_type = "market"
    if normalized_order_type == "market":
        # Prevent accidental pending orders when a stale limit/stop price is provided.
        price = None
        stop_price = None

    # Resolve user address: always prefer runtime-injected tool_states address.
    # If agent passes an explicit user_address arg, only use it if it looks like a real wallet
    # (starts with 0x and is at least 10 chars). This prevents hallucinated placeholders.
    explicit_addr = str(user_address or "").strip()
    is_real_wallet = explicit_addr.startswith("0x") and len(explicit_addr) >= 10
    resolved_address = (explicit_addr if is_real_wallet else None) or tool_states.get("user_address")

    # Resolve exchange: Check FORCE_EXECUTION_MODE environment variable first
    force_mode = os.getenv("FORCE_EXECUTION_MODE", "auto").lower().strip()
    if force_mode == "simulation":
        resolved_exchange = "simulation"
    elif force_mode == "onchain":
        resolved_exchange = "onchain"
    else:
        resolved_exchange = exchange or tool_states.get(
            "execution_exchange", "simulation"
        )

    # Validate constraints
    max_notional = float(tool_states.get("max_notional_usd", 5000) or 5000)
    max_leverage = int(tool_states.get("max_leverage", 50) or 50)

    if resolved_amount > max_notional:
        return {"error": f"Blocked by max_notional_usd ({max_notional})."}
    if leverage > max_leverage:
        return {"error": f"Blocked by max_leverage ({max_leverage}x)."}

    if not resolved_address:
        return {"error": "Missing user_address. Ensure wallet is connected."}

    # Construct Order Arguments
    order_args = {
        "user_address": resolved_address,
        "symbol": symbol,
        "side": side,
        "amount_usd": resolved_amount,
        "leverage": int(leverage),
        "order_type": normalized_order_type,
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

    # Decide: Execute or Propose?
    if can_auto_execute:
        result = await ExecutionAdapter.place_order(**order_args)
        # Attach balance context to result for transparency
        if isinstance(result, dict) and "error" not in result:
            if size_pct is not None:
                result["size_pct_used"] = size_pct
                result["free_collateral_usd"] = free_collateral
                result["amount_usd_resolved"] = resolved_amount
        return result
    else:
        # PROPOSE (HITL)
        proposal = {
            "status": "proposal",
            "order": order_args,
            "reason": "Human approval required (HITL).",
        }
        if size_pct is not None:
            proposal["size_pct_used"] = size_pct
            proposal["free_collateral_usd"] = free_collateral
        return proposal
