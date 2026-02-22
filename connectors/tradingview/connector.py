"""
TradingView Connector

Receive pre-calculated indicators from frontend TradingView widget.
"""

from ..base_connector import BaseConnector, ConnectorStatus
from typing import Dict, Any, Callable, List
import json
import asyncio
import time
import uuid

FIAT_CODES = {
    "USD",
    "EUR",
    "GBP",
    "CHF",
    "JPY",
    "CAD",
    "AUD",
    "NZD",
    "MXN",
    "HKD",
}


def _normalize_symbol_token(symbol: str) -> str:
    value = (symbol or "").strip().upper().replace("_", "-").replace("/", "-")
    if ":" in value:
        value = value.split(":")[-1]
    return value


def _symbol_aliases(symbol: str) -> List[str]:
    raw = _normalize_symbol_token(symbol)
    if not raw:
        return []

    aliases: List[str] = [raw]
    if "-" in raw:
        base, quote = raw.split("-", 1)
        if base and quote:
            is_fiat_pair = base in FIAT_CODES and quote in FIAT_CODES
            if not is_fiat_pair:
                aliases.append(base)
            aliases.append(f"{base}{quote}")
            if quote in {"USD", "USDT"} and base not in FIAT_CODES:
                aliases.append(base)
    else:
        if raw.endswith("USDT") and len(raw) > 4:
            base = raw[:-4]
            aliases.extend([base, f"{base}-USDT", f"{base}-USD"])
        elif raw.endswith("USD") and len(raw) > 3:
            base = raw[:-3]
            if base not in FIAT_CODES:
                aliases.extend([base, f"{base}-USD", f"{base}-USDT"])
        elif len(raw) == 6 and raw[:3] in FIAT_CODES and raw[3:] in FIAT_CODES:
            aliases.append(f"{raw[:3]}-{raw[3:]}")

    # Keep order and uniqueness
    seen = set()
    out: List[str] = []
    for item in aliases:
        token = _normalize_symbol_token(item)
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _command_symbol_key(symbol: str) -> str:
    raw = _normalize_symbol_token(symbol)
    if not raw:
        return raw
    if "-" in raw:
        base, quote = raw.split("-", 1)
        if base in FIAT_CODES and quote in FIAT_CODES:
            return f"{base}{quote}"
        if quote in {"USD", "USDT"} and base not in FIAT_CODES:
            return base
        return raw
    if len(raw) == 6 and raw[:3] in FIAT_CODES and raw[3:] in FIAT_CODES:
        return raw
    if raw.endswith("USDT") and len(raw) > 4:
        base = raw[:-4]
        if base and base not in FIAT_CODES:
            return base
    if raw.endswith("USD") and len(raw) > 3:
        base = raw[:-3]
        if base and base not in FIAT_CODES:
            return base
    return raw


def _command_symbol_keys(symbol: str) -> List[str]:
    """
    Return all plausible command queue keys for a symbol.
    This prevents queue/poll mismatches after source or symbol format switches
    (e.g. USD-CHF vs USDCHF, BTC-USD vs BTCUSDT vs BTC).
    """
    raw = _normalize_symbol_token(symbol)
    candidates: List[str] = [raw]
    candidates.extend(_symbol_aliases(raw))

    if "-" in raw:
        base, quote = raw.split("-", 1)
        if base in FIAT_CODES and quote in FIAT_CODES:
            candidates.append(f"{base}{quote}")
    if len(raw) == 6 and raw[:3] in FIAT_CODES and raw[3:] in FIAT_CODES:
        candidates.append(f"{raw[:3]}-{raw[3:]}")

    out: List[str] = []
    seen = set()
    for candidate in candidates:
        key = _command_symbol_key(candidate)
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _normalize_timeframe_token(timeframe: str) -> str:
    raw = (timeframe or "").strip().upper().replace(" ", "")
    if not raw:
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
        "1M": "1m",
        "3M": "3m",
        "5M": "5m",
        "15M": "15m",
        "30M": "30m",
    }
    return mapping.get(raw, raw)


def _timeframe_aliases(timeframe: str) -> List[str]:
    canonical = _normalize_timeframe_token(timeframe)
    raw = str(timeframe or "").strip()
    if not canonical and not raw:
        return []

    aliases: List[str] = []
    if canonical:
        aliases.append(canonical)

        reverse = {
            "1m": ["1", "1M"],
            "3m": ["3", "3M"],
            "5m": ["5", "5M"],
            "15m": ["15", "15M"],
            "30m": ["30", "30M"],
            "45m": ["45", "45M"],
            "1H": ["60"],
            "2H": ["120"],
            "3H": ["180"],
            "4H": ["240"],
            "6H": ["360"],
            "8H": ["480"],
            "12H": ["720"],
            "1D": ["D"],
            "1W": ["W"],
        }
        aliases.extend(reverse.get(canonical, []))

    if raw:
        aliases.append(raw)

    # Keep order and uniqueness case-insensitively.
    seen = set()
    out: List[str] = []
    for item in aliases:
        token = str(item or "").strip()
        if not token:
            continue
        marker = token.lower()
        if marker in seen:
            continue
        seen.add(marker)
        out.append(token)
    return out


class TradingViewConnector(BaseConnector):
    """
    TradingView data receiver connector.
    
    This is a RECEIVE-ONLY connector. It doesn't fetch from TradingView API.
    Instead, it receives indicator data extracted by frontend from the widget.
    
    Data Flow:
    1. Frontend extracts indicators via chart.getAllStudies()
    2. Frontend POSTs to /api/tradingview/indicators
    3. This connector stores in Redis
    4. AI agent reads from Redis
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("tradingview", config)
        
        self.redis_client = config.get("redis_client")
        self.cache_ttl = config.get("cache_ttl", 60)  # 60 seconds default
        self.consumer_status_ttl = int(max(30, config.get("consumer_status_ttl", 120)))

        # In CI/dev, Redis may be unavailable. We still want the TradingView command loop
        # (queue -> poll -> report result) to work for UI + tool verification.
        #
        # This in-memory fallback is process-local and non-durable, but unblocks:
        # - Playwright E2E tests
        # - Local development without Redis
        self._memory_enabled = self.redis_client is None
        self._mem_lock = asyncio.Lock()
        self._mem_kv: Dict[str, tuple[str, float]] = {}          # key -> (json, expires_at_ms)
        self._mem_lists: Dict[str, tuple[List[str], float]] = {}  # key -> ([json...], expires_at_ms)
        
        # Treat in-memory mode as healthy (commands still work).
        self.status = ConnectorStatus.HEALTHY

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _expires_at_ms(self, ttl_sec: int) -> float:
        ttl = int(max(1, ttl_sec))
        return float(self._now_ms() + (ttl * 1000))

    async def _mem_cleanup_locked(self) -> None:
        now = float(self._now_ms())
        kv_dead = [k for k, (_, exp) in self._mem_kv.items() if exp and exp <= now]
        for k in kv_dead:
            self._mem_kv.pop(k, None)
        list_dead = [k for k, (_, exp) in self._mem_lists.items() if exp and exp <= now]
        for k in list_dead:
            self._mem_lists.pop(k, None)

    async def _mem_get(self, key: str) -> str | None:
        async with self._mem_lock:
            await self._mem_cleanup_locked()
            item = self._mem_kv.get(key)
            if not item:
                return None
            value, exp = item
            if exp and exp <= float(self._now_ms()):
                self._mem_kv.pop(key, None)
                return None
            return value

    async def _mem_setex(self, key: str, ttl_sec: int, value: str) -> None:
        async with self._mem_lock:
            await self._mem_cleanup_locked()
            self._mem_kv[key] = (value, self._expires_at_ms(ttl_sec))

    async def _mem_rpush(self, key: str, value: str) -> None:
        async with self._mem_lock:
            await self._mem_cleanup_locked()
            existing, exp = self._mem_lists.get(key, ([], 0.0))
            existing = list(existing)
            existing.append(value)
            # Preserve previous TTL if present, else no expiry until explicit expire().
            self._mem_lists[key] = (existing, exp)

    async def _mem_expire(self, key: str, ttl_sec: int) -> None:
        async with self._mem_lock:
            await self._mem_cleanup_locked()
            if key in self._mem_kv:
                value, _ = self._mem_kv[key]
                self._mem_kv[key] = (value, self._expires_at_ms(ttl_sec))
                return
            if key in self._mem_lists:
                items, _ = self._mem_lists[key]
                self._mem_lists[key] = (list(items), self._expires_at_ms(ttl_sec))

    async def _mem_lrange_and_delete(self, key: str) -> List[str]:
        async with self._mem_lock:
            await self._mem_cleanup_locked()
            items, _ = self._mem_lists.get(key, ([], 0.0))
            self._mem_lists.pop(key, None)
            return list(items)

    def _consumer_poll_key(self) -> str:
        return "commands:tradingview:consumer:last_poll"

    async def _mark_consumer_poll(self, symbol: str) -> None:
        payload = json.dumps(
            {
                "symbol": _normalize_symbol_token(symbol),
                "polled_at_ms": self._now_ms(),
            }
        )
        key = self._consumer_poll_key()
        if self.redis_client:
            await self.redis_client.setex(key, self.consumer_status_ttl, payload)
        else:
            await self._mem_setex(key, self.consumer_status_ttl, payload)

    async def get_consumer_status(self, symbol: str = "", stale_after_sec: float = 6.0) -> Dict[str, Any]:
        key = self._consumer_poll_key()
        raw = await self.redis_client.get(key) if self.redis_client else await self._mem_get(key)
        now_ms = self._now_ms()
        stale_after_ms = int(max(500, float(stale_after_sec) * 1000))

        parsed: Dict[str, Any] = {}
        if raw:
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {}

        last_poll_ms = int(parsed.get("polled_at_ms") or 0)
        last_symbol = _normalize_symbol_token(str(parsed.get("symbol") or ""))
        age_ms = now_ms - last_poll_ms if last_poll_ms > 0 else None
        consumer_online = bool(age_ms is not None and age_ms <= stale_after_ms)
        return {
            "consumer_online": consumer_online,
            "stale_after_sec": float(stale_after_sec),
            "last_poll_ms": last_poll_ms or None,
            "last_poll_age_ms": age_ms,
            "last_polled_symbol": last_symbol or None,
            "requested_symbol": _normalize_symbol_token(symbol) or None,
        }
    
    async def fetch(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """
        Fetch cached indicators from Redis.
        
        Args:
            symbol: Trading symbol
            **kwargs: timeframe (required)
        
        Returns:
            Cached indicator data or error if not found
        """
        timeframe = kwargs.get("timeframe")
        if not timeframe:
            raise ValueError("timeframe is required")

        timeframe_candidates = _timeframe_aliases(str(timeframe))
        if not timeframe_candidates:
            timeframe_candidates = [str(timeframe)]

        try:
            for alias in _symbol_aliases(symbol):
                for tf in timeframe_candidates:
                    cache_key = f"indicators:{alias}:{tf}"
                    cached = await self.redis_client.get(cache_key) if self.redis_client else await self._mem_get(cache_key)
                    if not cached:
                        continue
                    data = json.loads(cached)
                    return self.normalize(data)
            raise ValueError(
                f"No indicators cached for {symbol} {timeframe}. "
                "Frontend needs to send data first."
            )
        
        except Exception as e:
            self.status = ConnectorStatus.ERROR
            raise
    
    async def subscribe(
        self,
        symbol: str,
        callback: Callable,
        **kwargs
    ) -> None:
        """
        Subscribe to indicator updates.
        
        Note: This monitors Redis for new data, not a WebSocket.
        """
        raise NotImplementedError(
            "TradingView subscription not implemented. Use polling."
        )
    
    async def store_indicators(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Store indicator data received from frontend.
        
        Args:
            data: {
                "symbol": str,
                "timeframe": str,
                "indicators": {...},
                "chart_screenshot": str (optional),
                "timestamp": int
            }
        
        Returns:
            {"status": "stored", "symbol": str, "count": int}
        """
        symbol = data.get("symbol")
        timeframe = data.get("timeframe")
        
        if not symbol or not timeframe:
            raise ValueError("symbol and timeframe are required")

        timeframe_candidates = _timeframe_aliases(str(timeframe))
        if not timeframe_candidates:
            timeframe_candidates = [str(timeframe)]

        payload = json.dumps(data)
        for alias in _symbol_aliases(symbol):
            for tf in timeframe_candidates:
                cache_key = f"indicators:{alias}:{tf}"
                if self.redis_client:
                    await self.redis_client.setex(cache_key, self.cache_ttl, payload)
                else:
                    await self._mem_setex(cache_key, self.cache_ttl, payload)
        
        return {
            "status": "stored",
            "symbol": _normalize_symbol_token(symbol),
            "timeframe": timeframe,
            "indicator_count": len(data.get("indicators", {})),
            "has_screenshot": "chart_screenshot" in data
        }
    
    async def queue_command(self, symbol: str, command: Dict[str, Any]) -> Dict[str, Any]:
        """
        Queue a command for the frontend to execute.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSD")
            command: Command dict (e.g., {"action": "set_timeframe", "params": "1h"})
        """
        if not symbol or not command:
            return {}

        symbol_key = _command_symbol_key(symbol)
        key = f"commands:tradingview:{symbol_key}"
        command_id = uuid.uuid4().hex
        envelope = {
            "command_id": command_id,
            "symbol": symbol,
            "symbol_key": symbol_key,
            "action": command.get("action"),
            "params": command.get("params", {}),
            "queued_at": int(time.time() * 1000),
        }

        # Expire commands after 60s if not picked up
        payload = json.dumps(envelope)
        if self.redis_client:
            await self.redis_client.rpush(key, payload)
            await self.redis_client.expire(key, 60)
        else:
            await self._mem_rpush(key, payload)
            await self._mem_expire(key, 60)
        return envelope
        
    async def get_pending_commands(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Get and clear pending commands for a symbol.
        """
        await self._mark_consumer_poll(symbol)
        keys = [f"commands:tradingview:{k}" for k in _command_symbol_keys(symbol)]
        if not keys:
            return []

        commands: List[Dict[str, Any]] = []
        seen_ids = set()

        if self.redis_client:
            # Read+clear all alias queues in one pipeline roundtrip.
            async with self.redis_client.pipeline() as pipe:
                for key in keys:
                    pipe.lrange(key, 0, -1)
                    pipe.delete(key)
                result = await pipe.execute()

            # result layout: [lrange0, del0, lrange1, del1, ...]
            for idx in range(0, len(result), 2):
                raw_commands = result[idx] or []
                for cmd_str in raw_commands:
                    try:
                        parsed = json.loads(cmd_str)
                    except Exception:
                        continue
                    cmd_id = str(parsed.get("command_id") or "").strip()
                    if cmd_id and cmd_id in seen_ids:
                        continue
                    if cmd_id:
                        seen_ids.add(cmd_id)
                    commands.append(parsed)
        else:
            for key in keys:
                raw_commands = await self._mem_lrange_and_delete(key)
                for cmd_str in raw_commands:
                    try:
                        parsed = json.loads(cmd_str)
                    except Exception:
                        continue
                    cmd_id = str(parsed.get("command_id") or "").strip()
                    if cmd_id and cmd_id in seen_ids:
                        continue
                    if cmd_id:
                        seen_ids.add(cmd_id)
                    commands.append(parsed)

        return commands

    def _result_key(self, command_id: str) -> str:
        return f"commands:tradingview:result:{command_id}"

    async def store_command_result(
        self,
        command_id: str,
        status: str,
        result: Dict[str, Any] | None = None,
        error: str | None = None,
        ttl_sec: int = 120,
    ) -> Dict[str, Any]:
        payload = {
            "command_id": command_id,
            "status": (status or "").strip().lower() or "unknown",
            "result": result or {},
            "error": error,
            "completed_at": int(time.time() * 1000),
        }
        key = self._result_key(command_id)
        raw = json.dumps(payload)
        ttl = int(max(30, ttl_sec))
        if self.redis_client:
            await self.redis_client.setex(key, ttl, raw)
        else:
            await self._mem_setex(key, ttl, raw)
        return payload

    async def wait_for_command_result(
        self,
        command_id: str,
        timeout_sec: float = 6.0,
        poll_interval_sec: float = 0.2,
    ) -> Dict[str, Any]:
        deadline = time.time() + max(0.2, float(timeout_sec))
        key = self._result_key(command_id)
        while time.time() < deadline:
            raw = await self.redis_client.get(key) if self.redis_client else await self._mem_get(key)
            if raw:
                try:
                    return json.loads(raw)
                except Exception:
                    return {
                        "command_id": command_id,
                        "status": "error",
                        "error": "Malformed command result payload",
                        "result": {},
                    }
            await asyncio.sleep(max(0.05, float(poll_interval_sec)))

        return {
            "command_id": command_id,
            "status": "timeout",
            "error": f"Timed out waiting for command result after {timeout_sec:.1f}s",
            "result": {},
        }

    def normalize(self, raw_data: Any) -> Dict[str, Any]:
        """
        Normalize TradingView data.
        
        Args:
            raw_data: Indicator data from frontend
        
        Returns:
            {
                "source": "tradingview",
                "symbol": symbol,
                "data_type": "indicators",
                "timestamp": int,
                "data": {
                    "timeframe": str,
                    "indicators": {...},
                    "screenshot": str (optional)
                }
            }
        """
        return {
            "source": "tradingview",
            "symbol": raw_data.get("symbol", "UNKNOWN"),
            "data_type": "indicators",
            "timestamp": raw_data.get("timestamp", 0),
            "data": {
                "timeframe": raw_data.get("timeframe"),
                "indicators": raw_data.get("indicators", {}),
                "screenshot": raw_data.get("chart_screenshot"),
                # Optional: chart.getAllStudies() names so tools can verify add/remove applied.
                "active_indicators": raw_data.get("active_indicators") or raw_data.get("activeIndicators") or [],
                # Optional: keys from drawing handler's ID map so tools can verify draw/update/clear.
                "drawing_tags": raw_data.get("drawing_tags") or raw_data.get("drawingTags") or [],
                # Optional: last trade setup parameters (entry/sl/tp/validation/invalidation/etc).
                "trade_setup": raw_data.get("trade_setup") or raw_data.get("tradeSetup") or {},
            }
        }
