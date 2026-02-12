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
        
        if self.redis_client:
            self.status = ConnectorStatus.HEALTHY
        else:
            self.status = ConnectorStatus.OFFLINE
    
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
        
        try:
            for alias in _symbol_aliases(symbol):
                cache_key = f"indicators:{alias}:{timeframe}"
                cached = await self.redis_client.get(cache_key)
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

        for alias in _symbol_aliases(symbol):
            cache_key = f"indicators:{alias}:{timeframe}"
            await self.redis_client.setex(
                cache_key,
                self.cache_ttl,
                json.dumps(data)
            )
        
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
        await self.redis_client.rpush(key, json.dumps(envelope))
        await self.redis_client.expire(key, 60)
        return envelope
        
    async def get_pending_commands(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Get and clear pending commands for a symbol.
        """
        keys = [f"commands:tradingview:{k}" for k in _command_symbol_keys(symbol)]
        if not keys:
            return []

        # Read+clear all alias queues in one pipeline roundtrip.
        async with self.redis_client.pipeline() as pipe:
            for key in keys:
                pipe.lrange(key, 0, -1)
                pipe.delete(key)
            result = await pipe.execute()

        commands: List[Dict[str, Any]] = []
        seen_ids = set()
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
        await self.redis_client.setex(self._result_key(command_id), int(max(30, ttl_sec)), json.dumps(payload))
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
            raw = await self.redis_client.get(key)
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
                "screenshot": raw_data.get("chart_screenshot")
            }
        }
