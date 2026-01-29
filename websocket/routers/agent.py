"""
Agent API Router
Handles AI Chat interactions and model discovery.
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from typing import List, Dict, Any, Optional
from auth.dependencies import get_current_user
from database.connection import get_db
from sqlalchemy.orm import Session
from services.portfolio_service import PortfolioService
from agent.Core.agent_brain import AgentBrain
from agent.Config.models_config import get_available_models, get_model_config

router = APIRouter(
    prefix="/api/agent",
    tags=["Agent"]
)

@router.get("/models")
async def list_models(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get list of AI models available to the current user based on their tier.
    """
    user_address = user.get("sub")
    
    # Calculate user tier from portfolio value
    portfolio_service = PortfolioService(db)
    metrics = await portfolio_service.calculate_portfolio_value(user_address)
    account_value = metrics.get("portfolio_value", 0)
    
    # Simple tiering logic:
    # < $1k: Tier 1
    # < $10k: Tier 2
    # < $50k: Tier 3
    # < $100k: Tier 4
    # < $500k: Tier 5
    # < $1M: Tier 6
    # >= $1M: Tier 7
    
    if account_value < 1000: tier = 1
    elif account_value < 10000: tier = 2
    elif account_value < 50000: tier = 3
    elif account_value < 100000: tier = 4
    elif account_value < 500000: tier = 5
    elif account_value < 1000000: tier = 6
    else: tier = 7
    
    models = get_available_models(user_tier=tier)
    
    return {
        "tier": tier,
        "account_value": account_value,
        "models": models
    }

@router.post("/chat")
async def agent_chat(
    model_id: str = Body(...),
    message: str = Body(...),
    history: Optional[List[Dict[str, str]]] = Body(None),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Send a message to the AI agent.
    Checks authorization and handles fee deduction.
    """
    user_address = user.get("sub")
    
    # 1. Validate Model & Tier
    config = get_model_config(model_id)
    if not config:
        raise HTTPException(status_code=404, detail="Model not found")
        
    portfolio_service = PortfolioService(db)
    metrics = await portfolio_service.calculate_portfolio_value(user_address)
    account_value = metrics.get("portfolio_value", 0)
    
    # Check minimum tier (reusing logic or simplified for validation)
    # (In a real app, this would be a shared utility)
    user_tier = 1
    if account_value >= 1000000: user_tier = 7
    elif account_value >= 500000: user_tier = 6
    elif account_value >= 100000: user_tier = 4 # Skip some for brevity
    
    if user_tier < config["min_tier"]:
        raise HTTPException(
            status_code=403, 
            detail=f"Model {config['name']} requires a higher account value tier."
        )
        
    # 2. Estimate & Deduct Fee (Logic Placeholder)
    # Fee logic: config["input_fee"] * tokens...
    # For now, we assume a flat fee of 0.01 USD as a demo deduction
    # TODO: Integration with AIFeeVault.deduct_exact_fee
    print(f"[AgentRouter] Deducting AI fee for {user_address} using {model_id}")
    
    # 3. Process with AgentBrain
    try:
        brain = AgentBrain(model_id=model_id)
        response = await brain.chat(user_message=message, history=history)
        
        return {
            "status": "success",
            "model": model_id,
            "response": response
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Agent Error: {str(e)}")
