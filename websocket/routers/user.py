from fastapi import APIRouter, Depends, HTTPException
from auth.dependencies import get_current_user
from Hyperliquid.http_client import http_client
import logging

router = APIRouter(
    prefix="/api/user",
    tags=["User"]
)

logger = logging.getLogger(__name__)


def _looks_like_wallet(value: str | None) -> bool:
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


def _resolve_wallet_address(user: dict) -> str:
    for key in ("wallet_address", "sub", "address"):
        value = str(user.get(key) or "").strip()
        if _looks_like_wallet(value):
            return value.lower()
    return ""


def _require_wallet_address(user: dict) -> str:
    wallet = _resolve_wallet_address(user)
    if not wallet:
        raise HTTPException(
            status_code=401,
            detail="Wallet address not found in authentication context. Please reconnect wallet.",
        )
    return wallet

@router.get("/profile")
async def get_user_profile(user: dict = Depends(get_current_user)):
    """
    Get current user profile (protected).
    """
    wallet_address = _require_wallet_address(user)
    return {
        "user_id": wallet_address,
        "wallet_address": wallet_address,
        "claims": user
    }

@router.get("/orders")
async def get_user_orders(user: dict = Depends(get_current_user)):
    """
    Get active orders from Hyperliquid
    """
    wallet_address = _require_wallet_address(user)
        
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
    wallet_address = _require_wallet_address(user)

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
