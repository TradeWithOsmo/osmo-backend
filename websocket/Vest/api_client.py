"""
Vest Exchange API client
Based on official API docs: https://server-prod.hz.vestmarkets.com/v2
Symbols: BTC-PERP, ETH-PERP, SOL-PERP (crypto), AUD-USD-PERP (forex/index)
Public endpoints (no auth required):
  GET /exchangeInfo    → all symbols + metadata
  GET /ticker/latest  → mark/index prices, funding rate
  GET /ticker/24hr    → 24h OHLCV
  GET /klines         → candlestick data
  GET /depth          → orderbook
WebSocket: wss://ws-prod.hz.vestmarkets.com/ws-api?version=1.0
"""
import httpx
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

VEST_REST_BASE = "https://server-prod.hz.vestmarkets.com/v2"
VEST_ACCOUNT_GROUP = 0  # default; returned by /register


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout_s: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout_s = timeout_s
        self.failures = 0
        self.last_failure_time: Optional[datetime] = None
        self.is_open = False

    def record_success(self):
        self.failures = 0
        self.is_open = False

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = datetime.now()
        if self.failures >= self.failure_threshold:
            self.is_open = True
            logger.warning(f"[Vest] Circuit breaker OPEN after {self.failures} failures")

    def can_attempt(self) -> bool:
        if not self.is_open:
            return True
        if self.last_failure_time:
            elapsed = (datetime.now() - self.last_failure_time).total_seconds()
            if elapsed >= self.timeout_s:
                self.is_open = False
                self.failures = 0
                return True
        return False


class VestAPIClient:
    """
    HTTP client for Vest Exchange.
    - Base URL: https://server-prod.hz.vestmarkets.com/v2
    - Required header: xrestservermm: restserver{account_group}
    - Symbols: BTC-PERP, ETH-PERP (crypto), AUD-USD-PERP (forex)
    """

    def __init__(self, rest_base: str = VEST_REST_BASE, account_group: int = VEST_ACCOUNT_GROUP):
        self.rest_base = rest_base.rstrip("/")
        self.account_group = account_group
        self._headers = {
            "xrestservermm": f"restserver{account_group}",
            "Content-Type": "application/json",
        }
        self.client = httpx.AsyncClient(timeout=10.0, verify=False, headers=self._headers)
        self.circuit_breaker = CircuitBreaker()
        self.last_successful_fetch: Optional[datetime] = None

    async def get_exchange_info(self) -> Optional[Dict[str, Any]]:
        """GET /exchangeInfo — all symbols + margin/fee info."""
        try:
            resp = await self.client.get(f"{self.rest_base}/exchangeInfo")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"[Vest] /exchangeInfo failed: {e}")
            return None

    async def get_latest_tickers(self, symbols: Optional[List[str]] = None) -> Optional[List[Dict]]:
        """
        GET /ticker/latest — mark price, index price, funding rate per symbol.
        Returns list of ticker dicts.
        """
        if not self.circuit_breaker.can_attempt():
            return None
        try:
            params = {}
            if symbols:
                params["symbols"] = ",".join(symbols)
            resp = await self.client.get(f"{self.rest_base}/ticker/latest", params=params)
            resp.raise_for_status()
            data = resp.json()
            tickers = data.get("tickers", [])
            self.circuit_breaker.record_success()
            self.last_successful_fetch = datetime.now()
            return tickers
        except Exception as e:
            logger.debug(f"[Vest] /ticker/latest failed: {e}")
            self.circuit_breaker.record_failure()
            return None

    async def get_24h_tickers(self, symbols: Optional[List[str]] = None) -> Optional[List[Dict]]:
        """GET /ticker/24hr — OHLCV + price change."""
        try:
            params = {}
            if symbols:
                params["symbols"] = ",".join(symbols)
            resp = await self.client.get(f"{self.rest_base}/ticker/24hr", params=params)
            resp.raise_for_status()
            return resp.json().get("tickers", [])
        except Exception as e:
            logger.debug(f"[Vest] /ticker/24hr failed: {e}")
            return None

    async def get_latest_prices(self) -> Optional[List[Dict[str, Any]]]:
        """
        Main polling method — fetches exchange info (for symbol list) +
        latest tickers (for prices/funding) + 24hr tickers (for OHLC/volume/change).
        """
        if not self.circuit_breaker.can_attempt():
            return None

        # First get all symbols
        exchange_info = await self.get_exchange_info()
        symbols_meta: Dict[str, Dict] = {}
        if exchange_info:
            for s in exchange_info.get("symbols", []):
                sym = s.get("symbol", "")
                if sym:
                    symbols_meta[sym] = s

        # Then get live tickers
        tickers = await self.get_latest_tickers()
        if tickers is None:
            return None

        # Also get 24h stats for change%, high, low, volume
        tickers_24h_list = await self.get_24h_tickers() or []
        tickers_24h: Dict[str, Dict] = {t.get("symbol", ""): t for t in tickers_24h_list}

        results = []
        for ticker in tickers:
            sym = ticker.get("symbol", "")
            if not sym:
                continue

            # Parse Vest symbol format: BTC-PERP → base=BTC, BTC-USD-PERP → base=BTC, quote=USD
            parts = sym.replace("-PERP", "").split("-")
            base = parts[0].upper()
            quote = parts[1].upper() if len(parts) > 1 else "USD"

            meta = symbols_meta.get(sym, {})
            t24 = tickers_24h.get(sym, {})

            mark_price = float(ticker.get("markPrice") or 0)
            open_price = float(t24.get("openPrice") or mark_price)
            close_price = float(t24.get("lastPrice") or mark_price)
            change_24h = close_price - open_price
            change_pct = (change_24h / open_price * 100) if open_price else 0.0

            results.append({
                "symbol": sym,
                "tradingSymbol": sym,
                "from": base,
                "to": quote,
                "price": mark_price,
                "index_price": float(ticker.get("indexPrice") or 0),
                "funding_rate": float(ticker.get("oneHrFundingRate") or 0),
                "status": ticker.get("status", "TRADING"),
                "imbalance": float(ticker.get("imbalance") or 0),
                "max_leverage": int(1 / float(meta.get("initMarginRatio") or 0.1)),
                "source": "vest",
                "high_24h": float(t24.get("highPrice") or 0),
                "low_24h": float(t24.get("lowPrice") or 0),
                "volume_24h": float(t24.get("volume") or t24.get("quoteVolume") or 0),
                "change_24h": change_24h,
                "change_percent_24h": change_pct,
                "open_interest": float(ticker.get("openInterest") or 0),
            })

        self.circuit_breaker.record_success()
        self.last_successful_fetch = datetime.now()
        return results

    async def get_klines(self, symbol: str, interval: str = "1m", limit: int = 100,
                         start_time: Optional[int] = None, end_time: Optional[int] = None) -> Optional[List]:
        """GET /klines — OHLCV candlesticks."""
        try:
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
            resp = await self.client.get(f"{self.rest_base}/klines", params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"[Vest] /klines {symbol} failed: {e}")
            return None

    async def get_depth(self, symbol: str, limit: int = 20) -> Optional[Dict]:
        """GET /depth — bid/ask orderbook."""
        try:
            resp = await self.client.get(f"{self.rest_base}/depth", params={"symbol": symbol, "limit": limit})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"[Vest] /depth {symbol} failed: {e}")
            return None

    async def get_recent_trades(self, symbol: str, limit: int = 50) -> Optional[List]:
        """GET /trades — recent trades.

        Vest returns a raw JSON array:
          [{"id": "0x...", "price": "65907.1", "qty": "0.002", "quoteQty": "...", "time": 1234}, ...]
        Negative qty means Sell side.
        We normalise to {px, sz, side, time} so _normalize_trade_item in main.py can handle it.
        """
        try:
            resp = await self.client.get(
                f"{self.rest_base}/trades", params={"symbol": symbol, "limit": limit}
            )
            resp.raise_for_status()
            data = resp.json()

            # API returns a bare list; guard against legacy wrapped format
            if isinstance(data, dict):
                rows = data.get("trades", [])
            elif isinstance(data, list):
                rows = data
            else:
                return []

            normalised = []
            for row in rows:
                try:
                    price_raw = float(row.get("price") or 0)
                    qty_raw = float(row.get("qty") or 0)
                    if price_raw <= 0:
                        continue
                    side = "S" if qty_raw < 0 else "B"
                    normalised.append({
                        "px": str(abs(price_raw)),
                        "sz": str(abs(qty_raw)),
                        "side": side,
                        "time": row.get("time"),
                        "id": row.get("id"),
                    })
                except Exception:
                    continue
            return normalised
        except Exception as e:
            logger.debug(f"[Vest] /trades {symbol} failed: {e}")
            return None

    async def get_markets(self) -> List[Dict[str, Any]]:
        return await self.get_latest_prices() or []

    def get_status(self) -> dict:
        return {
            "exchange": "vest",
            "chain": "base",
            "rest_base": self.rest_base,
            "account_group": self.account_group,
            "circuit_breaker_open": self.circuit_breaker.is_open,
            "failures": self.circuit_breaker.failures,
            "last_successful_fetch": self.last_successful_fetch.isoformat() if self.last_successful_fetch else None,
        }

    async def close(self):
        await self.client.aclose()
