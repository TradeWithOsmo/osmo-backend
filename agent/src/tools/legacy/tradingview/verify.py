from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

try:
    from agent.Config.tools_config import DATA_SOURCES
except Exception:
    from backend.agent.Config.tools_config import DATA_SOURCES


CONNECTORS_API = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")

_INDICATOR_NAME_MAP: Dict[str, str] = {
    "RSI": "Relative Strength Index",
    "Stoch": "Stochastic",
    "StochRSI": "Stochastic RSI",
    "CCI": "Commodity Channel Index",
    "MACD": "MACD",
    "MFI": "Money Flow Index",
    "ROC": "Rate Of Change",
    "TSI": "True Strength Index",
    "Williams %R": "Williams %R",
    "AO": "Awesome Oscillator",
    "KST": "Know Sure Thing",
    "EMA": "Moving Average Exponential",
    "SMA": "Moving Average",
    "WMA": "Moving Average Weighted",
    "HMA": "Hull Moving Average",
    "VWMA": "VWMA",
    "MA": "Moving Average",
    "Bollinger Bands": "Bollinger Bands",
    "BB": "Bollinger Bands",
    "SuperTrend": "SuperTrend",
    "Parabolic SAR": "Parabolic SAR",
    "SAR": "Parabolic SAR",
    "Ichimoku": "Ichimoku Cloud",
    "ADX": "Average Directional Index",
    "DMI": "Directional Movement",
    "Mass Index": "Mass Index",
    "ATR": "Average True Range",
    "Keltner": "Keltner Channels",
    "Donchian": "Donchian Channels",
    "HV": "Historical Volatility",
    "OBV": "On Balance Volume",
    "VWAP": "VWAP",
    "VPVR": "Volume Profile Visible Range",
    "VPFR": "Volume Profile Fixed Range",
    "Volume": "Volume",
    "CMF": "Chaikin Money Flow",
    "EOM": "Ease Of Movement",
}


def _as_text(v: Any) -> str:
    return str(v or "").strip()


def _norm_symbol(v: Any) -> str:
    return _as_text(v).upper().replace("/", "-").replace("_", "-")


def _norm_timeframe(v: Any) -> str:
    raw = _as_text(v).upper().replace(" ", "")
    if not raw:
        return ""
    mapping = {
        "60": "1H",
        "1H": "1H",
        "240": "4H",
        "4H": "4H",
        "D": "1D",
        "1D": "1D",
        "W": "1W",
        "1W": "1W",
        "1": "1m",
        "3": "3m",
        "5": "5m",
        "15": "15m",
        "30": "30m",
        "1M": "1m",
        "3M": "3m",
        "5M": "5m",
        "15M": "15m",
        "30M": "30m",
    }
    return mapping.get(raw, raw)


def _norm_indicator_token(v: Any) -> str:
    return _as_text(v).lower().replace("_", " ").replace("-", " ")


def _indicator_match_tokens(v: Any) -> set[str]:
    raw = _as_text(v)
    if not raw:
        return set()

    normalized = _norm_indicator_token(raw)
    tokens: set[str] = {normalized}

    canonical = _INDICATOR_NAME_MAP.get(raw) or _INDICATOR_NAME_MAP.get(raw.upper()) or _INDICATOR_NAME_MAP.get(raw.title())
    if canonical:
        tokens.add(_norm_indicator_token(canonical))
    return {item for item in tokens if item}


def _as_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, bool):
            return float(int(v))
        return float(v)
    except Exception:
        return None


def _float_equal(a: Any, b: Any) -> bool:
    fa = _as_float(a)
    fb = _as_float(b)
    if fa is None or fb is None:
        return False
    tol = max(1e-6, abs(fb) * 1e-6)
    return abs(fa - fb) <= tol


async def verify_tradingview_state(
    symbol: str,
    timeframe: str = "1D",
    *,
    require_indicators: Optional[List[str]] = None,
    forbid_indicators: Optional[List[str]] = None,
    require_drawings: Optional[List[str]] = None,
    require_trade_setup: Optional[Dict[str, Any]] = None,
    timeout_sec: float = 6.0,
    poll_interval_sec: float = 0.25,
) -> Dict[str, Any]:
    """
    Verify TradingView frontend state that is pushed into /api/connectors/tradingview/indicators.

    Covers "human operator" flow checks after write tools:
    - set_symbol / set_timeframe: verify cache exists for symbol+timeframe
    - add_indicator: verify indicator name is present in active_indicators
    - remove_indicator: verify indicator name is absent from active_indicators
    - draw/add_price_alert/mark_trading_session: verify drawing tag/id exists in drawing_tags
    - setup_trade: verify trade_setup fields match expected (numeric tolerance)
    """
    want_symbol = _norm_symbol(symbol)
    want_tf = _norm_timeframe(timeframe)
    want_ind = [_as_text(x) for x in (require_indicators or []) if _as_text(x)]
    forbid_ind = [_as_text(x) for x in (forbid_indicators or []) if _as_text(x)]
    want_draw = [_as_text(x) for x in (require_drawings or []) if _as_text(x)]
    want_trade = dict(require_trade_setup or {})

    deadline = time.time() + max(0.0, float(timeout_sec))
    attempts = 0
    last_payload: Any = None

    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            attempts += 1
            try:
                resp = await client.get(
                    f"{CONNECTORS_API}/tradingview/indicators",
                    params={"symbol": symbol, "timeframe": timeframe},
                )
            except Exception as exc:
                last_payload = {"error": f"Failed to query tradingview indicators: {exc}"}
            else:
                if resp.status_code == 404:
                    last_payload = {"error": "No TradingView indicators cached yet"}
                else:
                    try:
                        resp.raise_for_status()
                        last_payload = resp.json() if resp.content else {}
                    except Exception as exc:
                        last_payload = {"error": f"TradingView indicators HTTP error: {exc}", "http_status": resp.status_code}

            payload = last_payload if isinstance(last_payload, dict) else {"raw": last_payload}
            data = (payload.get("data") or {}) if isinstance(payload.get("data"), dict) else {}
            got_symbol = _norm_symbol(payload.get("symbol") or data.get("symbol") or "")
            got_tf = _norm_timeframe(data.get("timeframe") or payload.get("timeframe") or "")

            active_indicators = data.get("active_indicators") or []
            if not isinstance(active_indicators, list):
                active_indicators = []
            active_tokens = {_norm_indicator_token(x) for x in active_indicators}

            drawing_tags = data.get("drawing_tags") or []
            if not isinstance(drawing_tags, list):
                drawing_tags = []
            drawing_set = {str(x) for x in drawing_tags if _as_text(x)}

            trade_setup = data.get("trade_setup") or {}
            if not isinstance(trade_setup, dict):
                trade_setup = {}

            missing: List[str] = []
            mismatch: List[str] = []

            if want_symbol and got_symbol and got_symbol != want_symbol:
                mismatch.append(f"symbol expected={want_symbol} actual={got_symbol}")
            if want_tf and got_tf and got_tf != want_tf:
                mismatch.append(f"timeframe expected={want_tf} actual={got_tf}")

            for ind_name in want_ind:
                required_tokens = _indicator_match_tokens(ind_name)
                if not required_tokens.intersection(active_tokens):
                    missing.append(f"indicator:{_norm_indicator_token(ind_name)}")

            for ind_name in forbid_ind:
                forbidden_tokens = _indicator_match_tokens(ind_name)
                if forbidden_tokens.intersection(active_tokens):
                    mismatch.append(f"indicator_present:{_norm_indicator_token(ind_name)}")

            for d in want_draw:
                if d not in drawing_set:
                    missing.append(f"drawing:{d}")

            for k, v in want_trade.items():
                if k not in trade_setup:
                    missing.append(f"trade_setup:{k}")
                    continue
                actual = trade_setup.get(k)
                if _as_float(v) is not None and _as_float(actual) is not None:
                    if not _float_equal(actual, v):
                        mismatch.append(f"trade_setup:{k} expected={_as_text(v)} actual={_as_text(actual)}")
                else:
                    if _as_text(actual).lower() != _as_text(v).lower():
                        mismatch.append(f"trade_setup:{k} expected={_as_text(v)} actual={_as_text(actual)}")

            ok = not missing and not mismatch and bool(payload.get("data"))
            if ok:
                return {
                    "status": "ok",
                    "verified": True,
                    "symbol": want_symbol,
                    "timeframe": want_tf,
                    "attempts": attempts,
                    "active_indicators": active_indicators,
                    "drawing_tags": drawing_tags,
                    "trade_setup": trade_setup,
                }

            if time.time() >= deadline:
                return {
                    "status": "error",
                    "verified": False,
                    "symbol": want_symbol,
                    "timeframe": want_tf,
                    "attempts": attempts,
                    "missing": missing,
                    "mismatch": mismatch,
                    "last_payload": payload,
                    "error": f"TradingView state not verified within {timeout_sec:.1f}s",
                }

            await asyncio.sleep(max(0.05, float(poll_interval_sec)))
