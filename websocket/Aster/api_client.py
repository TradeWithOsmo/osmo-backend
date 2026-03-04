"""
Aster Exchange API client
"""
import httpx
import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

ASTER_FAPI_BASE = "https://www.asterdex.com/fapi/v1"
ASTER_BAPI_BASE = "https://www.asterdex.com/bapi"

_SEMAPHORE_LIMIT = 10


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
    def __init__(self, fapi_base: str = ASTER_FAPI_BASE):
        self.fapi_base = fapi_base.rstrip("/")
        limits = httpx.Limits(
            max_connections=30,
            max_keepalive_connections=20,
            keepalive_expiry=30,
        )
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=3.0),
            limits=limits,
            verify=False,
        )
        self._sem = asyncio.Semaphore(_SEMAPHORE_LIMIT)
        self.circuit_breaker = CircuitBreaker()
        self.last_successful_fetch: Optional[datetime] = None

    async def _get(self, path: str, params: dict = None) -> Any:
        async with self._sem:
            resp = await self.client.get(f"{self.fapi_base}{path}", params=params or {})
            resp.raise_for_status()
            return resp.json()

    async def get_exchange_info(self) -> Optional[Dict[str, Any]]:
        try:
            data = await self._get("/exchangeInfo")
            if not data:
                return None
            all_symbols = data.get("symbols", [])
            active = [
                s for s in all_symbols
                if s.get("status", "").upper() in {"TRADING", "SETTLING"}
            ]
            logger.info(f"[Aster] exchangeInfo: {len(all_symbols)} total, {len(active)} active")
            data["symbols"] = active
            return data
        except Exception as e:
            logger.debug(f"[Aster] /exchangeInfo failed: {e}")
            return None

    async def get_ticker_prices(self) -> Optional[List[Dict]]:
        try:
            data = await self._get("/ticker/price")
            return data if isinstance(data, list) else [data]
        except Exception as e:
            logger.debug(f"[Aster] /ticker/price failed: {e}")
            return None

    async def get_24h_tickers(self) -> Optional[List[Dict]]:
        try:
            data = await self._get("/ticker/24hr")
            return data if isinstance(data, list) else [data]
        except Exception as e:
            logger.debug(f"[Aster] /ticker/24hr failed: {e}")
            return None

    async def get_latest_prices(self) -> Optional[List[Dict[str, Any]]]:
        if not self.circuit_breaker.can_attempt():
            return None

        exchange_info, tickers = await asyncio.gather(
            self.get_exchange_info(),
            self.get_24h_tickers(),
            return_exceptions=True,
        )

        if isinstance(exchange_info, Exception):
            exchange_info = None
        if isinstance(tickers, Exception):
            tickers = None

        symbols_meta: Dict[str, Dict] = {}
        if exchange_info:
            for s in exchange_info.get("symbols", []):
                sym = s.get("symbol", "")
                if sym:
                    symbols_meta[sym] = s

        if tickers is None:
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
            base = meta.get("baseAsset") or sym.replace("USDT", "").replace("USDC", "").replace("BUSD", "")
            quote = meta.get("quoteAsset", "USDC")
            base = base.upper()
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
        try:
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
            return await self._get("/klines", params)
        except Exception as e:
            logger.debug(f"[Aster] /klines {symbol} failed: {e}")
            return None

    async def get_depth(self, symbol: str, limit: int = 20) -> Optional[Dict]:
        try:
            return await self._get("/depth", {"symbol": symbol, "limit": limit})
        except Exception as e:
            logger.debug(f"[Aster] /depth {symbol} failed: {e}")
            return None

    async def get_recent_trades(self, symbol: str, limit: int = 20) -> Optional[List]:
        try:
            return await self._get("/trades", {"symbol": symbol, "limit": limit})
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