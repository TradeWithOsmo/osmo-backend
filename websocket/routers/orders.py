"""
Orders API Endpoints

FastAPI routes for order management with security middleware.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List
from services.order_service import OrderService
from middleware.security import security_middleware

router = APIRouter(tags=["orders"])
order_service = OrderService()


# Request models
class PlaceOrderRequest(BaseModel):
    user_address: str
    symbol: str
    side: str  # 'buy' | 'sell'
    order_type: str  # 'market' | 'limit' | 'stop_limit'
    amount_usd: float
    leverage: int = 1
    price: Optional[float] = None
    stop_price: Optional[float] = None
    tp: Optional[float] = None
    sl: Optional[float] = None
    exchange: Optional[str] = None  # Auto-detect if not provided
    reduce_only: bool = False
    post_only: bool = False
    time_in_force: Optional[str] = 'GTC'  # 'GTC', 'IOC', 'FOK'
    trigger_condition: Optional[str] = None  # 'ABOVE', 'BELOW'

class ReportOrderRequest(BaseModel):
    user_address: str
    symbol: str
    side: str  # 'buy' | 'sell'
    order_type: str  # 'market' | 'limit' | 'stop_limit'
    amount_usd: float
    leverage: int = 1
    tx_hash: str
    price: Optional[float] = None
    stop_price: Optional[float] = None
    tp: Optional[float] = None
    sl: Optional[float] = None
    exchange: str = 'onchain'


@router.post("/report")
async def report_order(request_data: ReportOrderRequest, req: Request):
    """Report a successful on-chain order placement for immediate tracking"""
    try:
        await security_middleware.verify_user(req, request_data.user_address)
        
        result = await order_service.report_onchain_order(
            user_address=request_data.user_address,
            symbol=request_data.symbol,
            side=request_data.side,
            order_type=request_data.order_type,
            amount_usd=request_data.amount_usd,
            leverage=request_data.leverage,
            tx_hash=request_data.tx_hash,
            price=request_data.price,
            stop_price=request_data.stop_price,
            tp=request_data.tp,
            sl=request_data.sl,
            exchange=request_data.exchange
        )
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/place")
async def place_order(request_data: PlaceOrderRequest, req: Request):
    """Place new order"""
    try:
        # Security check
        await security_middleware.verify_user(req, request_data.user_address)
        
        result = await order_service.place_order(
            user_address=request_data.user_address,
            symbol=request_data.symbol,
            side=request_data.side,
            order_type=request_data.order_type,
            amount_usd=request_data.amount_usd,
            leverage=request_data.leverage,
            price=request_data.price,
            stop_price=request_data.stop_price,
            tp=request_data.tp,
            sl=request_data.sl,
            exchange=request_data.exchange,
            reduce_only=request_data.reduce_only,
            post_only=request_data.post_only,
            time_in_force=request_data.time_in_force,
            trigger_condition=request_data.trigger_condition
        )
        return {"success": True, **result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/cancel/{order_id}")
async def cancel_order(order_id: str, user_address: str, req: Request):
    """Cancel pending order"""
    try:
        await security_middleware.verify_user(req, user_address)
        
        result = await order_service.cancel_order(user_address, order_id)
        return {"success": True, **result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/history")
async def get_orders(
    user_address: str,
    status: Optional[str] = None,
    exchange: Optional[str] = None,
    req: Request = None,
):
    """Get order history"""
    try:
        await security_middleware.verify_user(req, user_address)
        
        orders = await order_service.get_user_orders(user_address, status=status, exchange=exchange)
        return {"success": True, "orders": orders}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/positions")
async def get_positions(user_address: str, exchange: Optional[str] = None, req: Request = None):
    """Get active positions"""
    try:
        await security_middleware.verify_user(req, user_address)
        
        result = await order_service.get_user_positions(user_address, exchange=exchange)
        return {"success": True, **result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class UpdateTPSLRequest(BaseModel):
    user_address: str
    symbol: str
    tp: Optional[str] = None
    sl: Optional[str] = None
    exchange: Optional[str] = None
    # Optional UI extensions
    size_tokens: Optional[float] = None
    tp_limit_price: Optional[float] = None
    sl_limit_price: Optional[float] = None

@router.post("/positions/tpsl")
async def update_tpsl(request_data: UpdateTPSLRequest, req: Request):
    """Update TP/SL for a position"""
    try:
        await security_middleware.verify_user(req, request_data.user_address)
        
        result = await order_service.update_position_tpsl(
            user_address=request_data.user_address,
            symbol=request_data.symbol,
            tp=request_data.tp,
            sl=request_data.sl,
            exchange=request_data.exchange,
            size_tokens=request_data.size_tokens,
            tp_limit_price=request_data.tp_limit_price,
            sl_limit_price=request_data.sl_limit_price,
        )
        return {"success": True, **result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class UpdateAllTPSLRequest(BaseModel):
    user_address: str
    tp: Optional[str] = None
    sl: Optional[str] = None
    tp_pct: Optional[float] = None
    sl_pct: Optional[float] = None
    exchange: Optional[str] = None


@router.post("/positions/tpsl/all")
async def update_all_tpsl(request_data: UpdateAllTPSLRequest, req: Request):
    """Bulk update TP/SL for all open positions"""
    try:
        await security_middleware.verify_user(req, request_data.user_address)

        result = await order_service.update_all_positions_tpsl(
            user_address=request_data.user_address,
            tp=request_data.tp,
            sl=request_data.sl,
            tp_pct=request_data.tp_pct,
            sl_pct=request_data.sl_pct,
            exchange=request_data.exchange,
        )
        return {"success": True, **result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- Trade Actions (Detailed Simulation) ---
from services.trade_action_service import trade_action_service

class ClosePositionRequest(BaseModel):
    user_address: str
    symbol: str
    exchange: Optional[str] = None
    price: Optional[float] = None
    size_pct: float = 1.0 # 0.0 - 1.0

class ReversePositionRequest(BaseModel):
    user_address: str
    symbol: str
    exchange: Optional[str] = None
    price: Optional[float] = None

@router.post("/close")
async def close_position(request_data: ClosePositionRequest, req: Request):
    """Close a position (Market or Limit if price provided)"""
    try:
        await security_middleware.verify_user(req, request_data.user_address)
        result = await trade_action_service.close_position(
            request_data.user_address, 
            request_data.symbol, 
            request_data.price,
            request_data.size_pct,
            exchange=request_data.exchange
        )
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/close/all")
async def close_all_positions(user_address: str, req: Request):
    """Close ALL open positions"""
    try:
        await security_middleware.verify_user(req, user_address)
        results = await trade_action_service.close_all_positions(user_address)
        return {"success": True, "results": results}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/reverse")
async def reverse_position(request_data: ReversePositionRequest, req: Request):
    """Reverse a position"""
    try:
        await security_middleware.verify_user(req, request_data.user_address)
        result = await trade_action_service.reverse_position(
            request_data.user_address,
            request_data.symbol,
            exchange=request_data.exchange,
            price=request_data.price,
        )
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
