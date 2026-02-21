"""
API Routes for Agent Model Management
Provides endpoints for frontend to fetch and manage model selection
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from src.config.models_config import (
    fetch_openrouter_models,
    get_model_config,
    get_models_by_provider,
    get_recommended_models,
    list_available_models,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


# ============================================================================
# Models & Schemas
# ============================================================================


class ModelInfo(BaseModel):
    """Model information"""

    id: str
    name: str
    provider: str
    context_window: Optional[int] = None
    supports_tool_calling: bool = True
    supports_reasoning: bool = True
    pricing: Optional[Dict[str, Any]] = None


class ModelsListResponse(BaseModel):
    """Response with list of models"""

    models: List[ModelInfo]
    count: int
    recommended: Optional[Dict[str, Dict[str, Any]]] = None


class ModelDetailResponse(BaseModel):
    """Detailed model information"""

    model: ModelInfo
    config: Dict[str, Any]


class ModelSelectRequest(BaseModel):
    """Request to select a model"""

    model_id: str
    temperature: float = 0.7
    max_iterations: int = 10


class ModelSelectResponse(BaseModel):
    """Response when model is selected"""

    status: str
    model_id: str
    message: str


# ============================================================================
# Endpoints - Models Management
# ============================================================================


@router.get(
    "/models", response_model=ModelsListResponse, summary="Get available models"
)
async def get_models(
    provider: Optional[str] = Query(None), refresh: Optional[bool] = Query(False)
) -> ModelsListResponse:
    """
    Get all available models with tool calling + reasoning support.

    Query Parameters:
    - provider: Filter by provider (anthropic, openai, google, meta, mistral)
    - refresh: Force refresh models from OpenRouter API

    Returns:
        List of available models with metadata
    """
    try:
        # Fetch models from OpenRouter API
        await fetch_openrouter_models(force_refresh=refresh)

        if provider:
            # Filter by provider
            models_list = get_models_by_provider(provider)
        else:
            # Get all models
            all_ids = list_available_models()
            models_list = []
            for model_id in all_ids:
                config = get_model_config(model_id)
                if config:
                    models_list.append(config)

        # Convert to response format
        models = [
            ModelInfo(
                id=m.get("id"),
                name=m.get("name", m.get("id")),
                provider=m.get("provider", "unknown"),
                context_window=m.get("context_window"),
                supports_tool_calling=m.get("supports_tool_calling", True),
                supports_reasoning=m.get("supports_reasoning", True),
                pricing=m.get("pricing"),
            )
            for m in models_list
        ]

        # Get recommendations (convert to dict with just IDs)
        recommendations = None
        try:
            recommended = get_recommended_models()
            # Convert to dict for response
            recommendations = {
                k: {
                    "id": v.get("id"),
                    "name": v.get("name"),
                    "provider": v.get("provider"),
                }
                for k, v in recommended.items()
                if v
            }
        except Exception:
            pass

        return ModelsListResponse(
            models=models,
            count=len(models),
            recommended=recommendations,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching models: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching models: {str(e)}")


@router.get("/models/recommended")
async def get_recommended():
    """
    Get recommended models for different use cases.

    Returns:
        Dictionary of recommended models by use case
    """
    try:
        # Ensure models are fetched
        await fetch_openrouter_models()

        recommendations = get_recommended_models()
        return {
            "recommended": recommendations,
            "count": len(recommendations),
        }
    except Exception as e:
        logger.error(f"Error getting recommendations: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get(
    "/models/{model_id}",
    response_model=ModelDetailResponse,
    summary="Get model details",
)
async def get_model_details(model_id: str) -> ModelDetailResponse:
    """
    Get detailed information about a specific model.

    Parameters:
    - model_id: The model ID (e.g., 'anthropic/claude-3.5-sonnet')

    Returns:
        Detailed model configuration and metadata
    """
    try:
        # Ensure models are fetched
        await fetch_openrouter_models()

        config = get_model_config(model_id)

        if not config:
            raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

        # Validate model capabilities
        if not config.get("supports_tool_calling"):
            raise HTTPException(
                status_code=400,
                detail=f"Model '{model_id}' doesn't support tool calling",
            )

        if not config.get("supports_reasoning"):
            raise HTTPException(
                status_code=400, detail=f"Model '{model_id}' doesn't support reasoning"
            )

        model_info = ModelInfo(
            id=config.get("id"),
            name=config.get("name", model_id),
            provider=config.get("provider", "unknown"),
            context_window=config.get("context_window"),
            supports_tool_calling=config.get("supports_tool_calling", True),
            supports_reasoning=config.get("supports_reasoning", True),
            pricing=config.get("pricing"),
        )

        return ModelDetailResponse(
            model=model_info,
            config=config,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching model details: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/models/provider/{provider}", response_model=ModelsListResponse)
async def get_provider_models(provider: str) -> ModelsListResponse:
    """
    Get all models from a specific provider.

    Parameters:
    - provider: Provider name (anthropic, openai, google, meta, mistral)

    Returns:
        Models from the specified provider
    """
    try:
        # Ensure models are fetched
        await fetch_openrouter_models()

        models_list = get_models_by_provider(provider)

        if not models_list:
            raise HTTPException(
                status_code=404, detail=f"No models found for provider '{provider}'"
            )

        models = [
            ModelInfo(
                id=m.get("id"),
                name=m.get("name", m.get("id")),
                provider=m.get("provider", provider),
                context_window=m.get("context_window"),
                supports_tool_calling=m.get("supports_tool_calling", True),
                supports_reasoning=m.get("supports_reasoning", True),
                pricing=m.get("pricing"),
            )
            for m in models_list
        ]

        return ModelsListResponse(
            models=models,
            count=len(models),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching provider models: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.post("/models/validate")
async def validate_model(model_id: str = Query(...)):
    """
    Validate if a model supports required capabilities.

    Query Parameters:
    - model_id: The model ID to validate

    Returns:
        Validation result with details
    """
    try:
        # Ensure models are fetched
        await fetch_openrouter_models()

        config = get_model_config(model_id)

        if not config:
            return {
                "valid": False,
                "reason": f"Model '{model_id}' not found",
            }

        reasons = []

        if not config.get("supports_tool_calling"):
            reasons.append("Tool calling not supported")

        if not config.get("supports_reasoning"):
            reasons.append("Reasoning not supported")

        if reasons:
            return {
                "valid": False,
                "reason": "; ".join(reasons),
            }

        return {
            "valid": True,
            "model_id": model_id,
            "name": config.get("name"),
            "provider": config.get("provider"),
        }

    except Exception as e:
        logger.error(f"Error validating model: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ============================================================================
# Endpoints - Providers
# ============================================================================


@router.get("/providers")
async def list_providers():
    """
    Get list of all available providers.

    Returns:
        List of provider names with model counts
    """
    try:
        # Ensure models are fetched
        await fetch_openrouter_models()

        all_ids = list_available_models()
        providers: Dict[str, int] = {}

        for model_id in all_ids:
            config = get_model_config(model_id)
            if config:
                provider = config.get("provider", "unknown")
                providers[provider] = providers.get(provider, 0) + 1

        return {
            "providers": providers,
            "total": len(providers),
        }

    except Exception as e:
        logger.error(f"Error fetching providers: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ============================================================================
# Endpoints - Health & Info
# ============================================================================


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Try to load models to ensure config is working
        await fetch_openrouter_models()
        models = list_available_models()
        return {
            "status": "healthy",
            "available_models": len(models),
            "service": "osmo-agent",
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "service": "osmo-agent",
            },
        )


@router.get("/info")
async def get_agent_info():
    """Get general agent information"""
    try:
        # Ensure models are fetched
        await fetch_openrouter_models()

        all_models = list_available_models()
        providers_dict = {}

        for model_id in all_models:
            config = get_model_config(model_id)
            if config:
                provider = config.get("provider", "unknown")
                if provider not in providers_dict:
                    providers_dict[provider] = []
                providers_dict[provider].append(model_id)

        return {
            "service": "osmo-agent",
            "version": "1.0.0",
            "framework": "LangChain",
            "models": {
                "total": len(all_models),
                "by_provider": {p: len(m) for p, m in providers_dict.items()},
            },
            "capabilities": {
                "tool_calling": True,
                "reasoning": True,
                "streaming": True,
                "async": True,
            },
        }

    except Exception as e:
        logger.error(f"Error getting agent info: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
