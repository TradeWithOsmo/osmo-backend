import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx
import pytest
from fastapi import FastAPI

WS_ROOT = Path(__file__).resolve().parents[2]
if str(WS_ROOT) not in sys.path:
    sys.path.insert(0, str(WS_ROOT))
BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Isolate tests from external auth dependencies (jwt/cryptography).
if "auth.dependencies" not in sys.modules:
    auth_pkg = types.ModuleType("auth")
    deps_mod = types.ModuleType("auth.dependencies")

    async def _default_current_user():
        return {
            "wallet_address": "0x1234567890abcdef1234567890abcdef12345678",
            "sub": "0x1234567890abcdef1234567890abcdef12345678",
        }

    deps_mod.get_current_user = _default_current_user
    auth_pkg.dependencies = deps_mod
    sys.modules["auth"] = auth_pkg
    sys.modules["auth.dependencies"] = deps_mod

from auth.dependencies import get_current_user  # type: ignore
from routers import tools as tools_router_module


def _cases() -> List[Tuple[str, str, Dict[str, Any]]]:
    wallet = "0x1234567890abcdef1234567890abcdef12345678"
    return [
        (
            "POST",
            "/api/tools/trade_execution/place_order",
            {
                "symbol": "BTC-USD",
                "side": "buy",
                "amount_usd": 10.0,
                "tool_states": {"execution": False},
                "exchange": "simulation",
            },
        ),
        (
            "POST",
            "/api/tools/trade_execution/get_positions",
            {"exchange": "simulation"},
        ),
        (
            "POST",
            "/api/tools/trade_execution/close_position",
            {
                "symbol": "BTC-USD",
                "price": 100.0,
                "size_pct": 1.0,
                "exchange": "simulation",
            },
        ),
        ("POST", "/api/tools/trade_execution/close_all_positions", {}),
        (
            "POST",
            "/api/tools/trade_execution/reverse_position",
            {"symbol": "BTC-USD", "exchange": "simulation"},
        ),
        ("POST", "/api/tools/trade_execution/cancel_order", {"order_id": "ord-smoke"}),
        (
            "POST",
            "/api/tools/tradingview/add_indicator",
            {"symbol": "BTC-USD", "name": "RSI", "inputs": {}, "force_overlay": True},
        ),
        (
            "POST",
            "/api/tools/tradingview/remove_indicator",
            {"symbol": "BTC-USD", "name": "RSI"},
        ),
        (
            "POST",
            "/api/tools/tradingview/clear_indicators",
            {"symbol": "BTC-USD", "keep_volume": False},
        ),
        (
            "POST",
            "/api/tools/tradingview/set_timeframe",
            {"symbol": "BTC-USD", "timeframe": "1H"},
        ),
        (
            "POST",
            "/api/tools/tradingview/set_symbol",
            {
                "symbol": "BTC-USD",
                "target_symbol": "ETH-USD",
                "target_source": "hyperliquid",
            },
        ),
        (
            "POST",
            "/api/tools/tradingview/setup_trade",
            {
                "symbol": "BTC-USD",
                "side": "buy",
                "entry": 100.0,
                "sl": 95.0,
                "tp": 110.0,
            },
        ),
        (
            "POST",
            "/api/tools/tradingview/add_price_alert",
            {"symbol": "BTC-USD", "price": 101.0, "message": "alert"},
        ),
        (
            "POST",
            "/api/tools/tradingview/mark_session",
            {"symbol": "BTC-USD", "session": "london"},
        ),
        ("POST", "/api/tools/tradingview/focus_chart", {"symbol": "BTC-USD"}),
        (
            "POST",
            "/api/tools/tradingview/pan",
            {
                "symbol": "BTC-USD",
                "axis": "time",
                "direction": "left",
                "amount": "small",
            },
        ),
        (
            "POST",
            "/api/tools/tradingview/zoom",
            {"symbol": "BTC-USD", "mode": "in", "amount": "small"},
        ),
        ("POST", "/api/tools/tradingview/reset_view", {"symbol": "BTC-USD"}),
        ("POST", "/api/tools/tradingview/get_screenshot", {"symbol": "BTC-USD"}),
        (
            "POST",
            "/api/tools/tradingview/draw",
            {
                "symbol": "BTC-USD",
                "tool": "trend_line",
                "points": [{"x": 1, "y": 100.0}, {"x": 2, "y": 101.0}],
                "style": {},
                "text": "smoke",
            },
        ),
        ("POST", "/api/tools/tradingview/clear_drawings", {"symbol": "BTC-USD"}),
        (
            "POST",
            "/api/tools/data/price",
            {"symbol": "BTC-USD", "asset_type": "crypto"},
        ),
        (
            "POST",
            "/api/tools/data/candles",
            {
                "symbol": "BTC-USD",
                "timeframe": "1H",
                "limit": 50,
                "asset_type": "crypto",
            },
        ),
        (
            "POST",
            "/api/tools/data/levels",
            {
                "symbol": "BTC-USD",
                "timeframe": "1H",
                "lookback": 7,
                "asset_type": "crypto",
            },
        ),
        (
            "POST",
            "/api/tools/research/market",
            {"symbol": "BTC-USD", "timeframe": "1H", "include_depth": False},
        ),
        ("POST", "/api/tools/research/scan", {"asset_class": "all"}),
        (
            "POST",
            "/api/tools/analysis/technical",
            {"symbol": "BTC-USD", "asset_type": "crypto"},
        ),
        (
            "POST",
            "/api/tools/web/search",
            {"query": "btc update", "mode": "quality", "source": "news"},
        ),
        ("POST", "/api/tools/web/sentiment", {"symbol": "BTC-USD", "mode": "quality"}),
        (
            "POST",
            "/api/tools/knowledge/search",
            {"query": "trendline", "category": "drawing", "top_k": 2},
        ),
        (
            "POST",
            "/api/tools/memory/add",
            {"text": "smoke memory", "metadata": {"wallet": wallet}},
        ),
        ("POST", "/api/tools/memory/search", {"query": "smoke", "limit": 5}),
        ("GET", "/api/tools/memory/history?limit=5", {}),
    ]


def _stub_result(name: str):
    async def _stub(*args, **kwargs):
        return {"status": "ok", "tool": name}

    return _stub


@pytest.mark.asyncio
async def test_tools_endpoints_matrix_callable() -> None:
    app = FastAPI()
    app.include_router(tools_router_module.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "wallet_address": "0x1234567890abcdef1234567890abcdef12345678",
        "sub": "0x1234567890abcdef1234567890abcdef12345678",
    }

    # Patch all external tool call targets to pure async stubs.
    names_to_patch = [
        "place_order",
        "get_positions",
        "close_position",
        "close_all_positions",
        "reverse_position",
        "cancel_order",
        "add_indicator",
        "remove_indicator",
        "clear_indicators",
        "set_timeframe",
        "set_symbol",
        "setup_trade",
        "add_price_alert",
        "mark_trading_session",
        "focus_chart",
        "pan",
        "zoom",
        "reset_view",
        "get_screenshot",
        "draw",
        "clear_drawings",
        "get_price",
        "get_candles",
        "get_high_low_levels",
        "research_market",
        "scan_market_overview",
        "get_technical_analysis",
        "search_news",
        "search_sentiment",
        "search_knowledge_base",
        "add_memory",
        "search_memory",
        "get_recent_history",
    ]
    for name in names_to_patch:
        setattr(tools_router_module, name, _stub_result(name))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        for method, path, payload in _cases():
            if method == "GET":
                response = await client.get(path)
            else:
                response = await client.post(path, json=payload)
            assert response.status_code == 200, f"{method} {path} -> {response.text}"
            body = response.json()
            assert body is not None
