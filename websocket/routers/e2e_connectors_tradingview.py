from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from connectors.tradingview import TradingViewConnector

logger = logging.getLogger(__name__)

router = APIRouter()


# Single in-process TradingView connector instance for E2E.
# Uses in-memory fallback when Redis is unavailable, so the command loop works.
_tv = TradingViewConnector(config={"redis_client": None, "cache_ttl": 0})


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
    active_indicators: Optional[List[str]] = None
    drawing_tags: Optional[List[str]] = None
    trade_setup: Optional[Dict[str, Any]] = None
    timestamp: Optional[int] = None


def _model_to_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


@router.get("/status")
async def status() -> Dict[str, Any]:
    return {"connectors": ["tradingview"], "count": 1}


@router.post("/tradingview/commands")
async def send_tradingview_command(
    cmd: CommandRequest,
    wait_for_completion: bool = Query(False),
    timeout_sec: float = Query(6.0, ge=0.5, le=60.0),
    poll_interval_sec: float = Query(0.2, ge=0.05, le=2.0),
):
    """
    E2E-only TradingView command endpoint.
    This is intentionally minimal (no HL/Ostium caches, no web3 deps).
    """
    try:
        queued = await _tv.queue_command(cmd.symbol, {"action": cmd.action, "params": cmd.params or {}})
        if not queued:
            raise HTTPException(status_code=400, detail="Invalid tradingview command payload")

        if not wait_for_completion:
            return {"status": "queued", "command": queued}

        result = await _tv.wait_for_command_result(
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
async def get_tradingview_commands(symbol: str) -> List[Dict[str, Any]]:
    try:
        return await _tv.get_pending_commands(symbol)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/tradingview/commands/result")
async def report_tradingview_command_result(payload: CommandResultRequest) -> Dict[str, Any]:
    try:
        stored = await _tv.store_command_result(
            command_id=payload.command_id,
            status=payload.status,
            result=payload.result,
            error=payload.error,
        )
        return {"status": "acknowledged", "result": stored}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/tradingview/indicators")
async def receive_tradingview_indicators(data: IndicatorData) -> Dict[str, Any]:
    try:
        payload = _model_to_dict(data)
        return await _tv.store_indicators(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/tradingview/indicators")
async def get_tradingview_indicators(symbol: str, timeframe: str) -> Dict[str, Any]:
    try:
        return await _tv.fetch(symbol, timeframe=timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
