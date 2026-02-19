"""
FastAPI application for Osmo Agent
Provides REST API for chat, model selection, and agent management
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from src.api.routes import router
from src.config.models_config import get_model_config, list_available_models
from src.core import LLMFactory

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app lifecycle - startup and shutdown"""
    # Startup
    logger.info("Starting Osmo Agent API...")
    available_models = list_available_models()
    logger.info(
        f"Loaded {len(available_models)} models with tool calling + reasoning support"
    )

    yield

    # Shutdown
    logger.info("Shutting down Osmo Agent API...")


# Create FastAPI application
app = FastAPI(
    title="Osmo Agent API",
    description="AI Agent API with OpenRouter LLM support and tool calling capabilities",
    version="1.0.0",
    lifespan=lifespan,
)

# Include API routes
app.include_router(router)


# Health check endpoint
@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint"""
    try:
        models = list_available_models()
        return {
            "status": "healthy",
            "available_models": len(models),
            "service": "osmo-agent",
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "service": "osmo-agent",
        }


# Root endpoint
@app.get("/")
async def root() -> Dict[str, str]:
    """Root endpoint with API information"""
    return {
        "service": "Osmo Agent API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info(f"Starting server on {host}:{port}")
    uvicorn.run(
        "src.main:app",
        host=host,
        port=port,
        reload=os.getenv("ENV", "production") == "development",
    )
