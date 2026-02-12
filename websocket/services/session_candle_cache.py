"""Session-scoped in-memory candle cache for development.

Design goals:
- Keep all candle data in memory only (no disk writes).
- Hydrate ~N days of 1m candles from secondary providers.
- Update 1m candles continuously from primary real-time ticks.
- Serve 1m/15m/30m candles from the same canonical 1m store.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

import httpx

from config import settings
from Hyperliquid.http_client import http_client

logger = logging.getLogger(__name__)

_BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
_YAHOO_CHART_URLS = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
    "https://query2.finance.yahoo.com/v8/finance/chart/{ticker}",
)
_YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}

_CRYPTO_BASES = {"BTC", "ETH", "ARB", "SOL", "HYPE", "LIT"}
_COMMODITY_BASES = {"XAU", "XAG", "WTI", "BRN", "NG", "GC", "SI", "HG", "CL"}
_DEFAULT_SYMBOLS = ["BTC-USD", "ETH-USD", "ARB-USD", "SOL-USD", "HYPE-USD"]
_HYPE_FALLBACK_SYMBOL = "LIT-USD"

_RESOLUTION_TO_TIMEFRAME = {
    "1": "1m",
    "5": "5m",
    "15": "15m",
    "30": "30m",
    "60": "1h",
    "240": "4h",
    "D": "1d",
    "1D": "1d",
    "W": "1w",
    "1W": "1w",
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
}

_TIMEFRAME_BUCKET_MS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
    "1w": 7 * 24 * 60 * 60_000,
}

_HL_INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def normalize_symbol(symbol: str) -> str:
    raw = (symbol or "").strip().upper().replace("_", "-").replace("/", "-")
    if not raw:
        return raw

    if raw.endswith("-USDT"):
        return raw.replace("-USDT", "-USD")
    if raw in {"BTC", "ETH", "ARB", "SOL", "COIN", "HYPE", "LIT", "HYPERLIQUID"}:
        if raw == "HYPERLIQUID":
            return "HYPE-USD"
        return f"{raw}-USD"
    if raw == "XAUUSD":
        return "XAU-USD"
    if len(raw) == 6 and "-" not in raw:
        return f"{raw[:3]}-{raw[3:]}"
    if "-" not in raw and raw.endswith("USD"):
        return f"{raw[:-3]}-USD"
    return raw


def base_asset(symbol: str) -> str:
    return normalize_symbol(symbol).split("-")[0]


def _is_commodity_symbol(symbol: str) -> bool:
    base = base_asset(symbol)
    return base in _COMMODITY_BASES


def _to_yahoo_ticker(symbol: str) -> Optional[str]:
    normalized = normalize_symbol(symbol)
    base, quote = (normalized.split("-", 1) + ["USD"])[:2]
    if _is_commodity_symbol(normalized):
        return None
    if len(base) == 3 and len(quote) == 3:
        return f"{base}{quote}=X"
    return base


def to_timeframe(resolution_or_tf: Optional[str]) -> str:
    if not resolution_or_tf:
        return "1m"
    raw = str(resolution_or_tf).strip()
    return _RESOLUTION_TO_TIMEFRAME.get(raw, raw)


def is_cache_timeframe(timeframe: str) -> bool:
    return timeframe in _TIMEFRAME_BUCKET_MS


def timeframe_bucket_ms(timeframe: str) -> int:
    return _TIMEFRAME_BUCKET_MS.get(timeframe, 60_000)


def timeframe_minutes(timeframe: str) -> int:
    return max(1, timeframe_bucket_ms(timeframe) // 60_000)


def to_hl_interval(timeframe: str) -> str:
    return _HL_INTERVAL_MAP.get(timeframe, "1m")


class SessionCandleCache:
    def __init__(self, history_days: int = 4):
        self.history_days = max(1, int(history_days))
        # 4 days * 1440 minutes + headroom
        self.max_1m_bars = max(6000, self.history_days * 1440 + 600)
        self._bars_1m: Dict[str, Deque[Dict[str, Any]]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._hydrated: Dict[str, bool] = {}

    async def prewarm_default_symbols(self) -> None:
        for symbol in _DEFAULT_SYMBOLS:
            try:
                await self.hydrate(symbol)
                if symbol == "HYPE-USD" and not self._bars_1m.get("HYPE-USD"):
                    # Fallback requested by product flow: if HYPE unavailable, use LIT.
                    logger.info("HYPE secondary data unavailable, prewarming fallback %s", _HYPE_FALLBACK_SYMBOL)
                    await self.hydrate(_HYPE_FALLBACK_SYMBOL)
            except Exception as exc:
                logger.warning("Session cache prewarm failed for %s: %s", symbol, exc)

    async def hydrate(self, symbol: str, source_hint: Optional[str] = None) -> None:
        symbol = normalize_symbol(symbol)
        if not symbol:
            return
        if self._hydrated.get(symbol):
            return

        lock = self._locks.setdefault(symbol, asyncio.Lock())
        async with lock:
            if self._hydrated.get(symbol):
                return

            bars: List[Dict[str, Any]] = []
            src = (source_hint or "").strip().lower()
            is_crypto = base_asset(symbol) in _CRYPTO_BASES

            if src == "hyperliquid":
                is_crypto = True
            elif src == "ostium":
                is_crypto = False

            if settings.SECONDARY_CRYPTO_ONLY and not is_crypto:
                self._bars_1m.setdefault(symbol, deque(maxlen=self.max_1m_bars))
                self._hydrated[symbol] = True
                logger.info("Session cache skip non-crypto symbol %s (crypto-only mode)", symbol)
                return

            if is_crypto:
                bars = await self._fetch_binance_1m(symbol)
                if not bars:
                    bars = await self._fetch_hyperliquid_1m(symbol)
                if not bars and base_asset(symbol) == "HYPE":
                    logger.info("HYPE secondary data unavailable, trying fallback %s", _HYPE_FALLBACK_SYMBOL)
                    bars = await self._fetch_binance_1m(_HYPE_FALLBACK_SYMBOL)
                    if not bars:
                        bars = await self._fetch_hyperliquid_1m(_HYPE_FALLBACK_SYMBOL)
            else:
                bars = await self._fetch_yahoo_finance_1m(symbol)

            if bars:
                bars.sort(key=lambda x: int(x["timestamp"]))
                self._bars_1m[symbol] = deque(bars, maxlen=self.max_1m_bars)
                self._hydrated[symbol] = True
                logger.info("Session cache hydrated %s: %d bars", symbol, len(bars))
            else:
                # Mark hydrated to avoid hot-loop retries on every request.
                self._bars_1m.setdefault(symbol, deque(maxlen=self.max_1m_bars))
                self._hydrated[symbol] = True
                logger.warning("Session cache hydrated empty for %s", symbol)

    def update_tick(self, symbol: str, price: float, timestamp_ms: Optional[int] = None, volume: float = 0.0) -> None:
        symbol = normalize_symbol(symbol)
        if not symbol:
            return
        if timestamp_ms is None:
            timestamp_ms = _now_ms()

        ts_min = (int(timestamp_ms) // 60000) * 60000
        px = _safe_float(price, 0.0)
        if px <= 0:
            return

        bars = self._bars_1m.setdefault(symbol, deque(maxlen=self.max_1m_bars))

        if not bars:
            bars.append(
                {
                    "timestamp": ts_min,
                    "open": px,
                    "high": px,
                    "low": px,
                    "close": px,
                    "volume": max(0.0, _safe_float(volume, 0.0)),
                    "symbol": symbol,
                }
            )
            return

        last = bars[-1]
        last_ts = int(last["timestamp"])
        if ts_min < last_ts:
            # Ignore out-of-order older ticks for simplicity.
            return

        if ts_min == last_ts:
            last["high"] = max(_safe_float(last["high"]), px)
            last["low"] = min(_safe_float(last["low"]), px)
            last["close"] = px
            last["volume"] = _safe_float(last.get("volume"), 0.0) + max(0.0, _safe_float(volume, 0.0))
            return

        # Fill missing minute buckets to avoid chart gaps during active session.
        prev_close = _safe_float(last["close"], px)
        cursor = last_ts + 60000
        while cursor < ts_min:
            bars.append(
                {
                    "timestamp": cursor,
                    "open": prev_close,
                    "high": prev_close,
                    "low": prev_close,
                    "close": prev_close,
                    "volume": 0.0,
                    "symbol": symbol,
                }
            )
            cursor += 60000

        bars.append(
            {
                "timestamp": ts_min,
                "open": prev_close,
                "high": max(prev_close, px),
                "low": min(prev_close, px),
                "close": px,
                "volume": max(0.0, _safe_float(volume, 0.0)),
                "symbol": symbol,
            }
        )

    async def get_candles(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 300,
        source_hint: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        symbol = normalize_symbol(symbol)
        tf = to_timeframe(timeframe)
        if not is_cache_timeframe(tf):
            tf = "1m"

        await self.hydrate(symbol, source_hint=source_hint)
        bars = list(self._bars_1m.get(symbol, []))
        if not bars:
            return []

        if tf == "1m":
            return bars[-max(1, limit):]

        return self._aggregate_from_1m(symbol=symbol, bars_1m=bars, timeframe=tf, limit=limit)

    @staticmethod
    def _aggregate_from_1m(
        symbol: str,
        bars_1m: List[Dict[str, Any]],
        timeframe: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        bucket_ms = timeframe_bucket_ms(timeframe)
        agg: Dict[int, Dict[str, Any]] = {}

        for bar in bars_1m:
            ts = int(bar["timestamp"])
            bucket = (ts // bucket_ms) * bucket_ms
            open_px = _safe_float(bar["open"])
            high_px = _safe_float(bar["high"])
            low_px = _safe_float(bar["low"])
            close_px = _safe_float(bar["close"])
            vol = _safe_float(bar.get("volume"), 0.0)

            current = agg.get(bucket)
            if current is None:
                agg[bucket] = {
                    "timestamp": bucket,
                    "open": open_px,
                    "high": high_px,
                    "low": low_px,
                    "close": close_px,
                    "volume": vol,
                    "symbol": symbol,
                }
                continue

            current["high"] = max(_safe_float(current["high"]), high_px)
            current["low"] = min(_safe_float(current["low"]), low_px)
            current["close"] = close_px
            current["volume"] = _safe_float(current.get("volume"), 0.0) + vol

        merged = [agg[k] for k in sorted(agg.keys())]
        return merged[-max(1, limit):]

    async def _fetch_binance_1m(self, symbol: str) -> List[Dict[str, Any]]:
        base = base_asset(symbol)
        pair = f"{base}USDT"
        end_ms = _now_ms()
        start_ms = end_ms - (self.history_days * 24 * 60 * 60 * 1000)
        cursor = start_ms
        out: List[Dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=15.0) as client:
            while cursor < end_ms:
                params = {
                    "symbol": pair,
                    "interval": "1m",
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": 1000,
                }
                try:
                    rows = await self._json_get_with_ssl_fallback(client, _BINANCE_KLINES_URL, params)
                except Exception as exc:
                    logger.warning("Binance fetch failed for %s: %s", symbol, exc)
                    break

                if not isinstance(rows, list) or not rows:
                    break

                last_open = None
                for row in rows:
                    # Binance kline shape: [openTime, open, high, low, close, volume, ...]
                    ts = int(row[0])
                    last_open = ts
                    out.append(
                        {
                            "timestamp": ts,
                            "open": _safe_float(row[1]),
                            "high": _safe_float(row[2]),
                            "low": _safe_float(row[3]),
                            "close": _safe_float(row[4]),
                            "volume": _safe_float(row[5]),
                            "symbol": symbol,
                        }
                    )

                if last_open is None:
                    break
                next_cursor = last_open + 60_000
                if next_cursor <= cursor:
                    break
                cursor = next_cursor
                await asyncio.sleep(0.05)

        return out

    async def _fetch_yahoo_finance_1m(self, symbol: str) -> List[Dict[str, Any]]:
        normalized = normalize_symbol(symbol)
        if _is_commodity_symbol(normalized):
            logger.info("Skipping commodity secondary history for %s", normalized)
            return []
        ticker = _to_yahoo_ticker(normalized)
        if not ticker:
            return []

        range_days = max(1, min(7, self.history_days + 1))
        params = {
            "interval": "1m",
            "range": f"{range_days}d",
            "includePrePost": "true",
            "events": "div,splits",
        }

        payload: Optional[Dict[str, Any]] = None
        last_exc: Optional[Exception] = None
        try:
            async with httpx.AsyncClient(timeout=25.0, headers=_YAHOO_HEADERS) as client:
                for attempt in range(3):
                    for url_template in _YAHOO_CHART_URLS:
                        try:
                            payload = await self._json_get_with_ssl_fallback(
                                client,
                                url_template.format(ticker=ticker),
                                params,
                            )
                            break
                        except httpx.HTTPStatusError as exc:
                            last_exc = exc
                            status = exc.response.status_code if exc.response else None
                            if status in {404}:
                                # Unsupported symbol on Yahoo.
                                return []
                            # Try next endpoint / retry on throttling.
                            continue
                        except Exception as exc:
                            last_exc = exc
                            continue
                    if payload is not None:
                        break
                    await asyncio.sleep(0.6 * (attempt + 1))
        except Exception as exc:
            last_exc = exc

        if payload is None:
            logger.warning(
                "Yahoo Finance fetch failed for %s (%s): %s",
                symbol,
                ticker,
                last_exc,
            )
            return []

        if not isinstance(payload, dict):
            return []

        chart = payload.get("chart", {})
        result_list = chart.get("result") if isinstance(chart, dict) else None
        if not isinstance(result_list, list) or not result_list:
            error_obj = chart.get("error") if isinstance(chart, dict) else None
            logger.warning(
                "Yahoo Finance no series for %s (%s), error=%s",
                symbol,
                ticker,
                error_obj,
            )
            return []

        result = result_list[0] if isinstance(result_list[0], dict) else {}
        timestamps = result.get("timestamp")
        indicators = result.get("indicators", {})
        quote_list = indicators.get("quote") if isinstance(indicators, dict) else None
        quote = quote_list[0] if isinstance(quote_list, list) and quote_list else {}
        opens = quote.get("open") if isinstance(quote, dict) else None
        highs = quote.get("high") if isinstance(quote, dict) else None
        lows = quote.get("low") if isinstance(quote, dict) else None
        closes = quote.get("close") if isinstance(quote, dict) else None
        volumes = quote.get("volume") if isinstance(quote, dict) else None
        if not isinstance(timestamps, list):
            return []

        end_ms = _now_ms()
        start_ms = end_ms - (self.history_days * 24 * 60 * 60 * 1000)
        out: List[Dict[str, Any]] = []
        for idx, ts in enumerate(timestamps):
            try:
                ts_ms = int(ts) * 1000
            except Exception:
                continue
            if ts_ms < start_ms or ts_ms > end_ms:
                continue
            open_px = _safe_float(opens[idx] if isinstance(opens, list) and idx < len(opens) else None)
            high_px = _safe_float(highs[idx] if isinstance(highs, list) and idx < len(highs) else None)
            low_px = _safe_float(lows[idx] if isinstance(lows, list) and idx < len(lows) else None)
            close_px = _safe_float(closes[idx] if isinstance(closes, list) and idx < len(closes) else None)
            if open_px <= 0 or high_px <= 0 or low_px <= 0 or close_px <= 0:
                continue
            volume = _safe_float(volumes[idx], 0.0) if isinstance(volumes, list) and idx < len(volumes) else 0.0
            out.append(
                {
                    "timestamp": ts_ms,
                    "open": open_px,
                    "high": high_px,
                    "low": low_px,
                    "close": close_px,
                    "volume": max(0.0, volume),
                    "symbol": normalized,
                }
            )
        out.sort(key=lambda x: int(x["timestamp"]))
        return out

    async def _fetch_hyperliquid_1m(self, symbol: str) -> List[Dict[str, Any]]:
        base = base_asset(symbol)
        end_ms = _now_ms()
        start_ms = end_ms - (self.history_days * 24 * 60 * 60 * 1000)
        candles = await http_client.get_candles(base, interval="1m", start_time=start_ms, end_time=end_ms)
        out: List[Dict[str, Any]] = []
        for c in candles or []:
            out.append(
                {
                    "timestamp": int(c.get("timestamp", 0)),
                    "open": _safe_float(c.get("open")),
                    "high": _safe_float(c.get("high")),
                    "low": _safe_float(c.get("low")),
                    "close": _safe_float(c.get("close")),
                    "volume": _safe_float(c.get("volume"), 0.0),
                    "symbol": normalize_symbol(c.get("symbol", symbol)),
                }
            )
        if out:
            logger.warning("Secondary crypto fallback used (Hyperliquid) for %s", symbol)
        return out

    async def _json_get_with_ssl_fallback(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: Dict[str, Any],
    ) -> Any:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as first_exc:
            msg = str(first_exc).lower()
            if "certificate_verify_failed" not in msg:
                raise
            logger.warning("SSL verify failed for %s, retrying with verify=False (dev fallback)", url)
            async with httpx.AsyncClient(timeout=client.timeout, verify=False) as insecure_client:
                response = await insecure_client.get(url, params=params)
                response.raise_for_status()
                return response.json()


# Shared singleton for app/runtime + routers.
session_candle_cache = SessionCandleCache(history_days=getattr(settings, "SESSION_HISTORY_DAYS", 4))
