from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from services.usage_service import usage_service
from services.openrouter_service import openrouter_service

router = APIRouter()

# --- Response Models ---
class usage_stat_response(BaseModel):
    total_cost: float
    total_tokens: int
    request_count: int
    credit_balance: float

class usage_log_item(BaseModel):
    id: int
    model: str
    tokens: int
    cost: float
    timestamp: datetime
    status: str = "Complete" # Placeholder

class usage_chart_point(BaseModel):
    date: str
    cost: float
    tokens: int
    requests: int

# --- Endpoints ---

@router.get("/stats/{user_address}")
async def get_stats(user_address: str):
    stats = await usage_service.get_user_stats(user_address)
    return stats

@router.get("/history/{user_address}")
async def get_history(
    user_address: str, 
    limit: int = 50, 
    offset: int = 0
):
    logs = await usage_service.get_history(user_address, limit, offset)
    
    # Transform to frontend format
    return [
        {
            "id": log.id,
            "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M"),
            "model": log.model,
            "tokens": f"{log.input_tokens + log.output_tokens:,}",
            "cost": f"${log.cost:.4f}",
            "speed": "N/A", # Not tracked yet
            "finish": "Complete"
        }
        for log in logs
    ]

@router.get("/chart/{user_address}")
async def get_chart(user_address: str, timeframe: str = "30D"):
    days = 30
    if timeframe == "7D": days = 7
    if timeframe == "1D": days = 1 # Not supported by daily snapshot yet
    if timeframe == "ALL": days = 365
    
    data = await usage_service.get_chart_data(user_address, days)
    return data

@router.get("/models")
async def get_models(provider: Optional[str] = None, search: Optional[str] = None):
    """Get real-time model pricing from OpenRouter merged with usage stats"""
    if provider:
        models = await openrouter_service.get_models_by_provider(provider)
    else:
        models = await openrouter_service.get_models(search=search)
        
    # Inject real weekly usage data
    weekly_usage = await usage_service.get_global_weekly_usage()
    for model in models:
        model["weekly_tokens"] = weekly_usage.get(model["id"], 0)
        
    return models

@router.get("/providers")
async def get_providers():
    """Get list of available model providers"""
    return await openrouter_service.get_providers()

@router.get("/last-used/{user_address}")
async def get_last_used(user_address: str, timeframe: str = "all"):
    """Get list of last used models for a specific user"""
    data = await usage_service.get_last_used_models(user_address, timeframe)
    return data

class EnabledModelsRequest(BaseModel):
    models: List[str]

@router.get("/models/enabled/default")
async def get_default_enabled_models():
    """Get list of default enabled models"""
    return await usage_service.get_default_enabled_models()

@router.get("/models/enabled/{user_address}")
async def get_enabled_models(user_address: str):
    """Get list of enabled models for a user"""
    return await usage_service.get_enabled_models(user_address)

@router.post("/models/enabled/{user_address}")
async def save_enabled_models(user_address: str, request: EnabledModelsRequest):
    """Save list of enabled models for a user"""
    success = await usage_service.save_enabled_models(user_address, request.models)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save models")
    return {"status": "success"}

# --- Agent Enablement Endpoints ---

class EnabledAgentsRequest(BaseModel):
    agents: List[str]

@router.get("/agents/enabled/default")
async def get_default_enabled_agents():
    """Get list of default enabled agents"""
    return await usage_service.get_default_enabled_agents()

@router.get("/agents/enabled/{user_address}")
async def get_enabled_agents(user_address: str):
    """Get list of enabled agents for a user"""
    return await usage_service.get_enabled_agents(user_address)

@router.post("/agents/enabled/{user_address}")
async def save_enabled_agents(user_address: str, request: EnabledAgentsRequest):
    """Save list of enabled agents for a user"""
    success = await usage_service.save_enabled_agents(user_address, request.agents)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save agents")
    return {"status": "success"}
