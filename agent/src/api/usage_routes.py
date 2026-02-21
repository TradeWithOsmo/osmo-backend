"""
API Routes for Usage Tracking
Endpoints for monitoring LLM usage, costs, and analytics
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from src.services.usage_tracker import usage_tracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/usage", tags=["usage"])


# ============================================================================
# Schemas
# ============================================================================


class UsageStats(BaseModel):
    """User usage statistics"""

    total_cost: float
    total_tokens: int
    request_count: int
    credit_balance: float


class UsageLogEntry(BaseModel):
    """Individual usage log entry"""

    id: int
    model: str
    input_tokens: int
    output_tokens: int
    cost: float
    timestamp: str


class UsageChartEntry(BaseModel):
    """Daily usage for charts"""

    date: str
    cost: float
    tokens: int
    requests: int


class ModelUsageEntry(BaseModel):
    """Model usage statistics"""

    model: str
    request_count: int
    total_tokens: int
    total_cost: float
    last_used: str


class GlobalUsageResponse(BaseModel):
    """Global usage statistics"""

    models: Dict[str, int]
    period: str


# ============================================================================
# Endpoints - User Usage
# ============================================================================


@router.get("/stats/{user_address}", response_model=UsageStats)
async def get_user_stats(user_address: str) -> UsageStats:
    """
    Get aggregated usage statistics for a user.

    Parameters:
    - user_address: User's wallet address

    Returns:
    - Total cost, tokens, request count, and credit balance
    """
    try:
        stats = await usage_tracker.get_user_stats(user_address)
        return UsageStats(**stats)
    except Exception as e:
        logger.error(f"Error getting user stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{user_address}", response_model=List[UsageLogEntry])
async def get_usage_history(
    user_address: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> List[UsageLogEntry]:
    """
    Get historical usage logs for a user.

    Parameters:
    - user_address: User's wallet address
    - limit: Number of records to return (max 500)
    - offset: Pagination offset

    Returns:
    - List of usage log entries
    """
    try:
        logs = await usage_tracker.get_history(user_address, limit, offset)
        return [
            UsageLogEntry(
                id=log["id"],
                model=log["model"],
                input_tokens=log["input_tokens"],
                output_tokens=log["output_tokens"],
                cost=log["cost"],
                timestamp=log["timestamp"],
            )
            for log in logs
        ]
    except Exception as e:
        logger.error(f"Error getting usage history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chart/{user_address}", response_model=List[UsageChartEntry])
async def get_chart_data(
    user_address: str, days: int = Query(30, ge=1, le=365)
) -> List[UsageChartEntry]:
    """
    Get daily usage data for charts.

    Parameters:
    - user_address: User's wallet address
    - days: Number of days to retrieve (max 365)

    Returns:
    - Daily usage data for charting
    """
    try:
        data = await usage_tracker.get_chart_data(user_address, days)
        return [
            UsageChartEntry(
                date=entry["date"],
                cost=entry["cost"],
                tokens=entry["tokens"],
                requests=entry["requests"],
            )
            for entry in data
        ]
    except Exception as e:
        logger.error(f"Error getting chart data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/{user_address}", response_model=List[ModelUsageEntry])
async def get_last_used_models(
    user_address: str,
    timeframe: str = Query("all", pattern="^(24h|7d|30d|all)$"),
    limit: int = Query(50, ge=1, le=200),
) -> List[ModelUsageEntry]:
    """
    Get last used models with aggregated metrics.

    Parameters:
    - user_address: User's wallet address
    - timeframe: Time filter (24h, 7d, 30d, all)
    - limit: Number of models to return

    Returns:
    - Model usage statistics
    """
    try:
        models = await usage_tracker.get_last_used_models(
            user_address, timeframe, limit
        )
        return [
            ModelUsageEntry(
                model=m["model"],
                request_count=m["request_count"],
                total_tokens=m["total_tokens"],
                total_cost=m["total_cost"],
                last_used=m["last_used"],
            )
            for m in models
        ]
    except Exception as e:
        logger.error(f"Error getting model usage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Endpoints - Global Analytics
# ============================================================================


@router.get("/global/weekly", response_model=GlobalUsageResponse)
async def get_global_weekly() -> GlobalUsageResponse:
    """
    Get global usage statistics for the last 7 days.

    Returns:
    - Total tokens used per model across all users
    """
    try:
        usage = await usage_tracker.get_global_weekly_usage()
        return GlobalUsageResponse(models=usage, period="7d")
    except Exception as e:
        logger.error(f"Error getting global usage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Endpoints - Manual Logging (for testing/integration)
# ============================================================================


class LogUsageRequest(BaseModel):
    """Request to log usage"""

    user_address: str = Field(..., min_length=3, max_length=256)
    model: str = Field(..., min_length=1, max_length=256)
    input_tokens: int = Field(..., ge=0)
    output_tokens: int = Field(..., ge=0)
    cost: float = Field(..., ge=0.0)
    session_id: Optional[str] = None


@router.post("/log")
async def log_usage(request: LogUsageRequest) -> Dict[str, str]:
    """
    Manually log AI usage (for testing or external integration).

    Request Body:
    - user_address: User's wallet address
    - model: Model ID used
    - input_tokens: Number of input tokens
    - output_tokens: Number of output tokens
    - cost: Total cost in USD
    - session_id: Optional session identifier

    Returns:
    - Success message
    """
    try:
        await usage_tracker.log_usage(
            user_address=request.user_address,
            model=request.model,
            input_tokens=request.input_tokens,
            output_tokens=request.output_tokens,
            cost=request.cost,
            session_id=request.session_id,
        )
        return {"status": "success", "message": "Usage logged successfully"}
    except Exception as e:
        logger.error(f"Error logging usage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Endpoints - Health & Info
# ============================================================================


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check for usage tracking service"""
    return {"status": "healthy", "service": "usage-tracker", "database": "sqlite"}
