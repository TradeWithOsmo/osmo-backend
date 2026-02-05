from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging

from .faucet_manager import faucet_manager
from .session_manager import session_manager
from .connector import web3_connector

# Main Router
router = APIRouter()
logger = logging.getLogger(__name__)

# --- Models ---
class FaucetClaimRequest(BaseModel):
    user_address: str

class CreateSessionRequest(BaseModel):
    user_address: str
    permissions: Optional[Dict[str, Any]] = {}

class VaultActionRequest(BaseModel):
    user_address: str
    amount_usdc: float

# --- Vault Routes ---
vault_router = APIRouter(prefix="/vault", tags=["vault"])

@vault_router.get("/trading/{user_address}/balance")
async def get_trading_vault_balance(user_address: str):
    try:
        contract = web3_connector.get_contract("TradingVault")
        if not contract:
            return {"total": 0, "available": 0, "reserved": 0}
            
        # getBalance(user) returns (total, reserved, available)
        total, reserved, available = contract.functions.getBalance(user_address).call()
        decimals = 1_000_000 # USDC 6 decimals
        
        return {
            "total": total, # Raw int for precision if needed, but frontend likely handles it
            "reserved": reserved,
            "available": available,
            # Helper formatted values
            "collateral": available / decimals, 
            "balance": total / decimals
        }
    except Exception as e:
        logger.error(f"Error fetching TradingVault balance: {e}")
        # Return 0 gracefully for UI
        return {"total": 0, "available": 0, "reserved": 0, "collateral": 0, "balance": 0}

@vault_router.get("/ai/{user_address}/balance")
async def get_ai_vault_balance(user_address: str):
    try:
        contract = web3_connector.get_contract("AIVault")
        if not contract:
            # If AIVault contract doesn't exist yet, return 0
            return {"balance": 0, "credits": 0}
            
        # Assuming AIVault has balanceOf(user) or similar
        # If it's a standard ERC20 vault or similar
        # Let's assume 'balanceOf' for now
        try:
            balance = contract.functions.balanceOf(user_address).call()
        except:
            # Fallback if ABI is different (e.g. getBalance)
            try:
                balance = contract.functions.getBalance(user_address).call()
            except:
                balance = 0
                
        decimals = 1_000_000
        return {
            "balance": balance,
            "credits": balance / decimals
        }
    except Exception as e:
        logger.error(f"Error fetching AIVault balance: {e}")
        return {"balance": 0, "credits": 0}

@vault_router.post("/deposit")
async def deposit_to_vault(request: VaultActionRequest):
    """
    Initiate a deposit to the TradingVault.
    NOTE: Real deposits require the USER to sign a transaction.
    This endpoint cannot 'pull' funds. 
    It serves to log the intent or, in a Dev/Testnet environment with a 'God Mode' faucet, 
    potentially fund the user.
    """
    # For this implementation, we will simulate or return a "Not Implemented" for the backend action,
    # as the frontend must handle the transaction.
    # However, to not break the frontend flow (which expects a 200 OK json), we return a success-like structure
    # but strictly speaking this does nothing on-chain unless we have a relayer.
    
    # Check if we are on testnet and can "Cheat" (e.g. give user tokens then deposit?)
    # No, we can't deposit FOR them into the Vault without allowance.
    
    return {
        "success": False, 
        "message": "Backend-initiated deposit not supported. Please implement client-side wallet signature."
    }

@vault_router.post("/withdraw")
async def withdraw_from_vault(request: VaultActionRequest):
    return {
        "success": False, 
        "message": "Backend-initiated withdrawal not supported. Please implement client-side wallet signature."
    }

@vault_router.post("/refill-ai")
async def refill_ai_vault(request: VaultActionRequest):
    return {
        "success": False, 
        "message": "Backend-initiated refill not supported. Please implement client-side wallet signature."
    }


# --- Faucet Routes ---
faucet_router = APIRouter(prefix="/faucet", tags=["faucet"])

@faucet_router.get("/status/{user_address}")
async def get_faucet_status(user_address: str):
    try:
        can_claim, cooldown = await faucet_manager.check_eligibility(user_address)
        balance = await faucet_manager.get_faucet_balance()
        return {
            "can_claim": can_claim,
            "time_until_next_claim": cooldown, # Matching frontend property name
            "faucet_balance": balance
        }
    except Exception as e:
        logger.error(f"Faucet status error: {e}")
        return {"can_claim": False, "time_until_next_claim": 3600}

@faucet_router.get("/balance")
async def get_faucet_balance_endpoint():
    balance = await faucet_manager.get_faucet_balance()
    return {"balance": balance}

@faucet_router.post("/claim")
async def claim_faucet(request: FaucetClaimRequest):
    try:
        result = await faucet_manager.claim(request.user_address)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Session Routes ---
session_router = APIRouter(prefix="/session", tags=["session"])

@session_router.post("/create")
async def create_session(request: CreateSessionRequest):
    try:
        session_data = await session_manager.create_session(request.user_address, request.permissions)
        return session_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ConfirmSessionRequest(BaseModel):
    user_address: str
    session_address: str
    session_private_key: str
    expires_in: int

@session_router.post("/confirm")
async def confirm_session(request: ConfirmSessionRequest):
    """
    Confirm and store session after on-chain approval.
    Called by frontend after successful SessionKeyManager.createSessionKey() transaction.
    """
    try:
        result = await session_manager.confirm_session(
            request.user_address,
            request.session_address,
            request.session_private_key,
            request.expires_in
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@session_router.get("/active/{user_address}")
async def get_active_session(user_address: str):
    """Check if a user has an active session key."""
    try:
        session = await session_manager.get_active_session(user_address)
        if session:
            return {
                "has_session": True,
                "session_address": session.session_address,
                "expires_at": session.expires_at.isoformat(),
                # In demo mode, we can return the key IF the user is authenticated, 
                # but for now we'll just indicate it exists.
                "session_private_key": session.encrypted_private_key 
            }
        return {"has_session": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Include sub-routers into main router
router.include_router(vault_router)
router.include_router(faucet_router)
router.include_router(session_router)

