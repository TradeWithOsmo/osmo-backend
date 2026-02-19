"""
Trade Setup Routes

API endpoints for trade setup management with GP/GL monitoring.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from services.price_monitor_service import price_monitor_service

router = APIRouter(prefix="/api/trade-setups", tags=["Trade Setups"])


class CreateTradeSetupRequest(BaseModel):
    symbol: str
    side: str
    entry_price: float
    tp: Optional[float] = None
    sl: Optional[float] = None
    gp: Optional[float] = None
    gl: Optional[float] = None
    gp_note: Optional[str] = None
    gl_note: Optional[str] = None
    exchange: str = "simulation"
    session_id: Optional[str] = None
    position_id: Optional[int] = None


class UpdateGPGLRequest(BaseModel):
    gp: Optional[float] = None
    gl: Optional[float] = None


class AdjustTPSLGPGLRequest(BaseModel):
    tp: Optional[float] = None
    sl: Optional[float] = None
    gp: Optional[float] = None
    gl: Optional[float] = None


@router.post("/")
async def create_trade_setup(
    request: CreateTradeSetupRequest,
    user_address: str = None,
):
    """Create a new trade setup with GP/GL levels for monitoring."""
    if not user_address:
        raise HTTPException(status_code=401, detail="User address required")

    setup = await price_monitor_service.create_trade_setup(
        user_address=user_address,
        symbol=request.symbol,
        side=request.side,
        entry_price=request.entry_price,
        exchange=request.exchange,
        session_id=request.session_id,
        position_id=request.position_id,
        tp=request.tp,
        sl=request.sl,
        gp=request.gp,
        gl=request.gl,
        gp_note=request.gp_note,
        gl_note=request.gl_note,
    )

    return {
        "status": "created",
        "setup_id": setup.id,
        "symbol": setup.symbol,
        "side": setup.side,
        "gp": setup.gp,
        "gl": setup.gl,
    }


@router.get("/")
async def get_active_setups(user_address: str = None):
    """Get all active trade setups for a user."""
    if not user_address:
        raise HTTPException(status_code=401, detail="User address required")

    setups = await price_monitor_service.get_active_setups(user_address)
    return {"setups": setups}


@router.put("/position/{symbol}")
async def update_position_gpgl(
    symbol: str,
    request: UpdateGPGLRequest,
    user_address: str = None,
    exchange: str = "simulation",
):
    """Update GP/GL levels for an existing position."""
    if not user_address:
        raise HTTPException(status_code=401, detail="User address required")

    success = await price_monitor_service.update_position_gpgl(
        user_address=user_address,
        symbol=symbol,
        exchange=exchange,
        gp=request.gp,
        gl=request.gl,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Position not found")

    return {
        "status": "updated",
        "symbol": symbol,
        "gp": request.gp,
        "gl": request.gl,
    }


@router.delete("/{setup_id}")
async def cancel_trade_setup(
    setup_id: int,
    user_address: str = None,
):
    """Cancel a trade setup."""
    if not user_address:
        raise HTTPException(status_code=401, detail="User address required")

    success = await price_monitor_service.cancel_setup(
        setup_id=setup_id,
        user_address=user_address,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Trade setup not found")

    return {"status": "cancelled", "setup_id": setup_id}


@router.post("/adjust/{symbol}")
async def adjust_tpsl_gpgl(
    symbol: str,
    request: AdjustTPSLGPGLRequest,
    user_address: str = None,
    exchange: str = "simulation",
):
    """
    Adjust TP/SL/GP/GL for a position.
    
    This is an alias for the AI tool adjust_position_tpsl with GP/GL support.
    """
    if not user_address:
        raise HTTPException(status_code=401, detail="User address required")

    from agent.Orchestrator.execution_adapter import ExecutionAdapter

    result = await ExecutionAdapter.adjust_position_tpsl(
        user_address=user_address,
        symbol=symbol,
        tp=request.tp,
        sl=request.sl,
        gp=request.gp,
        gl=request.gl,
        exchange=exchange,
    )

    if result.get("error"):
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result
