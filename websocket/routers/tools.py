from fastapi import APIRouter, Depends, HTTPException, Body
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from auth.dependencies import get_current_user

# --- Tool Imports ---
from agent.Tools.trade_execution import place_order
from agent.Tools.tradingview.actions import (
    add_indicator, 
    remove_indicator, 
    clear_indicators, 
    set_timeframe, 
    set_symbol, 
    setup_trade, 
    add_price_alert, 
    mark_trading_session
)
from agent.Tools.tradingview.nav.actions import (
    focus_chart, 
    ensure_mode, 
    pan, 
    zoom, 
    press_key, 
    reset_view, 
    focus_latest, 
    get_screenshot, 
    hover_candle
)
from agent.Tools.tradingview.drawing.actions import (
    draw, 
    update_drawing, 
    clear_drawings
)
from agent.Tools.data.market import (
    get_price, 
    get_candles, 
    get_orderbook, 
    get_funding_rate,
    get_high_low_levels
)
from agent.Tools.data.analysis import (
    get_technical_analysis
)
from agent.Tools.data.research import (
    research_market,
    scan_market_overview
)
from agent.Tools.data.web import (
    search_news,
    search_sentiment
)
from agent.Tools.data.memory import (
    add_memory,
    search_memory,
    get_recent_history
)
from agent.Tools.data.knowledge import (
    search_knowledge_base
)

router = APIRouter(
    tags=["Tools"],
    prefix="/api/tools"
)


def _looks_like_wallet(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    raw = value.strip()
    if not raw.startswith("0x") or len(raw) != 42:
        return False
    try:
        int(raw[2:], 16)
        return True
    except Exception:
        return False


def _resolve_wallet_address(user: Dict[str, Any]) -> str:
    wallet = str(user.get("wallet_address") or "").strip()
    subject = str(user.get("sub") or "").strip()
    direct_address = str(user.get("address") or "").strip()
    if _looks_like_wallet(wallet):
        return wallet.lower()
    if _looks_like_wallet(subject):
        return subject.lower()
    if _looks_like_wallet(direct_address):
        return direct_address.lower()
    return ""


def _require_wallet_address(user: Dict[str, Any]) -> str:
    wallet = _resolve_wallet_address(user)
    if not _looks_like_wallet(wallet):
        raise HTTPException(
            status_code=401,
            detail="Wallet address not found in authentication context. Please reconnect wallet.",
        )
    return wallet.lower()

# --- Request Models ---

class TradeExecutionRequest(BaseModel):
    symbol: str
    side: str
    amount_usd: float
    leverage: int = 1
    order_type: str = "market"
    price: Optional[float] = None
    stop_price: Optional[float] = None
    tp: Optional[float] = None
    sl: Optional[float] = None
    exchange: Optional[str] = "simulation"
    tool_states: Optional[Dict[str, Any]] = None

# TradingView Action Models
class AddIndicatorRequest(BaseModel):
    symbol: str
    name: str
    inputs: Optional[Dict[str, Any]] = None
    force_overlay: bool = True

class RemoveIndicatorRequest(BaseModel):
    symbol: str
    name: str

class ClearIndicatorsRequest(BaseModel):
    symbol: str
    keep_volume: bool = False

class SetTimeframeRequest(BaseModel):
    symbol: str
    timeframe: str

class SetSymbolRequest(BaseModel):
    symbol: str
    target_symbol: str
    target_source: Optional[str] = None

class SetupTradeRequest(BaseModel):
    symbol: str
    side: str
    entry: float
    sl: float
    tp: float
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    trailing_sl: Optional[float] = None
    validation: Optional[float] = None
    invalidation: Optional[float] = None

class AddPriceAlertRequest(BaseModel):
    symbol: str
    price: float
    message: str

class MarkSessionRequest(BaseModel):
    symbol: str
    session: str

# TradingView Nav Models
class FocusChartRequest(BaseModel):
    symbol: str

class PanRequest(BaseModel):
    symbol: str
    axis: str
    direction: str
    amount: str = "medium"

class ZoomRequest(BaseModel):
    symbol: str
    mode: str
    amount: Optional[Any] = None

class ResetViewRequest(BaseModel):
    symbol: str

class GetScreenshotRequest(BaseModel):
    symbol: str

# Drawing Models
class DrawRequest(BaseModel):
    symbol: str
    tool: str
    points: List[Dict[str, Any]]
    style: Optional[Dict[str, Any]] = None
    text: Optional[str] = None
    id: Optional[str] = None

class ClearDrawingsRequest(BaseModel):
    symbol: str

# Data Models
class GetPriceRequest(BaseModel):
    symbol: str
    asset_type: str = "crypto"

class GetCandlesRequest(BaseModel):
    symbol: str
    timeframe: str = "1H"
    limit: int = 100
    asset_type: str = "crypto"

class GetHighLowLevelsRequest(BaseModel):
    symbol: str
    timeframe: str = "1H"
    lookback: int = 7
    asset_type: str = "crypto"

class ResearchMarketRequest(BaseModel):
    symbol: str
    timeframe: str = "1H"
    include_depth: bool = False

class ScanOverviewRequest(BaseModel):
    asset_class: str = "all"

class WebSearchRequest(BaseModel):
    query: str
    mode: str = "quality"
    source: str = "news"

class MemoryAddRequest(BaseModel):
    text: str
    metadata: Optional[Dict] = None

class MemorySearchRequest(BaseModel):
    query: str
    limit: int = 5

class KnowledgeSearchRequest(BaseModel):
    query: str
    category: Optional[str] = None
    top_k: int = 3

# --- Endpoints ---

# 1. Trade Execution
@router.post("/trade_execution/place_order")
async def execute_trade_tool(
    request: TradeExecutionRequest,
    user: dict = Depends(get_current_user)
):
    user_address = _require_wallet_address(user)
    result = await place_order(
        symbol=request.symbol,
        side=request.side,
        amount_usd=request.amount_usd,
        tool_states=request.tool_states or {},
        leverage=request.leverage,
        order_type=request.order_type,
        price=request.price,
        stop_price=request.stop_price,
        tp=request.tp,
        sl=request.sl,
        user_address=user_address,
        exchange=request.exchange
    )
    return result

# 2. TradingView Actions
@router.post("/tradingview/add_indicator")
async def execute_add_indicator(request: AddIndicatorRequest):
    return await add_indicator(request.symbol, request.name, request.inputs, request.force_overlay)

@router.post("/tradingview/remove_indicator")
async def execute_remove_indicator(request: RemoveIndicatorRequest):
    return await remove_indicator(request.symbol, request.name)

@router.post("/tradingview/clear_indicators")
async def execute_clear_indicators(request: ClearIndicatorsRequest):
    return await clear_indicators(request.symbol, request.keep_volume)

@router.post("/tradingview/set_timeframe")
async def execute_set_timeframe(request: SetTimeframeRequest):
    return await set_timeframe(request.symbol, request.timeframe)

@router.post("/tradingview/set_symbol")
async def execute_set_symbol(request: SetSymbolRequest):
    return await set_symbol(request.symbol, request.target_symbol, request.target_source)

@router.post("/tradingview/setup_trade")
async def execute_setup_trade(request: SetupTradeRequest):
    return await setup_trade(
        symbol=request.symbol,
        side=request.side,
        entry=request.entry,
        sl=request.sl,
        tp=request.tp,
        tp2=request.tp2,
        tp3=request.tp3,
        trailing_sl=request.trailing_sl,
        validation=request.validation,
        invalidation=request.invalidation
    )

@router.post("/tradingview/add_price_alert")
async def execute_add_price_alert(request: AddPriceAlertRequest):
    return await add_price_alert(request.symbol, request.price, request.message)

@router.post("/tradingview/mark_session")
async def execute_mark_session(request: MarkSessionRequest):
    return await mark_trading_session(request.symbol, request.session)

# 3. TradingView Navigation
@router.post("/tradingview/focus_chart")
async def execute_focus_chart(request: FocusChartRequest):
    return await focus_chart(request.symbol)

@router.post("/tradingview/pan")
async def execute_pan(request: PanRequest):
    return await pan(request.symbol, request.axis, request.direction, request.amount)

@router.post("/tradingview/zoom")
async def execute_zoom(request: ZoomRequest):
    return await zoom(request.symbol, request.mode, request.amount)

@router.post("/tradingview/reset_view")
async def execute_reset_view(request: ResetViewRequest):
    return await reset_view(request.symbol)

@router.post("/tradingview/get_screenshot")
async def execute_get_screenshot(request: GetScreenshotRequest):
    return await get_screenshot(request.symbol)

# 4. TradingView Drawing
@router.post("/tradingview/draw")
async def execute_draw(request: DrawRequest):
    return await draw(request.symbol, request.tool, request.points, request.style, request.text, request.id)

@router.post("/tradingview/clear_drawings")
async def execute_clear_drawings(request: ClearDrawingsRequest):
    return await clear_drawings(request.symbol)

# 5. Market Data
@router.post("/data/price")
async def execute_get_price(request: GetPriceRequest):
    return await get_price(request.symbol, request.asset_type)

@router.post("/data/candles")
async def execute_get_candles(request: GetCandlesRequest):
    return await get_candles(request.symbol, request.timeframe, request.limit, request.asset_type)

@router.post("/data/levels")
async def execute_get_levels(request: GetHighLowLevelsRequest):
    return await get_high_low_levels(request.symbol, request.timeframe, request.lookback, None, request.asset_type)

# 6. Research & Analysis
@router.post("/research/market")
async def execute_research_market(request: ResearchMarketRequest):
    return await research_market(request.symbol, request.timeframe, request.include_depth)

@router.post("/research/scan")
async def execute_scan_overview(request: ScanOverviewRequest):
    return await scan_market_overview(request.asset_class)

@router.post("/analysis/technical")
async def execute_technical_analysis(request: GetPriceRequest):
    # Reusing GetPriceRequest structure as it has symbol and asset_type
    return await get_technical_analysis(request.symbol, "1D", request.asset_type)

# 7. Web & Knowledge
@router.post("/web/search")
async def execute_web_search(request: WebSearchRequest):
    if request.source == "twitter":
        return await search_sentiment(request.query, request.mode) # Hacky: using query as symbol for sentiment? No, sentiment takes symbol.
        # Actually search_sentiment takes symbol. search_news takes query.
        # Let's clean this up.
        pass
    return await search_news(request.query, request.mode, request.source)

@router.post("/web/sentiment")
async def execute_sentiment(symbol: str = Body(..., embed=True), mode: str = Body("quality", embed=True)):
    return await search_sentiment(symbol, mode)

@router.post("/knowledge/search")
async def execute_knowledge_search(request: KnowledgeSearchRequest):
    return await search_knowledge_base(request.query, request.category, request.top_k)

# 8. Memory
@router.post("/memory/add")
async def execute_add_memory(
    request: MemoryAddRequest,
    user: dict = Depends(get_current_user)
):
    user_id = _require_wallet_address(user)
    return await add_memory(user_id, request.text, request.metadata)

@router.post("/memory/search")
async def execute_search_memory(
    request: MemorySearchRequest,
    user: dict = Depends(get_current_user)
):
    user_id = _require_wallet_address(user)
    return await search_memory(user_id, request.query, request.limit)

@router.get("/memory/history")
async def execute_get_history(
    limit: int = 10,
    user: dict = Depends(get_current_user)
):
    user_id = _require_wallet_address(user)
    return await get_recent_history(user_id, limit)
