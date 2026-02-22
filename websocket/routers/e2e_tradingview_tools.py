from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from agent.Tools.tradingview.actions import (
    add_indicator,
    remove_indicator,
    clear_indicators,
    verify_indicator_present,
    set_timeframe,
    set_symbol,
    setup_trade,
    add_price_alert,
    mark_trading_session,
    list_supported_indicator_aliases,
)
from agent.Tools.tradingview.verify import verify_tradingview_state
from agent.Tools.tradingview.drawing.actions import (
    draw,
    update_drawing,
    clear_drawings,
    list_supported_draw_tools,
)


router = APIRouter(prefix="/api/e2e/tools/tradingview", tags=["e2e-tools"])


class AddIndicatorRequest(BaseModel):
    symbol: str
    name: str
    inputs: Optional[Dict[str, Any]] = None
    force_overlay: bool = False


class RemoveIndicatorRequest(BaseModel):
    symbol: str
    name: str


class VerifyIndicatorRequest(BaseModel):
    symbol: str
    name: str
    timeframe: str = "1D"
    timeout_sec: float = 6.0


class VerifyTradingViewStateRequest(BaseModel):
    symbol: str
    timeframe: str = "1D"
    require_indicators: Optional[List[str]] = None
    require_drawings: Optional[List[str]] = None
    require_trade_setup: Optional[Dict[str, Any]] = None
    timeout_sec: float = 6.0


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
    be: Optional[float] = None
    liq: Optional[float] = None
    gp: Optional[float] = None
    gl: Optional[float] = None
    validation: Optional[float] = None
    invalidation: Optional[float] = None
    validation_note: Optional[str] = None
    invalidation_note: Optional[str] = None


class AddPriceAlertRequest(BaseModel):
    symbol: str
    price: float
    message: str


class MarkSessionRequest(BaseModel):
    symbol: str
    session: str


class DrawRequest(BaseModel):
    symbol: str
    tool: str
    points: List[Dict[str, Any]]
    style: Optional[Dict[str, Any]] = None
    text: Optional[str] = None
    id: Optional[str] = None


class UpdateDrawingRequest(BaseModel):
    symbol: str
    id: str
    points: Optional[List[Dict[str, Any]]] = None
    style: Optional[Dict[str, Any]] = None
    text: Optional[str] = None


class ClearDrawingsRequest(BaseModel):
    symbol: str


@router.get("/ping")
async def ping() -> Dict[str, Any]:
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


@router.get("/indicator_aliases")
async def indicator_aliases() -> Dict[str, Any]:
    return await list_supported_indicator_aliases()


@router.get("/draw_tools")
async def draw_tools() -> Dict[str, Any]:
    return await list_supported_draw_tools()


@router.post("/add_indicator")
async def e2e_add_indicator(req: AddIndicatorRequest) -> Dict[str, Any]:
    return await add_indicator(req.symbol, req.name, req.inputs, req.force_overlay)


@router.post("/remove_indicator")
async def e2e_remove_indicator(req: RemoveIndicatorRequest) -> Dict[str, Any]:
    return await remove_indicator(req.symbol, req.name)


@router.post("/verify_indicator_present")
async def e2e_verify_indicator_present(req: VerifyIndicatorRequest) -> Dict[str, Any]:
    return await verify_indicator_present(
        symbol=req.symbol,
        name=req.name,
        timeframe=req.timeframe,
        timeout_sec=req.timeout_sec,
    )


@router.post("/verify_state")
async def e2e_verify_state(req: VerifyTradingViewStateRequest) -> Dict[str, Any]:
    return await verify_tradingview_state(
        symbol=req.symbol,
        timeframe=req.timeframe,
        require_indicators=req.require_indicators,
        require_drawings=req.require_drawings,
        require_trade_setup=req.require_trade_setup,
        timeout_sec=req.timeout_sec,
    )


@router.post("/clear_indicators")
async def e2e_clear_indicators(req: ClearIndicatorsRequest) -> Dict[str, Any]:
    return await clear_indicators(req.symbol, req.keep_volume)


@router.post("/set_timeframe")
async def e2e_set_timeframe(req: SetTimeframeRequest) -> Dict[str, Any]:
    return await set_timeframe(req.symbol, req.timeframe)


@router.post("/set_symbol")
async def e2e_set_symbol(req: SetSymbolRequest) -> Dict[str, Any]:
    return await set_symbol(req.symbol, req.target_symbol, req.target_source)


@router.post("/setup_trade")
async def e2e_setup_trade(req: SetupTradeRequest) -> Dict[str, Any]:
    return await setup_trade(
        symbol=req.symbol,
        side=req.side,
        entry=req.entry,
        sl=req.sl,
        tp=req.tp,
        tp2=req.tp2,
        tp3=req.tp3,
        trailing_sl=req.trailing_sl,
        be=req.be,
        liq=req.liq,
        gp=req.gp,
        gl=req.gl,
        validation=req.validation,
        invalidation=req.invalidation,
        validation_note=req.validation_note,
        invalidation_note=req.invalidation_note,
    )


@router.post("/add_price_alert")
async def e2e_add_price_alert(req: AddPriceAlertRequest) -> Dict[str, Any]:
    return await add_price_alert(req.symbol, req.price, req.message)


@router.post("/mark_session")
async def e2e_mark_session(req: MarkSessionRequest) -> Dict[str, Any]:
    return await mark_trading_session(req.symbol, req.session)


@router.post("/draw")
async def e2e_draw(req: DrawRequest) -> Dict[str, Any]:
    return await draw(req.symbol, req.tool, req.points, req.style, req.text, req.id)


@router.post("/update_drawing")
async def e2e_update_drawing(req: UpdateDrawingRequest) -> Dict[str, Any]:
    return await update_drawing(req.symbol, req.id, req.points, req.style, req.text)


@router.post("/clear_drawings")
async def e2e_clear_drawings(req: ClearDrawingsRequest) -> Dict[str, Any]:
    return await clear_drawings(req.symbol)
