from fastapi import APIRouter, Depends, HTTPException
from auth.dependencies import get_current_user
from Hyperliquid.http_client import http_client
import logging

router = APIRouter(
    prefix="/api/user",
    tags=["User"]
)

logger = logging.getLogger(__name__)

@router.get("/profile")
async def get_user_profile(user: dict = Depends(get_current_user)):
    """
    Get current user profile (protected).
    """
    return {
        "user_id": user.get("sub"),
        "wallet_address": user.get("sub"),
        "claims": user
    }

@router.get("/orders")
async def get_user_orders(user: dict = Depends(get_current_user)):
    """
    Get active orders from Hyperliquid
    """
    wallet_address = user.get("sub")
    if not wallet_address:
        raise HTTPException(status_code=400, detail="Invalid wallet address")
        
    try:
        orders = await http_client.get_user_open_orders(wallet_address)
        return {"orders": orders, "user": wallet_address}
    except Exception as e:
        logger.error(f"Failed to fetch orders: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch orders from upstream")

@router.get("/positions")
async def get_user_positions(user: dict = Depends(get_current_user)):
    """
    Get user positions and balances from Hyperliquid
    """
    wallet_address = user.get("sub")
    if not wallet_address:
        raise HTTPException(status_code=400, detail="Invalid wallet address")

    try:
        state = await http_client.get_user_state(wallet_address)
        # Parse state
        # state usually has "assetPositions" and "marginSummary"
        return {
            "positions": state.get("assetPositions", []),
            "account_value": state.get("marginSummary", {}).get("accountValue"),
            "raw_state": state,
            "user": wallet_address
        }
    except Exception as e:
        logger.error(f"Failed to fetch positions: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch positions from upstream")
