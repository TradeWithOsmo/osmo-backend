"""
Market Data Access Tool

Aggregates data from Hyperliquid (Crypto), Ostium (RWA), and Chainlink (Oracle).
"""

import httpx
from typing import Dict, Any, List, Optional
import pandas as pd
try:
    from agent.Config.tools_config import DATA_SOURCES
except Exception:
    from backend.agent.Config.tools_config import DATA_SOURCES

# Base URL for connectors API
CONNECTORS_API = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")
FIAT_CODES = {"USD", "EUR", "GBP", "CHF", "JPY", "CAD", "AUD", "NZD", "MXN", "HKD"}


def _normalize_symbol_candidates(symbol: str) -> List[str]:
    """
    Build symbol aliases for matching connector payloads.
    Examples:
      BTC -> [BTC, BTC-USD, BTCUSDT]
      BTC-USD -> [BTC-USD, BTC, BTCUSDT]
      BTCUSDT -> [BTCUSDT, BTC-USD, BTC]
    """
    raw = (symbol or "").strip().upper().replace("/", "-").replace("_", "-")
    if not raw:
        return []
    candidates = [raw]
    if "-" in raw:
        base_pair, quote_pair = raw.split("-", 1)
        if base_pair and quote_pair:
            candidates.extend([f"{base_pair}{quote_pair}", f"{base_pair}/{quote_pair}"])
    elif len(raw) == 6 and raw[:3] in FIAT_CODES and raw[3:] in FIAT_CODES:
        base_pair = raw[:3]
        quote_pair = raw[3:]
        candidates.extend([f"{base_pair}-{quote_pair}", f"{base_pair}/{quote_pair}"])

    base = raw
    if raw.endswith("USDT"):
        base = raw[:-4]
    elif raw.endswith("USD"):
        base = raw[:-3]
    elif "-" in raw:
        base = raw.split("-", 1)[0]

    if base:
        candidates.extend([f"{base}-USD", f"{base}USDT", base])

    # Keep order, remove duplicates
    seen = set()
    uniq = []
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            uniq.append(item)
    return uniq


def _looks_like_fiat_cross(symbol: str) -> bool:
    raw = (symbol or "").strip().upper().replace("/", "-").replace("_", "-")
    if "-" in raw:
        base, quote = raw.split("-", 1)
        return base in FIAT_CODES and quote in FIAT_CODES
    if len(raw) == 6:
        base, quote = raw[:3], raw[3:]
        return base in FIAT_CODES and quote in FIAT_CODES
    return False


def _select_market(markets: List[Dict[str, Any]], symbol: str) -> Optional[Dict[str, Any]]:
    candidates = _normalize_symbol_candidates(symbol)
    if not candidates:
        return None
    for c in candidates:
        for row in markets:
            row_symbol = str(row.get("symbol", "")).upper().replace("/", "-").replace("_", "-")
            if row_symbol == c:
                return row
    return None


def _normalize_asset_type(asset_type: str) -> str:
    value = (asset_type or "crypto").strip().lower()
    return "crypto" if value in {"crypto", "hyperliquid"} else "rwa"


def _symbol_for_connector_route(symbol: str, asset_type: str) -> str:
    raw = (symbol or "").strip().upper().replace("/", "-").replace("_", "-")
    if not raw:
        return ""
    if _normalize_asset_type(asset_type) == "crypto":
        if raw.endswith("USDT") and len(raw) > 4:
            return raw[:-4]
        if raw.endswith("USD") and len(raw) > 3 and "-" not in raw:
            return raw[:-3]
        if "-" in raw:
            return raw.split("-", 1)[0]
        return raw
    return raw

async def get_price(symbol: str, asset_type: str = "crypto") -> Dict[str, Any]:
    """
    Get current price for a symbol.
    
    Args:
        symbol: e.g. "BTC", "EURUSD"
        asset_type: "crypto" (Hyperliquid) or "rwa" (Ostium)
    """
    asset_type = _normalize_asset_type(asset_type)
    if asset_type == "crypto" and _looks_like_fiat_cross(symbol):
        # Auto-correct common model misses, e.g. USD/CHF requested as crypto.
        asset_type = "rwa"
    endpoint = "/hyperliquid/prices" if asset_type == "crypto" else "/ostium/prices"
    url = f"{CONNECTORS_API}{endpoint}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, list):
                return {"error": "Unexpected price payload format."}

            row = _select_market(payload, symbol)
            if not row:
                return {
                    "error": f"Symbol '{symbol}' not found in {asset_type} markets.",
                    "available_count": len(payload),
                }

            return {
                "symbol": row.get("symbol", symbol),
                "asset_type": asset_type,
                "price": row.get("price"),
                "change_24h": row.get("change_24h"),
                "change_percent_24h": row.get("change_percent_24h"),
                "volume_24h": row.get("volume_24h"),
                "high_24h": row.get("high_24h"),
                "low_24h": row.get("low_24h"),
                "raw": row,
            }
        except Exception as e:
            return {"error": f"Failed to fetch price: {str(e)}"}

async def get_candles(symbol: str, timeframe: str = "1H", limit: int = 100, asset_type: str = "crypto") -> Dict[str, Any]:
    """
    Get OHLCV candles from connectors API.
    """
    asset_type = _normalize_asset_type(asset_type)
    route_symbol = _symbol_for_connector_route(symbol, asset_type=asset_type)
    url = f"{CONNECTORS_API}/candles/{route_symbol}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                url,
                params={"timeframe": timeframe, "limit": int(limit), "asset_type": asset_type},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": f"Failed to fetch candles: {str(e)}"}

async def get_orderbook(symbol: str, asset_type: str = "crypto") -> Dict[str, Any]:
    """
    Get L2 Orderbook (Crypto/Hyperliquid only).
    """
    asset_type = _normalize_asset_type(asset_type)
    if asset_type != "crypto":
        return {"error": "Orderbook is available for crypto markets only."}
    route_symbol = _symbol_for_connector_route(symbol, asset_type=asset_type)
    url = f"{CONNECTORS_API}/orderbook/{route_symbol}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(url, params={"asset_type": asset_type})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": f"Failed to fetch orderbook: {str(e)}"}

async def get_funding_rate(symbol: str, asset_type: str = "crypto") -> Dict[str, Any]:
    """
    Get Funding Rate (Crypto/Hyperliquid only).
    """
    asset_type = _normalize_asset_type(asset_type)
    route_symbol = _symbol_for_connector_route(symbol, asset_type=asset_type)
    url = f"{CONNECTORS_API}/funding/{route_symbol}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(url, params={"asset_type": asset_type})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": f"Failed to fetch funding rate: {str(e)}"}

async def get_ticker_stats(symbol: str, asset_type: str = "crypto") -> Dict[str, Any]:
    """
    Get 24h Stats (Volume, Change).
    """
    # Ostium returns this in get_price response (volume_24h).
    # Hyperliquid price response also has data.
    price_data = await get_price(symbol, asset_type=asset_type)
    if "error" in price_data: return price_data
    
    return {
        "volume_24h": price_data.get("volume_24h", 0),
        "change_24h": price_data.get("change_24h", 0),
        "price": price_data.get("price")
    }

async def get_chainlink_price(symbol: str) -> Dict[str, Any]:
    """
    Get Verified Oracle Price via Chainlink.
    """
    # Chainlink is integrated as a connector.
    # Need to check how to route specific connector in get_price
    # Current implementation of get_price routers by asset_type.
    # TODO: Add specific route for chainlink in api_routes.
    return {"error": "Chainlink direct access not exposed in API"}


def _coerce_candles_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    candles = payload.get("candles")
    if isinstance(candles, list):
        return [row for row in candles if isinstance(row, dict)]
    nested = payload.get("raw")
    if isinstance(nested, dict):
        return _coerce_candles_rows(nested)
    return []


def _row_value(row: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        if key in row:
            try:
                return float(row.get(key))
            except Exception:
                continue
    return None


def _normalize_candle_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    o = _row_value(row, "open", "o")
    h = _row_value(row, "high", "h")
    l = _row_value(row, "low", "l")
    c = _row_value(row, "close", "c")
    if h is None or l is None:
        return None
    if o is None:
        o = c if c is not None else h
    if c is None:
        c = o
    return {
        "time": row.get("time") or row.get("timestamp") or row.get("t"),
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
    }


async def get_high_low_levels(
    symbol: str,
    timeframe: str = "1H",
    lookback: int = 7,
    limit: Optional[int] = None,
    asset_type: str = "crypto",
) -> Dict[str, Any]:
    """
    Compute rolling high/low levels (simple support/resistance) from OHLC candles.

    Example:
    - lookback=5  -> high_5 / low_5 from last 5 candles
    - lookback=20 -> high_20 / low_20 from last 20 candles
    """
    try:
        lookback_value = int(lookback)
    except Exception:
        lookback_value = 7
    lookback_value = max(2, min(lookback_value, 500))

    required_limit = max(lookback_value, int(limit or lookback_value))
    candles_payload = await get_candles(
        symbol=symbol,
        timeframe=timeframe,
        limit=required_limit,
        asset_type=asset_type,
    )
    if isinstance(candles_payload, dict) and candles_payload.get("error"):
        return candles_payload

    raw_rows = _coerce_candles_rows(candles_payload)
    rows: List[Dict[str, Any]] = []
    for item in raw_rows:
        normalized = _normalize_candle_row(item)
        if normalized is not None:
            rows.append(normalized)

    if len(rows) < lookback_value:
        return {
            "error": (
                f"Not enough candle data for lookback={lookback_value}. "
                f"available={len(rows)}"
            ),
            "symbol": symbol,
            "timeframe": timeframe,
            "lookback": lookback_value,
            "available_candles": len(rows),
        }

    df = pd.DataFrame(rows)
    high_col = f"high_{lookback_value}"
    low_col = f"low_{lookback_value}"
    df[high_col] = df["high"].rolling(window=lookback_value).max()
    df[low_col] = df["low"].rolling(window=lookback_value).min()

    latest = df.iloc[-1]
    resistance = float(latest[high_col])
    support = float(latest[low_col])
    midpoint = float((resistance + support) / 2.0)

    return {
        "status": "ok",
        "symbol": symbol,
        "timeframe": timeframe,
        "asset_type": _normalize_asset_type(asset_type),
        "lookback": lookback_value,
        "candle_count": int(len(df)),
        "support": support,
        "resistance": resistance,
        "midpoint": midpoint,
        "latest_high": float(latest["high"]),
        "latest_low": float(latest["low"]),
        "latest_close": float(latest["close"]),
        "levels": {
            high_col: resistance,
            low_col: support,
        },
    }
