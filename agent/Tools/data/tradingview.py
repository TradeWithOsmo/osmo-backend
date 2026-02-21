"""
TradingView Frontend Tool

Allows the agent to 'see' what indicators the user has on their chart.
"""

from typing import Dict, Any, List, Optional
try:
    from agent.Tools.http_client import get_http_client
except Exception:
    from backend.agent.Tools.http_client import get_http_client
try:
    from agent.Config.tools_config import DATA_SOURCES
except Exception:
    from backend.agent.Config.tools_config import DATA_SOURCES

CONNECTORS_API = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")


def _norm_symbol(raw: str) -> str:
    return str(raw or "").strip().upper().replace("/", "-").replace("_", "-")


def _symbol_candidates(raw: str) -> List[str]:
    base = _norm_symbol(raw)
    if not base:
        return []
    out: List[str] = [base]
    if "-" in base:
        out.append(base.replace("-", "/"))
    if "/" in base:
        out.append(base.replace("/", "-"))
    uniq: List[str] = []
    seen = set()
    for item in out:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq


def _norm_timeframe(raw: str) -> str:
    value = str(raw or "").strip().upper()
    if not value:
        return ""
    mapping = {
        "1": "1m",
        "3": "3m",
        "5": "5m",
        "15": "15m",
        "30": "30m",
        "45": "45m",
        "60": "1H",
        "120": "2H",
        "180": "3H",
        "240": "4H",
        "360": "6H",
        "480": "8H",
        "720": "12H",
        "D": "1D",
        "W": "1W",
    }
    return mapping.get(value, value)


def _timeframe_candidates(raw: str) -> List[str]:
    tf = _norm_timeframe(raw)
    if not tf:
        return []

    out: List[str] = [tf]
    aliases = {
        "1D": ["D"],
        "D": ["1D"],
        "1W": ["W"],
        "W": ["1W"],
        "1H": ["60"],
        "60": ["1H"],
        "4H": ["240"],
        "240": ["4H"],
    }
    out.extend(aliases.get(tf, []))

    uniq: List[str] = []
    seen = set()
    for item in out:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq


def _extract_timeframe_from_states(tool_states: Dict[str, Any]) -> str:
    market_tf = str(tool_states.get("market_timeframe") or "").strip()
    if market_tf:
        return market_tf

    raw_tf = tool_states.get("timeframe")
    if isinstance(raw_tf, str) and raw_tf.strip():
        return raw_tf.strip()
    if isinstance(raw_tf, list):
        for item in raw_tf:
            value = str(item or "").strip()
            if value:
                return value
    return ""


def _fallback_indicators_from_states(tool_states: Dict[str, Any]) -> List[str]:
    merged: List[str] = []
    for key in ("market_active_indicators", "preferred_indicators", "indicators"):
        value = tool_states.get(key)
        if isinstance(value, list):
            for item in value:
                token = str(item or "").strip()
                if token:
                    merged.append(token)
    uniq: List[str] = []
    seen = set()
    for item in merged:
        marker = item.lower()
        if marker in seen:
            continue
        seen.add(marker)
        uniq.append(item)
    return uniq


async def get_active_indicators(
    symbol: Optional[str] = None,
    timeframe: Optional[str] = "1D",
    tool_states: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Get indicators currently active on the user's frontend chart.
    These are pushed by the frontend to Redis.
    """
    states = dict(tool_states or {})
    resolved_symbol = (
        str(symbol or "").strip()
        or str(states.get("market_symbol") or "").strip()
        or str(states.get("market") or "").strip()
        or str(states.get("market_display") or "").strip()
    )
    if not resolved_symbol:
        return {
            "error": "Missing symbol. Provide symbol or set tool_states.market_symbol."
        }

    resolved_timeframe = (
        str(timeframe or "").strip()
        or _extract_timeframe_from_states(states)
        or "1D"
    )

    url = f"{CONNECTORS_API}/tradingview/indicators"
    client = await get_http_client(timeout_sec=10.0)
    try:
        last_not_found = False
        for sym in _symbol_candidates(resolved_symbol):
            for tf in _timeframe_candidates(resolved_timeframe):
                resp = await client.get(url, params={"symbol": sym, "timeframe": tf})
                if resp.status_code == 404:
                    last_not_found = True
                    continue
                resp.raise_for_status()
                payload = resp.json()
                payload_data = payload.get("data", {}) if isinstance(payload, dict) else {}
                active = payload_data.get("active_indicators")
                if isinstance(active, list):
                    return payload
                return payload

        # Fallback: if frontend already passes indicator context in tool_states,
        # return it so agent can still reason even when connector cache misses.
        fallback_indicators = _fallback_indicators_from_states(states)
        if fallback_indicators:
            return {
                "source": "tool_states",
                "symbol": _norm_symbol(resolved_symbol),
                "data_type": "indicators",
                "timestamp": None,
                "data": {
                    "timeframe": _norm_timeframe(resolved_timeframe) or resolved_timeframe,
                    "indicators": {},
                    "active_indicators": fallback_indicators,
                    "drawing_tags": [],
                    "trade_setup": {},
                },
                "info": "Using frontend tool_states fallback because TradingView cache was empty.",
            }

        if last_not_found:
            return {
                "info": "No active indicators found for this symbol/timeframe."
            }
        return {"error": "Failed to fetch TradingView indicators."}
    except Exception as e:
        return {"error": f"Failed to fetch TradingView data: {str(e)}"}
