from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from services.usage_service import usage_service

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
