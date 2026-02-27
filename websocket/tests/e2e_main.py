from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers.e2e_connectors_tradingview import router as e2e_connectors_router
from .routers.e2e_tradingview_tools import router as e2e_tools_router


logger = logging.getLogger(__name__)

app = FastAPI(title="Osmo E2E Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    # Intentionally minimal: routes only for TradingView command loop + E2E tool wrappers.
    # Avoids optional deps (web3, prometheus) and background pollers.
    logger.info("E2E app startup (minimal)")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


app.include_router(e2e_connectors_router, prefix="/api/connectors", tags=["connectors"])
app.include_router(e2e_tools_router)
