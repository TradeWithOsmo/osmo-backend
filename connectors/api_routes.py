"""
FastAPI Routes for Data Connectors

API endpoints for TradingView indicator receiver and connector management.
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import redis.asyncio as redis


router = APIRouter(prefix="/api/connectors", tags=["connectors"])


# Pydantic models for request/response
class IndicatorData(BaseModel):
    """TradingView indicator data"""
    symbol: str
    timeframe: str  # "1m", "5m", "1H", "4H", "1D"
    indicators: Dict[str, Any]
    chart_screenshot: Optional[str] = None  # base64 PNG
    timestamp: int


class IndicatorResponse(BaseModel):
    """Response for indicator storage"""
    status: str
    symbol: str
    timeframe: str
    indicator_count: int
    has_screenshot: bool


class ConnectorStatusResponse(BaseModel):
    """Connector health status"""
    name: str
    status: str
    rpc_connected: Optional[bool] = None
    supported_feeds: Optional[List[str]] = None


# Dependency: Get Redis client
async def get_redis():
    """Get Redis connection"""
    try:
        # Use service name 'redis' which is defined in docker-compose
        redis_client = await redis.from_url(
            "redis://redis:6379",
            encoding="utf-8",
            decode_responses=True
        )
        yield redis_client
    except Exception as e:
        print(f"Redis Dependency Error: {e}")
        raise
    finally:
        await redis_client.close()


# Dependency: Get connector manager
def get_manager():
    """
    Get connector manager instance.
    Uses the global registry initialized in main.py.
    """
    from connectors.init_connectors import get_connector_manager
    return get_connector_manager()


class CommandRequest(BaseModel):
    symbol: str
    action: str  # "set_timeframe", "add_indicator"
    params: Dict[str, Any]


@router.post("/tradingview/commands")
async def send_tradingview_command(
    cmd: CommandRequest,
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Queue a command for the TradingView frontend.
    """
    try:
        from connectors.tradingview import TradingViewConnector
        connector = TradingViewConnector({"redis_client": redis_client})
        await connector.queue_command(cmd.symbol, {"action": cmd.action, "params": cmd.params})
        return {"status": "queued", "command": cmd.dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tradingview/commands/{symbol}")
async def get_tradingview_commands(
    symbol: str,
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Get pending commands for the frontend.
    """
    try:
        from connectors.tradingview import TradingViewConnector
        connector = TradingViewConnector({"redis_client": redis_client})
        commands = await connector.get_pending_commands(symbol)
        return commands
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tradingview/indicators", response_model=IndicatorResponse)
async def receive_tradingview_indicators(
    data: IndicatorData,
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Receive indicator data from TradingView widget.
    
    Frontend extraction:
    ```typescript
    const chart = widget.activeChart();
    const studies = chart.getAllStudies();
    const indicators = {};
    studies.forEach(study => {
        indicators[study.name] = study.getPlotValues();
    });
    
    await fetch('/api/connectors/tradingview/indicators', {
        method: 'POST',
        body: JSON.stringify({
            symbol: chart.symbol(),
            timeframe: chart.resolution(),
            indicators,
            timestamp: Date.now()
        })
    });
    ```
    """
    try:
        from connectors.tradingview import TradingViewConnector
        
        # Initialize connector with Redis
        tv_connector = TradingViewConnector({"redis_client": redis_client})
        
        # Store indicators
        result = await tv_connector.store_indicators(data.dict())
        
        return IndicatorResponse(**result)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tradingview/indicators")
async def get_tradingview_indicators(
    symbol: str,
    timeframe: str,
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Get cached TradingView indicators.
    
    Args:
        symbol: Trading symbol (e.g., "BTC/USDT")
        timeframe: Chart timeframe (e.g., "1D")
    """
    try:
        from connectors.tradingview import TradingViewConnector
        
        tv_connector = TradingViewConnector({"redis_client": redis_client})
        
        result = await tv_connector.fetch(symbol, timeframe=timeframe)
        
        return result
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status", response_model=Dict[str, ConnectorStatusResponse])
async def get_all_connector_statuses(
    manager = Depends(get_manager)
):
    """
    Get health status of all connectors.
    
    Returns:
        {
            "hyperliquid": {"name": "hyperliquid", "status": "healthy"},
            "ostium": {"name": "ostium", "status": "healthy"},
            "chainlink": {"name": "chainlink", "status": "healthy", "rpc_connected": true},
            ...
        }
    """
    try:
        statuses = manager.get_all_statuses()
        return statuses
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hyperliquid/prices")
async def get_hyperliquid_prices(
    manager = Depends(get_manager)
):
    """
    Get ALL Hyperliquid prices/tickers.
    """
    try:
        from connectors.manager import AssetType
        return await manager.fetch_all_markets(AssetType.CRYPTO)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ostium/prices")
async def get_ostium_prices(
    manager = Depends(get_manager)
):
    """
    Get ALL Ostium prices/tickers.
    """
    try:
        from connectors.manager import AssetType
        return await manager.fetch_all_markets(AssetType.RWA)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/price/{symbol}")
async def get_price(
    symbol: str,
    asset_type: str = "crypto",  # "crypto" or "rwa"
    manager = Depends(get_manager)
):

    """
    Get current price for symbol.
    """
    try:
        from connectors.manager import AssetType, DataCategory
        
        a_type = AssetType.CRYPTO if asset_type == "crypto" else AssetType.RWA
        
        # Use manager directly
        result = await manager.fetch_data(
            category=DataCategory.MARKET,
            symbol=symbol,
            asset_type=a_type
        )
        return result
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/funding/{symbol}")
async def get_funding_rate(
    symbol: str,
    manager = Depends(get_manager)
):
    """
    Get funding rate data.
    """
    try:
        from connectors.manager import DataCategory
        result = await manager.fetch_data(
            category=DataCategory.FUNDING,
            symbol=symbol
        )
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orderbook/{symbol}")
async def get_orderbook(
    symbol: str,
    manager = Depends(get_manager)
):
    """
    Get L2 Orderbook data.
    """
    try:
        from connectors.manager import DataCategory
        result = await manager.fetch_data(
            category=DataCategory.ORDERBOOK,
            symbol=symbol
        )
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/candles/{symbol}")
async def get_candles(
    symbol: str,
    timeframe: str = "1H",
    limit: int = 100,
    asset_type: str = "crypto",
    manager = Depends(get_manager)
):
    """
    Get OHLCV Candles (Raw).
    """
    try:
        from connectors.manager import AssetType, DataCategory
        
        a_type = AssetType.CRYPTO if asset_type == "crypto" else AssetType.RWA
        
        result = await manager.fetch_data(
            category=DataCategory.CANDLES,
            symbol=symbol,
            asset_type=a_type,
            timeframe=timeframe,
            limit=limit
        )
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/web_search/search")
async def search_web(
    query: str,
    source: str = "news",
    manager = Depends(get_manager)
):
    """
    Execute web search via Grok or Perplexity.
    """
    try:
        # Get connector by name
        connector = manager.get_connector("web_search")
        if not connector:
            raise HTTPException(status_code=404, detail="Web search connector not active")

        result = await connector.fetch("UNKNOWN", query=query, source=source)
        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dune/whale_trades/{symbol}")
async def get_whale_trades(
    symbol: str,
    min_size_usd: int = 100000,
    manager = Depends(get_manager)
):
    """
    Get whale trades from Dune Analytics.
    """
    try:
        connector = manager.get_connector("dune")
        if not connector:
            raise HTTPException(status_code=404, detail="Dune connector not active")

        result = await connector.fetch(symbol, min_size_usd=min_size_usd)
        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/analysis/technical/{symbol}")
async def get_technical_analysis(
    symbol: str,
    timeframe: str = "1D",
    asset_type: str = "crypto",
    manager = Depends(get_manager)
):
    """
    Get algorithmic technical analysis.
    """
    try:
        from analysis.engine import TechnicalAnalysisEngine
        from connectors.manager import DataCategory, AssetType
        
        # 1. Fetch OHLCV Data
        a_type = AssetType.CRYPTO if asset_type == "crypto" else AssetType.RWA
        
        candles_data = await manager.fetch_data(
            category=DataCategory.CANDLES,
            symbol=symbol,
            asset_type=a_type,
            timeframe=timeframe,
            limit=50
        )
        
        ohlcv = candles_data.get("data", []) if isinstance(candles_data, dict) else candles_data
        
        # 2. Run Analysis
        engine = TechnicalAnalysisEngine()
        result = engine.analyze_ticker(symbol, timeframe, ohlcv)
        
        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history")
async def get_history(
    symbol: str,
    resolution: str,
    from_: int = Query(..., alias="from"),
    to: int = Query(..., alias="to"),
    source: str = "hyperliquid",
    manager = Depends(get_manager)
):
    """
    Get Historical Candles for TradingView.
    """
    try:
        # TODO: Implement actual history fetch using manager
        
        # Temporary Mock Response to prevent Chart Error
        return {
            "s": "no_data",
            "nextTime": None
        }
        
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

