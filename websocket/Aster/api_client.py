"""
Aster Exchange API client
Based on: https://github.com/asterdex/aster-broker-pro-sdk
API is Binance-compatible (fapi = futures API):
  https://www.asterdex.com/bapi/*  →  REST/account
  https://www.asterdex.com/fapi/*  →  Futures REST (public)
  wss://fstream.asterdex.com/compress/stream  →  WS

Public endpoints (no auth):
  GET /fapi/v1/exchangeInfo   → all perpetual pairs + metadata
  GET /fapi/v1/ticker/price   → latest mark prices
  GET /fapi/v1/ticker/24hr    → 24h OHLCV + price change
  GET /fapi/v1/depth          → orderbook
  GET /fapi/v1/klines         → candlesticks
"""
import httpx
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

ASTER_FAPI_BASE = "https://www.asterdex.com/fapi/v1"
ASTER_BAPI_BASE = "https://www.asterdex.com/bapi"


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
            logger.warning(f"[Aster] Circuit breaker OPEN after {self.failures} failures")

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


class AsterAPIClient:
    """
    HTTP client for Aster Exchange (Binance fapi-compatible).
    Chain: BNB Chain
    Symbols: BTCUSDT, ETHUSDT, ... (Binance perpetual format)
    """

    def __init__(self, fapi_base: str = ASTER_FAPI_BASE):
        self.fapi_base = fapi_base.rstrip("/")
        self.client = httpx.AsyncClient(timeout=10.0, verify=False)
        self.circuit_breaker = CircuitBreaker()
        self.last_successful_fetch: Optional[datetime] = None

    async def get_exchange_info(self) -> Optional[Dict[str, Any]]:
        """
        GET /fapi/v1/exchangeInfo
        Returns all trading pairs with margin parameters.
        Binance-compatible format: {"symbols": [{"symbol": "BTCUSDT", "baseAsset": "BTC", ...}]}
        """
        try:
            resp = await self.client.get(f"{self.fapi_base}/exchangeInfo")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"[Aster] /exchangeInfo failed: {e}")
            return None

    async def get_ticker_prices(self) -> Optional[List[Dict]]:
        """GET /fapi/v1/ticker/price — latest mark price per symbol."""
        try:
            resp = await self.client.get(f"{self.fapi_base}/ticker/price")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else [data]
        except Exception as e:
            logger.debug(f"[Aster] /ticker/price failed: {e}")
            return None

    async def get_24h_tickers(self) -> Optional[List[Dict]]:
        """GET /fapi/v1/ticker/24hr — OHLCV + price change."""
        try:
            resp = await self.client.get(f"{self.fapi_base}/ticker/24hr")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else [data]
        except Exception as e:
            logger.debug(f"[Aster] /ticker/24hr failed: {e}")
            return None

    async def get_latest_prices(self) -> Optional[List[Dict[str, Any]]]:
        """
        Main polling method. Fetches exchangeInfo + 24hr tickers.
        Normalizes to unified {symbol, from, to, price, ...} format.
        """
        if not self.circuit_breaker.can_attempt():
            return None

        # Try to get all symbols from exchangeInfo
        exchange_info = await self.get_exchange_info()
        symbols_meta: Dict[str, Dict] = {}
        if exchange_info:
            for s in exchange_info.get("symbols", []):
                sym = s.get("symbol", "")
                if sym:
                    symbols_meta[sym] = s

        # Get live prices from 24hr ticker
        tickers = await self.get_24h_tickers()
        if tickers is None:
            # Fallback to simple price endpoint
            tickers = await self.get_ticker_prices()
        if tickers is None:
            self.circuit_breaker.record_failure()
            return None

        results = []
        for ticker in tickers:
            sym = ticker.get("symbol", "")
            if not sym:
                continue

            meta = symbols_meta.get(sym, {})
            # Binance format: BTCUSDT → base=BTC, quote=USDC/USDT
            base = meta.get("baseAsset") or sym.replace("USDT", "").replace("USDC", "").replace("BUSD", "")
            quote = meta.get("quoteAsset", "USDC")
            base = base.upper()

            # Max leverage from requiredMarginPercent (e.g. 5% → 20x)
            req_margin = float(meta.get("requiredMarginPercent") or 10)
            max_lev = int(100 / req_margin) if req_margin > 0 else 20

            results.append({
                "symbol": sym,
                "tradingSymbol": sym,
                "from": base,
                "to": quote,
                "price": float(ticker.get("lastPrice") or ticker.get("price") or ticker.get("markPrice") or 0),
                "high_24h": float(ticker.get("highPrice") or 0),
                "low_24h": float(ticker.get("lowPrice") or 0),
                "volume_24h": float(ticker.get("volume") or ticker.get("quoteVolume") or 0),
                "change_24h": float(ticker.get("priceChange") or 0),
                "change_percent_24h": float(ticker.get("priceChangePercent") or 0),
                "funding_rate": float(ticker.get("lastFundingRate") or 0),
                "open_interest": float(ticker.get("openInterest") or 0),
                "max_leverage": max_lev,
                "source": "aster",
            })

        self.circuit_breaker.record_success()
        self.last_successful_fetch = datetime.now()
        return results

    async def get_klines(self, symbol: str, interval: str = "1m", limit: int = 100,
                         start_time: Optional[int] = None, end_time: Optional[int] = None) -> Optional[List]:
        """GET /fapi/v1/klines — Binance-compatible OHLCV."""
        try:
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
            resp = await self.client.get(f"{self.fapi_base}/klines", params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"[Aster] /klines {symbol} failed: {e}")
            return None

    async def get_depth(self, symbol: str, limit: int = 20) -> Optional[Dict]:
        """GET /fapi/v1/depth — Binance-compatible orderbook."""
        try:
            resp = await self.client.get(f"{self.fapi_base}/depth", params={"symbol": symbol, "limit": limit})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"[Aster] /depth {symbol} failed: {e}")
            return None

    async def get_recent_trades(self, symbol: str, limit: int = 20) -> Optional[List]:
        """GET /fapi/v1/trades — Binance-compatible recent trades."""
        try:
            resp = await self.client.get(f"{self.fapi_base}/trades", params={"symbol": symbol, "limit": limit})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"[Aster] /trades {symbol} failed: {e}")
            return None

    async def get_markets(self) -> List[Dict[str, Any]]:
        return await self.get_latest_prices() or []

    def get_status(self) -> dict:
        return {
            "exchange": "aster",
            "chain": "bnb",
            "fapi_base": self.fapi_base,
            "circuit_breaker_open": self.circuit_breaker.is_open,
            "failures": self.circuit_breaker.failures,
            "last_successful_fetch": self.last_successful_fetch.isoformat() if self.last_successful_fetch else None,
        }

    async def close(self):
        await self.client.aclose()
