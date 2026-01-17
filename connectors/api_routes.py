"""
FastAPI Routes for Data Connectors

API endpoints for TradingView indicator receiver and connector management.
"""

from fastapi import APIRouter, HTTPException, Depends
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
    redis_client = await redis.from_url("redis://redis:6379")
    try:
        yield redis_client
    finally:
        await redis_client.close()


# Dependency: Get connector manager
def get_manager():
    """
    Get connector manager instance.
    
    In production, this should be initialized once at app startup
    and stored in app.state.
    """
    from ..manager import ConnectorManager
    from ..tradingview import TradingViewConnector
    from ..chainlink import ChainlinkConnector
    from ..hyperliquid import HyperliquidConnector
    from ..ostium import OstiumConnector
    
    # This is simplified - in production, initialize in lifespan
    manager = ConnectorManager()
    return manager


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


@router.get("/price/{symbol}")
async def get_price(
    symbol: str,
    asset_type: str = "crypto",  # "crypto" or "rwa"
    manager = Depends(get_manager)
):
    """
    Get current price for symbol.
    
    Args:
        symbol: Trading symbol (e.g., "BTC", "GOLD")
        asset_type: "crypto" (Hyperliquid) or "rwa" (Ostium)
    
    Returns:
        Price data from appropriate connector
    """
    try:
        from ..data.market import get_current_price
        
        price_data = await get_current_price(manager, symbol, asset_type)
        
        return price_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analysis/technical/{symbol}")
async def get_technical_analysis(
    symbol: str,
    timeframe: str = "1D",
    asset_type: str = "crypto",
    manager = Depends(get_manager)
):
    """
    Get algorithmic technical analysis (patterns + indicators).
    Uses pandas-ta on raw OHLCV data.
    
    Args:
        symbol: Trading symbol
        timeframe: Candle timeframe (default 1D)
        asset_type: "crypto" or "rwa"
        
    Returns:
        {
            "symbol": "BTC",
            "price": 42000,
            "indicators": {...},
            "patterns": ["Doji", "Bullish Engulfing"]
        }
    """
    try:
        from analysis.engine import TechnicalAnalysisEngine
        from ..manager import DataCategory, AssetType
        
        # 1. Fetch OHLCV Data
        # Map string asset_type to Enum
        a_type = AssetType.CRYPTO if asset_type == "crypto" else AssetType.RWA
        
        # Fetch candles (returns list of dicts)
        # Note: We rely on ConnectorManager to route to Hyperliquid/Ostium
        candles_data = await manager.fetch_data(
            category=DataCategory.CANDLES,
            symbol=symbol,
            asset_type=a_type,
            timeframe=timeframe,
            limit=50  # Need enough for indicators
        )
        
        # Extract the list of candles from the response
        # Hyperliquid/Ostium connectors should return standard format
        # If response is wrapped, extract 'data'
        ohlcv = candles_data.get("data", []) if isinstance(candles_data, dict) else candles_data
        
        # 2. Run Analysis
        engine = TechnicalAnalysisEngine()
        result = engine.analyze_ticker(symbol, timeframe, ohlcv)
        
        return result

    except Exception as e:
        print(f"Analysis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
