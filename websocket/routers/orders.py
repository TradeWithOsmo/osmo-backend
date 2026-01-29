"""
Orders API Endpoints

FastAPI routes for order management with security middleware.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List
from services.order_service import OrderService
from middleware.security import security_middleware

router = APIRouter(prefix="/api/orders", tags=["orders"])
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
    exchange: Optional[str] = None  # Auto-detect if not provided


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
            exchange=request_data.exchange
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
async def get_orders(user_address: str, status: Optional[str] = None, req: Request = None):
    """Get order history"""
    try:
        await security_middleware.verify_user(req, user_address)
        
        orders = await order_service.get_user_orders(user_address, status)
        return {"success": True, "orders": orders}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/positions")
async def get_positions(user_address: str, req: Request = None):
    """Get active positions"""
    try:
        await security_middleware.verify_user(req, user_address)
        
        positions = await order_service.get_user_positions(user_address)
        return {"success": True, "positions": positions}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
