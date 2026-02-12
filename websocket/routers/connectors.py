from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import logging
import asyncio
import time
import sys
import os

# Add connectors path
sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
from connectors.hyperliquid.connector import HyperliquidConnector
from Ostium.api_client import OstiumAPIClient
from Ostium.normalizer import normalize_ostium_prices, get_ostium_category, get_ostium_max_leverage

router = APIRouter()
logger = logging.getLogger(__name__)

# Initialize connectors
hl_connector = HyperliquidConnector(config={})
ostium_client = OstiumAPIClient()

# Global cache for performance
HL_MARKETS_CACHE = []
OST_MARKETS_CACHE = []
LAST_HL_UPDATE = 0
LAST_OST_UPDATE = 0


def _detect_light_patterns(candles: List[Dict[str, Any]]) -> List[str]:
    if not candles or len(candles) < 2:
        return []
    try:
        c0 = candles[-1]
        c1 = candles[-2]
        c0_op = float(c0.get("open", 0))
        c0_cl = float(c0.get("close", 0))
        c0_hi = float(c0.get("high", 0))
        c0_lo = float(c0.get("low", 0))
        c1_op = float(c1.get("open", 0))
        c1_cl = float(c1.get("close", 0))

        out: List[str] = []
        body = abs(c0_cl - c0_op)
        rng = max(0.0, c0_hi - c0_lo)
        if rng > 0 and (body / rng) < 0.12:
            out.append("Doji")

        # Engulfing
        if (c1_cl < c1_op) and (c0_cl > c0_op) and (c0_cl >= c1_op) and (c0_op <= c1_cl):
            out.append("Bullish Engulfing")
        if (c1_cl > c1_op) and (c0_cl < c0_op) and (c0_cl <= c1_op) and (c0_op >= c1_cl):
            out.append("Bearish Engulfing")

        lower_wick = min(c0_op, c0_cl) - c0_lo
        upper_wick = c0_hi - max(c0_op, c0_cl)
        if rng > 0 and (body / rng) < 0.35 and (lower_wick / rng) > 0.55 and (upper_wick / rng) < 0.2:
            out.append("Hammer (Bullish)")
        if rng > 0 and (body / rng) < 0.35 and (upper_wick / rng) > 0.55 and (lower_wick / rng) < 0.2:
            out.append("Shooting Star (Bearish)")

        # De-duplicate preserve order
        seen = set()
        dedup: List[str] = []
        for item in out:
            if item not in seen:
                seen.add(item)
                dedup.append(item)
        return dedup
    except Exception:
        return []


class CommandRequest(BaseModel):
    symbol: str
    action: str
    params: Dict[str, Any] = {}


class CommandResultRequest(BaseModel):
    command_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class IndicatorData(BaseModel):
    symbol: str
    timeframe: str
    indicators: Dict[str, Any]
    chart_screenshot: Optional[str] = None
    timestamp: Optional[int] = None


def _model_to_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _safe_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_json(v) for v in value]
    return str(value)

async def update_hl_cache():
    global HL_MARKETS_CACHE, LAST_HL_UPDATE
    try:
        from main import hl_price_history
        markets = await hl_connector.fetch_all_markets()
        if markets:
            for market in markets:
                symbol = market["symbol"]
                price = market["price"]
                hl_price_history.update_price(symbol, price)
                stats_24h = hl_price_history.get_stats(symbol)
                if stats_24h:
                    market["high_24h"] = stats_24h.get("high_24h", 0)
                    market["low_24h"] = stats_24h.get("low_24h", 0)
            HL_MARKETS_CACHE = markets
            LAST_HL_UPDATE = time.time()
    except Exception as e:
        logger.error(f"Error updating HL cache: {e}")

async def update_ost_cache():
    global OST_MARKETS_CACHE, LAST_OST_UPDATE
    try:
        from main import ostium_price_history
        raw_prices = await ostium_client.get_latest_prices()
        if raw_prices:
            ostium_price_history.update_from_ostium_response(raw_prices)
            normalized_dict = normalize_ostium_prices(raw_prices)
            markets_list = []
            for symbol, data in normalized_dict.items():
                stats_24h = ostium_price_history.get_stats(symbol)
                markets_list.append({
                    "symbol": data["symbol"],
                    "price": float(data["price"]),
                    "change_24h": stats_24h.get("change_24h", 0) if stats_24h else 0,
                    "change_percent_24h": stats_24h.get("change_percent_24h", 0) if stats_24h else 0,
                    "volume_24h": 0,
                    "high_24h": stats_24h.get("high_24h", 0) if stats_24h else 0,
                    "low_24h": stats_24h.get("low_24h", 0) if stats_24h else 0,
                    "category": data.get("category", "Forex")
                })
            OST_MARKETS_CACHE = markets_list
            LAST_OST_UPDATE = time.time()
    except Exception as e:
        logger.error(f"Error updating Ostium cache: {e}")

@router.on_event("startup")
async def start_cache_poller():
    async def poll():
        while True:
            await asyncio.gather(update_hl_cache(), update_ost_cache())
            await asyncio.sleep(0.5) # Refresh every 0.5s for <1s freshness
    asyncio.create_task(poll())

@router.get("/hyperliquid/prices")
async def get_hyperliquid_prices():
    if not HL_MARKETS_CACHE:
        await update_hl_cache()
    return HL_MARKETS_CACHE

@router.get("/ostium/prices")
async def get_ostium_prices():
    if not OST_MARKETS_CACHE:
        await update_ost_cache()
    return OST_MARKETS_CACHE


def _symbol_candidates(symbol: str) -> List[str]:
    raw = (symbol or "").strip().upper().replace("/", "-").replace("_", "-")
    if not raw:
        return []
    candidates = [raw]

    base = raw
    if raw.endswith("USDT"):
        base = raw[:-4]
    elif raw.endswith("USD"):
        base = raw[:-3]
    elif "-" in raw:
        base = raw.split("-", 1)[0]

    if base:
        candidates.extend([f"{base}-USD", f"{base}USDT", base])

    seen = set()
    out: List[str] = []
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _find_market(markets: List[Dict[str, Any]], symbol: str) -> Optional[Dict[str, Any]]:
    candidates = _symbol_candidates(symbol)
    for c in candidates:
        for row in markets:
            rs = str(row.get("symbol", "")).upper().replace("/", "-").replace("_", "-")
            if rs == c:
                return row
    return None


def _normalize_hl_symbol(symbol: str) -> str:
    raw = (symbol or "").strip().upper().replace("/", "-").replace("_", "-")
    if raw.endswith("-USD"):
        return raw[:-4]
    if raw.endswith("USDT"):
        return raw[:-4]
    if raw.endswith("USD"):
        return raw[:-3]
    if "-" in raw:
        return raw.split("-", 1)[0]
    return raw


def _manager():
    from connectors.init_connectors import connector_registry
    return connector_registry.get_manager()


def _require_connector(connector_id: str):
    manager = _manager()
    connector = manager.get_connector(connector_id)
    if not connector:
        raise HTTPException(status_code=503, detail=f"Connector '{connector_id}' not active")
    return connector


@router.get("/price/{symbol}")
async def get_price_legacy(
    symbol: str,
    asset_type: str = Query("crypto", pattern="^(crypto|rwa|hyperliquid|ostium)$"),
):
    """
    Backward-compatible single-price endpoint.
    Kept for legacy callers that still use /api/connectors/price/{symbol}.
    """
    normalized = asset_type.lower()
    if normalized in {"crypto", "hyperliquid"}:
        if not HL_MARKETS_CACHE:
            await update_hl_cache()
        markets = HL_MARKETS_CACHE
        source = "hyperliquid"
    else:
        if not OST_MARKETS_CACHE:
            await update_ost_cache()
        markets = OST_MARKETS_CACHE
        source = "ostium"

    row = _find_market(markets, symbol)
    if not row:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found for asset_type='{asset_type}'")

    return {
        "symbol": row.get("symbol", symbol),
        "asset_type": "crypto" if source == "hyperliquid" else "rwa",
        "source": source,
        "data": row,
    }


@router.get("/status")
async def get_all_connector_statuses():
    """
    Connector health snapshot for debugging tools/runtime availability.
    """
    try:
        manager = _manager()
        connector_ids = sorted([str(k) for k in getattr(manager, "connectors", {}).keys()])
        return {
            "count": len(connector_ids),
            "connectors": connector_ids,
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/tradingview/commands")
async def send_tradingview_command(
    cmd: CommandRequest,
    wait_for_completion: bool = Query(False),
    timeout_sec: float = Query(6.0, ge=0.5, le=60.0),
    poll_interval_sec: float = Query(0.2, ge=0.05, le=2.0),
):
    """
    Queue command for TradingView frontend executor.
    """
    try:
        tv = _require_connector("tradingview")
        queued = await tv.queue_command(cmd.symbol, {"action": cmd.action, "params": cmd.params or {}})
        if not queued:
            raise HTTPException(status_code=400, detail="Invalid tradingview command payload")

        if not wait_for_completion:
            return {"status": "queued", "command": queued}

        result = await tv.wait_for_command_result(
            command_id=queued.get("command_id"),
            timeout_sec=timeout_sec,
            poll_interval_sec=poll_interval_sec,
        )
        command_status = str(result.get("status") or "").strip().lower()
        if command_status in {"success", "ok", "done", "completed"}:
            return {"status": "completed", "command": queued, "result": result}
        if command_status == "timeout":
            raise HTTPException(
                status_code=504,
                detail={
                    "message": "TradingView command timed out waiting for frontend execution",
                    "command": queued,
                    "result": result,
                },
            )
        raise HTTPException(
            status_code=500,
            detail={
                "message": "TradingView command execution failed",
                "command": queued,
                "result": result,
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/tradingview/commands/{symbol}")
async def get_tradingview_commands(symbol: str):
    """
    Frontend polls this endpoint to execute pending commands.
    """
    try:
        tv = _require_connector("tradingview")
        return await tv.get_pending_commands(symbol)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/tradingview/commands/result")
async def report_tradingview_command_result(payload: CommandResultRequest):
    """
    Receive command execution result from TradingView frontend.
    """
    try:
        tv = _require_connector("tradingview")
        stored = await tv.store_command_result(
            command_id=payload.command_id,
            status=payload.status,
            result=payload.result,
            error=payload.error,
        )
        return {"status": "acknowledged", "result": stored}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/tradingview/indicators")
async def receive_tradingview_indicators(data: IndicatorData):
    """
    Receive and cache indicators from frontend TradingView widget.
    """
    try:
        tv = _require_connector("tradingview")
        payload = _model_to_dict(data)
        return await tv.store_indicators(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/tradingview/indicators")
async def get_tradingview_indicators(symbol: str, timeframe: str):
    """
    Fetch latest cached indicators for symbol/timeframe.
    """
    try:
        tv = _require_connector("tradingview")
        return await tv.fetch(symbol, timeframe=timeframe)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/web_search/search")
async def search_web(query: str, source: str = "news", mode: str = "quality"):
    """
    Generic web search endpoint used by agent tools.
    """
    try:
        connector = _require_connector("web_search")
        return await connector.fetch("UNKNOWN", query=query, source=source, mode=mode)
    except HTTPException:
        raise
    except Exception as exc:
        return {
            "source": "web_search",
            "symbol": None,
            "data_type": f"{source}_search",
            "timestamp": None,
            "data": {
                "error": f"Web search route error: {exc}",
                "query": query,
                "source": source,
                "mode": mode,
            },
        }


@router.get("/dune/whale_trades/{symbol}")
async def get_whale_trades(symbol: str, min_size_usd: int = 100000, hours: int = 24):
    """
    Whale trade feed used by analytics tools.
    """
    try:
        connector = _require_connector("dune")
        return await connector.fetch(_normalize_hl_symbol(symbol), min_size_usd=min_size_usd, hours=hours)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/orderbook/{symbol}")
async def get_orderbook(symbol: str):
    """
    L2 orderbook from Hyperliquid.
    """
    try:
        connector = _require_connector("hyperliquid")
        return await connector.fetch(_normalize_hl_symbol(symbol), data_type="orderbook")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/funding/{symbol}")
async def get_funding_rate(symbol: str):
    """
    Funding rate context for perpetual pairs.
    """
    try:
        connector = _require_connector("hyperliquid")
        return await connector.fetch(_normalize_hl_symbol(symbol), data_type="funding")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/analysis/technical/{symbol}")
async def get_technical_analysis(
    symbol: str,
    timeframe: str = "1D",
    asset_type: str = Query("crypto", pattern="^(crypto|rwa|hyperliquid|ostium)$"),
):
    """
    Lightweight technical payload used by data analysis tools.
    Keeps tool calls stable even when full TA engine is unavailable.
    """
    try:
        normalized_asset = asset_type.lower()
        normalized_symbol = _normalize_hl_symbol(symbol)
        view_symbol = symbol.upper().replace("/", "-").replace("_", "-")
        if "-" not in view_symbol:
            view_symbol = f"{normalized_symbol}-USD"

        if normalized_asset in {"crypto", "hyperliquid"}:
            connector = _require_connector("hyperliquid")
            source = "hyperliquid"
            price_payload = await connector.fetch(normalized_symbol, data_type="price")
        else:
            connector = _require_connector("ostium")
            source = "ostium"
            price_payload = await connector.fetch(normalized_symbol, data_type="price")

        price_data = (price_payload or {}).get("data", {}) if isinstance(price_payload, dict) else {}
        indicators: Dict[str, Any] = {}
        chart_screenshot: Optional[str] = None
        patterns: List[str] = []

        # Best-effort pull from frontend-cached TradingView indicators.
        try:
            tv = _require_connector("tradingview")
            tv_payload = await tv.fetch(view_symbol, timeframe=timeframe)
            tv_data = tv_payload.get("data", {}) if isinstance(tv_payload, dict) else {}
            indicators = tv_data.get("indicators", {}) if isinstance(tv_data, dict) else {}
            chart_screenshot = tv_data.get("screenshot") if isinstance(tv_data, dict) else None
            raw_patterns = tv_data.get("patterns", []) if isinstance(tv_data, dict) else []
            if isinstance(raw_patterns, list):
                patterns = [str(item).strip() for item in raw_patterns if str(item).strip()]
        except Exception:
            indicators = {}
            chart_screenshot = None

        # Fallback: detect candlestick patterns from recent candles when frontend
        # TradingView payload does not provide patterns.
        if not patterns:
            try:
                from analysis.engine import TechnicalAnalysisEngine

                engine = TechnicalAnalysisEngine()
                candles_payload = await connector.fetch(
                    normalized_symbol,
                    data_type="candles",
                    timeframe=timeframe,
                    limit=120,
                )
                candles = (candles_payload or {}).get("data", []) if isinstance(candles_payload, dict) else []
                if isinstance(candles, list) and candles:
                    analysis_result = engine.analyze_ticker(
                        symbol=normalized_symbol,
                        timeframe=timeframe,
                        ohlcv_data=candles,
                    )
                    fallback_patterns = analysis_result.get("patterns", []) if isinstance(analysis_result, dict) else []
                    if isinstance(fallback_patterns, list):
                        patterns = [str(item).strip() for item in fallback_patterns if str(item).strip()]
                    if not patterns:
                        patterns = _detect_light_patterns(candles)
            except Exception:
                patterns = patterns or []

        return {
            "symbol": view_symbol,
            "timeframe": timeframe,
            "source": source,
            "price": price_data.get("price", 0),
            "change_24h": price_data.get("change_24h", 0),
            "change_percent_24h": price_data.get("change_percent_24h", 0),
            "volume_24h": price_data.get("volume_24h", 0),
            "indicators": indicators,
            "patterns": patterns,
            "chart_screenshot": chart_screenshot,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
