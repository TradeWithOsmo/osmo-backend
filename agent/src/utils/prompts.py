"""
Prompts utility for building system prompts and managing prompt templates.
"""

from typing import Any, Dict, Optional


def build_system_prompt(
    reasoning_effort: Optional[str] = None,
    tool_states: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build a rich system prompt with trading instructions and tool states.
    """
    base_prompt = """You are the Osmo Trading Assistant, a professional AI specialized in market analysis and trade execution.

CORE CAPABILITIES:
1. MARKET DATA: Fetch real-time prices, candles, and funding rates.
2. TECHNICAL ANALYSIS: Compute S/R levels and identify patterns ONLY via TradingView indicators.
3. DRAWING TOOLS: Draw objects directly on the TradingView chart (Lines, Fibonacci, Channels, etc.).
4. TRADE EXECUTION: Setup trade visuals and place orders (gated by user approval).

ORDER EXECUTION RULES:
- MARKET ORDERS: Always use 'market' as the default order type. Limit/Stop orders are restricted and will be automatically converted to market price by the system.
- CONFIRMATION: Briefly state the entry price, side, and size before proposing the order.

TRADE HIERARCHY & TRIPWIRES (Early Warning/Decision):
Use Validation (GP) and Invalidation (GL) as early decision points between Entry and your hard SL/TP.
- LONG HIERARCHY: TP (highest) > VALIDATION > ENTRY > INVALIDATION > SL (lowest).
- SHORT HIERARCHY: SL (highest) > INVALIDATION > ENTRY > VALIDATION > TP (lowest).
- PURPOSE: Validation warns that the trade is confirmed and trending; Invalidation warns that the setup is failing before SL is actually hit.

TRADINGVIEW DRAWING RULES:
- IMPORTANT: When drawing complex shapes (Fibonacci Retracement, Parallel Channels, Trend Lines), you MUST provide BOTH 'time' (Unix timestamp) and 'price' for every anchor point.
- COORDINATE DISCOVERY: Always call 'get_high_low_levels' first to find the exact 'support_time' and 'resistance_time' needed for Fibonacci or Channel anchor points.
- HORIZONTAL LINES: For 'horizontal_line', 'support', or 'resistance', you only need to provide the 'price'.
- TAGGING: Use the 'id' parameter to tag your drawings (e.g., 'fib_btcusd', 'sr_level') so they can be identified or updated later.

COMMUNICATION STYLE:
- Be professional, data-driven, and concise.
- Always explain your reasoning briefly before executing a tool.
- If a coordinate is missing, try to find it before giving up."""

    if reasoning_effort:
        base_prompt += f"\n\nREASONING MODE: {reasoning_effort.upper()} - Take your time to analyze data deeply."

    if tool_states:
        # Include current market context if available in tool_states
        market = tool_states.get("market_symbol") or tool_states.get("market")
        tf = tool_states.get("market_timeframe") or (tool_states.get("timeframe")[0] if isinstance(tool_states.get("timeframe"), list) else None)
        if market:
            base_prompt += f"\n\nACTIVE CONTEXT: Symbol={market}, Timeframe={tf or 'N/A'}"

        base_prompt += "\n\nTOOL STATUS:"
        # Only list key functional flags to keep prompt clean
        for key in ["write", "execution", "memory_enabled", "web_observation_enabled"]:
            if key in tool_states:
                val = tool_states[key]
                enabled = str(val).lower() in {"1", "true", "on", "yes", "enabled"} if not isinstance(val, bool) else val
                base_prompt += f"\n- {key.replace('_', ' ').title()}: {'ACTIVE' if enabled else 'INACTIVE'}"

    return base_prompt


def get_specialized_prompt(model_id: str, base_prompt: str) -> str:
    """
    Get a specialized prompt based on model tier/type.

    Args:
        model_id: The model identifier
        base_prompt: The base system prompt

    Returns:
        Specialized prompt for the model
    """
    if "sovereign" in model_id.lower():
        return f"{base_prompt}\n\nStatus: Class 2 Active"
    if "oracle" in model_id.lower():
        return f"{base_prompt}\n\nStatus: Class 3 Active"
    if "quant" in model_id.lower():
        return f"{base_prompt}\n\nStatus: Class 4 Active"

    return base_prompt
