from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest
import respx
from httpx import Response

from backend.agent.Orchestrator.tool_registry import get_tool_registry
import backend.agent.Tools.tradingview.verify as tv_verify
from backend.agent.Tools.tradingview.verify import verify_tradingview_state


CONNECTORS = "http://localhost:8000/api/connectors"


def _tv_completed(
    *,
    symbol: str,
    action: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    state = {
        "symbol": symbol,
        "timeframe": params.get("timeframe", "1D"),
    }
    payload: Dict[str, Any] = {
        "message": "ok",
        "state": state,
        "symbol": state["symbol"],
        "timeframe": state["timeframe"],
    }
    if action == "set_symbol":
        payload["applied_symbol"] = params.get("symbol") or symbol
    if action == "set_timeframe":
        payload["applied_timeframe"] = params.get("timeframe") or "1D"
    if action == "add_indicator":
        payload["applied_indicator"] = params.get("name") or ""
    if action == "setup_trade":
        payload["side"] = params.get("side") or ""
        payload["validation"] = params.get("validation", params.get("gp"))
        payload["invalidation"] = params.get("invalidation", params.get("gl"))
    if action in {"draw_shape", "update_drawing"} and params.get("id"):
        payload["drawing_id"] = params.get("id")
    if action == "clear_drawings":
        payload["drawings_cleared"] = True

    return {
        "status": "completed",
        "command": {"command_id": "dummy"},
        "result": {"status": "success", "result": payload},
    }


@pytest.fixture()
def mock_connectors():
    with respx.mock(assert_all_called=False) as router:
        # TradingView command loop
        def _tv_handler(request):
            body = json.loads(request.content.decode("utf-8") or "{}")
            symbol = body.get("symbol") or "BTC/USDT"
            action = body.get("action") or ""
            params = body.get("params") or {}
            return Response(200, json=_tv_completed(symbol=symbol, action=action, params=params))

        router.post(f"{CONNECTORS}/tradingview/commands").mock(side_effect=_tv_handler)
        router.post(f"{CONNECTORS}/tradingview/commands/result").mock(return_value=Response(200, json={"status": "ok"}))
        router.get(f"{CONNECTORS}/tradingview/commands/BTC%2FUSDT").mock(return_value=Response(200, json=[]))
        router.post(f"{CONNECTORS}/tradingview/indicators").mock(return_value=Response(200, json={"status": "stored"}))
        router.get(f"{CONNECTORS}/tradingview/indicators").mock(
            return_value=Response(
                200,
                json={
                    "source": "tradingview",
                    "symbol": "BTC/USDT",
                    "data_type": "indicators",
                    "timestamp": 0,
                    "data": {
                        "timeframe": "1D",
                        "indicators": {},
                        "screenshot": None,
                        "active_indicators": ["Relative Strength Index"],
                    },
                },
            )
        )

        # Market endpoints
        router.get(f"{CONNECTORS}/hyperliquid/prices").mock(
            return_value=Response(
                200,
                json=[
                    {
                        "symbol": "BTC-USD",
                        "price": 100000,
                        "change_24h": 0,
                        "change_percent_24h": 0,
                        "volume_24h": 1,
                        "high_24h": 101000,
                        "low_24h": 99000,
                        "category": "Crypto",
                    }
                ],
            )
        )
        router.get(f"{CONNECTORS}/ostium/prices").mock(
            return_value=Response(
                200,
                json=[
                    {
                        "symbol": "EURUSD",
                        "price": 1.1,
                        "change_24h": 0,
                        "change_percent_24h": 0,
                        "volume_24h": 1,
                        "high_24h": 1.2,
                        "low_24h": 1.0,
                        "category": "Forex",
                    }
                ],
            )
        )
        router.get(url__regex=rf"{CONNECTORS}/candles/.*").mock(
            return_value=Response(
                200,
                json=[
                    {"time": 1, "open": 10, "high": 12, "low": 9, "close": 11},
                    {"time": 2, "open": 11, "high": 13, "low": 10, "close": 12},
                    {"time": 3, "open": 12, "high": 14, "low": 11, "close": 13},
                ],
            )
        )
        router.get(url__regex=rf"{CONNECTORS}/orderbook/.*").mock(
            return_value=Response(200, json={"bids": [[1, 1]], "asks": [[2, 1]]})
        )
        router.get(url__regex=rf"{CONNECTORS}/funding/.*").mock(
            return_value=Response(200, json={"funding_rate": 0.0001})
        )

        # Web search endpoints
        router.get(f"{CONNECTORS}/web_search/search").mock(
            return_value=Response(200, json={"data": {"items": [{"title": "x"}]}})
        )
        router.get(url__regex=rf"{CONNECTORS}/dune/whale_trades/.*").mock(
            return_value=Response(200, json={"data": {"flows": []}})
        )

        # Memory endpoints (fallback if mem0 not available)
        router.post(f"{CONNECTORS}/memory/add").mock(return_value=Response(200, json={"stored": True}))
        router.post(f"{CONNECTORS}/memory/search").mock(return_value=Response(200, json={"data": {"results": []}}))
        router.get(url__regex=rf"{CONNECTORS}/memory/all.*").mock(return_value=Response(200, json={"memories": []}))

        # Analysis endpoint
        router.get(url__regex=rf"{CONNECTORS}/analysis/technical/.*").mock(
            return_value=Response(200, json={"status": "ok"})
        )

        yield router


@pytest.fixture(autouse=True)
def mock_execution_adapter(monkeypatch: pytest.MonkeyPatch):
    from backend.agent.Orchestrator import execution_adapter as ea

    async def _ok(**kwargs):
        return {"status": "ok", "args": kwargs}

    monkeypatch.setattr(ea.ExecutionAdapter, "place_order", staticmethod(_ok), raising=True)
    monkeypatch.setattr(ea.ExecutionAdapter, "get_positions", staticmethod(_ok), raising=True)
    monkeypatch.setattr(ea.ExecutionAdapter, "adjust_position_tpsl", staticmethod(_ok), raising=True)
    monkeypatch.setattr(ea.ExecutionAdapter, "adjust_all_positions_tpsl", staticmethod(_ok), raising=True)
    monkeypatch.setattr(ea.ExecutionAdapter, "close_position", staticmethod(_ok), raising=True)
    monkeypatch.setattr(ea.ExecutionAdapter, "close_all_positions", staticmethod(_ok), raising=True)
    monkeypatch.setattr(ea.ExecutionAdapter, "reverse_position", staticmethod(_ok), raising=True)
    monkeypatch.setattr(ea.ExecutionAdapter, "cancel_order", staticmethod(_ok), raising=True)


@pytest.fixture(autouse=True)
def mock_knowledge(monkeypatch: pytest.MonkeyPatch):
    import backend.agent.Tools.data.knowledge as kb

    def _fake_embedding(_: str, target_dims: Optional[int] = None):
        dims = int(target_dims or 8)
        return [0.01] * dims

    class _Hit:
        def __init__(self):
            self.score = 0.5
            self.payload = {"metadata": {"title": "t", "category": "drawing", "subcategory": ""}, "content": "c", "source": "s"}

    class _FakeQdrant:
        def search(self, **kwargs):
            _ = kwargs
            return [_Hit()]

    monkeypatch.setattr(kb, "_get_embedding", _fake_embedding, raising=True)
    monkeypatch.setattr(kb, "_get_qdrant", lambda: _FakeQdrant(), raising=True)


TOOL_CASES: Dict[str, List[Dict[str, Any]]] = {
    # Market data
    "get_price": [{"symbol": "BTC", "asset_type": "crypto"}],
    "get_candles": [{"symbol": "BTC", "timeframe": "1H", "limit": 3, "asset_type": "crypto"}],
    "get_orderbook": [{"symbol": "BTC", "asset_type": "crypto"}],
    "get_funding_rate": [{"symbol": "BTC", "asset_type": "crypto"}],
    "get_high_low_levels": [{"symbol": "BTC", "timeframe": "1H", "lookback": 2, "limit": 3, "asset_type": "crypto"}],
    "get_ticker_stats": [{"symbol": "BTC", "asset_type": "crypto"}],
    # This tool may be offline depending on web3 deps; contract is "no crash".
    "get_chainlink_price": [{"symbol": "BTC"}],

    # Analysis / patterns (these may return structured values depending on connector; here we just ensure no crash)
    "get_technical_analysis": [{"symbol": "BTC", "timeframe": "1D", "asset_type": "crypto"}],
    "get_patterns": [{"symbol": "BTC", "timeframe": "1D", "asset_type": "crypto"}],
    "get_indicators": [{"symbol": "BTC", "timeframe": "1D", "asset_type": "crypto"}],
    "get_technical_summary": [{"symbol": "BTC", "timeframe": "1D", "asset_type": "crypto"}],

    # Web + onchain
    "search_news": [{"query": "btc", "mode": "quality", "source": "news"}],
    "search_sentiment": [{"symbol": "BTC", "mode": "quality"}],
    "get_whale_activity": [{"symbol": "BTC", "min_size_usd": 100000}],
    "get_token_distribution": [{"symbol": "BTC"}],

    # Research
    "research_market": [{"symbol": "BTC", "timeframe": "1H", "include_depth": False}],
    "compare_markets": [{"symbols": ["BTC", "ETH"], "timeframe": "1H"}],
    "scan_market_overview": [{"asset_class": "all"}],

    # Knowledge + guidance
    "search_knowledge_base": [{"query": "risk management", "category": None, "top_k": 1}],
    "get_drawing_guidance": [{"tool_name": "trendline"}],
    "get_trade_management_guidance": [{"topic": "stop loss"}],
    "get_market_context_guidance": [{}],
    "consult_strategy": [{"question": "best pullback?"}],

    # Memory tools (gated by memory_enabled in runtime, but tool itself can run)
    "add_memory": [{"user_id": "0x" + "1" * 40, "text": "x", "metadata": {}}],
    "search_memory": [{"user_id": "0x" + "1" * 40, "query": "x", "limit": 3}],
    "get_recent_history": [{"user_id": "0x" + "1" * 40, "limit": 5}],

    # TradingView surface + polymorphism (mocked connector)
    "list_supported_indicator_aliases": [{}],
    "list_supported_draw_tools": [{}],
    "get_active_indicators": [{"symbol": "BTC/USDT", "timeframe": "1D"}],
    "add_indicator": [{"symbol": "BTC/USDT", "name": "RSI", "inputs": {}, "force_overlay": True}],
    "verify_indicator_present": [{"symbol": "BTC/USDT", "name": "RSI", "timeframe": "1D", "timeout_sec": 0.0}],
    "verify_tradingview_state": [
        {
            "symbol": "BTC/USDT",
            "timeframe": "1D",
            "require_indicators": ["Relative Strength Index"],
            "require_drawings": [],
            "require_trade_setup": {},
            "timeout_sec": 0.0,
        }
    ],
    "remove_indicator": [{"symbol": "BTC/USDT", "name": "RSI"}],
    "clear_indicators": [{"symbol": "BTC/USDT", "keep_volume": False}],
    "set_timeframe": [{"symbol": "BTC/USDT", "timeframe": "1H"}],
    "set_symbol": [{"symbol": "BTC/USDT", "target_symbol": "ETH/USDT", "target_source": None}],
    "setup_trade": [
        {"symbol": "BTC/USDT", "side": "long", "entry": 1, "sl": 0.9, "tp": 1.1, "gp": 1.05, "gl": 0.95},
        {"symbol": "BTC/USDT", "side": "short", "entry": 1, "sl": 1.1, "tp": 0.9, "validation": 0.95, "invalidation": 1.05},
    ],
    "add_price_alert": [{"symbol": "BTC/USDT", "price": 123.0, "message": "x"}],
    "mark_trading_session": [{"symbol": "BTC/USDT", "session": "LONDON"}],
    "draw": [{"symbol": "BTC/USDT", "tool": "hline", "points": [{"time": 1, "price": 1}], "id": "x"}],
    "update_drawing": [{"symbol": "BTC/USDT", "id": "x", "points": [{"time": 2, "price": 2}], "text": "t"}],
    "clear_drawings": [{"symbol": "BTC/USDT"}],

    # TradingView nav tools (mocked connector; expected_state is empty so only completion matters)
    "focus_chart": [{"symbol": "BTC/USDT"}],
    "ensure_mode": [{"symbol": "BTC/USDT", "mode": "nav"}],
    "mouse_move": [{"symbol": "BTC/USDT", "x": 10, "y": 10, "relative": False}],
    "mouse_press": [{"symbol": "BTC/USDT", "state": "click"}],
    "pan": [{"symbol": "BTC/USDT", "axis": "time", "direction": "left", "amount": "small"}],
    "zoom": [{"symbol": "BTC/USDT", "mode": "in", "amount": "small"}],
    "press_key": [{"symbol": "BTC/USDT", "key": "Escape"}],
    "reset_view": [{"symbol": "BTC/USDT"}],
    "focus_latest": [{"symbol": "BTC/USDT"}],
    "set_crosshair": [{"symbol": "BTC/USDT", "active": True}],
    "move_crosshair": [{"symbol": "BTC/USDT", "axis": "time", "direction": "right", "amount": "small"}],
    "get_canvas": [{"symbol": "BTC/USDT"}],
    "get_box": [{"symbol": "BTC/USDT"}],
    "get_screenshot": [{"symbol": "BTC/USDT"}],
    "get_photo_chart": [{"symbol": "BTC/USDT", "target": "canvas"}],
    "hover_candle": [{"symbol": "BTC/USDT", "from_right": 10, "price_level": None}],
    "inspect_cursor": [{"symbol": "BTC/USDT"}],
    "capture_moment": [{"symbol": "BTC/USDT", "caption": "x"}],

    # Execution tools (stubbed)
    "place_order": [
        {
            "symbol": "BTC-USD",
            "side": "long",
            "amount_usd": 10.0,
            "tool_states": {"user_address": "0x" + "1" * 40, "execution": False},
            "exchange": "simulation",
        }
    ],
    "get_positions": [{"user_address": "0x" + "1" * 40}],
    "adjust_position_tpsl": [{"user_address": "0x" + "1" * 40, "symbol": "BTC-USD", "tp": 1.0}],
    "adjust_all_positions_tpsl": [{"user_address": "0x" + "1" * 40, "tp_pct": 1.0}],
    "close_position": [{"user_address": "0x" + "1" * 40, "symbol": "BTC-USD", "price": None, "size_pct": 1.0}],
    "close_all_positions": [{"user_address": "0x" + "1" * 40}],
    "reverse_position": [{"user_address": "0x" + "1" * 40, "symbol": "BTC-USD"}],
    "cancel_order": [{"user_address": "0x" + "1" * 40, "order_id": "ord_123"}],
}


@pytest.mark.asyncio
async def test_tool_registry_functional_contracts(mock_connectors):
    _ = mock_connectors
    registry = get_tool_registry()
    missing = sorted(set(registry.keys()) - set(TOOL_CASES.keys()))
    assert not missing, "Missing TOOL_CASES for: " + ", ".join(missing)

    for tool_name, tool_fn in registry.items():
        cases = TOOL_CASES[tool_name]
        for args in cases:
            result = await tool_fn(**args)
            # Contract: tool must not crash; errors should be explicit.
            assert isinstance(result, (dict, str, list))
            if isinstance(result, dict):
                assert "traceback" not in result


@pytest.mark.asyncio
async def test_verify_tradingview_state_accepts_indicator_alias_tokens(monkeypatch: pytest.MonkeyPatch):
    payload = {
        "source": "tradingview",
        "symbol": "BTC/USDT",
        "data": {
            "timeframe": "1D",
            "active_indicators": ["Relative Strength Index"],
            "drawing_tags": [],
            "trade_setup": {},
        },
    }

    class _Resp:
        def __init__(self, body):
            self.status_code = 200
            self._body = body
            self.content = b"1"

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    class _Client:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

        async def get(self, url, params=None):
            _ = url, params
            return _Resp(payload)

    monkeypatch.setattr(tv_verify.httpx, "AsyncClient", _Client, raising=True)
    result = await verify_tradingview_state(
        symbol="BTC/USDT",
        timeframe="1D",
        require_indicators=["RSI"],  # alias
        timeout_sec=0.0,
    )
    assert isinstance(result, dict)
    assert result.get("verified") is True


@pytest.mark.asyncio
async def test_verify_tradingview_state_can_assert_indicator_absence(monkeypatch: pytest.MonkeyPatch):
    payload = {
        "source": "tradingview",
        "symbol": "BTC/USDT",
        "data": {
            "timeframe": "1D",
            "active_indicators": ["Relative Strength Index"],
            "drawing_tags": [],
            "trade_setup": {},
        },
    }

    class _Resp:
        def __init__(self, body):
            self.status_code = 200
            self._body = body
            self.content = b"1"

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    class _Client:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

        async def get(self, url, params=None):
            _ = url, params
            return _Resp(payload)

    monkeypatch.setattr(tv_verify.httpx, "AsyncClient", _Client, raising=True)
    result = await verify_tradingview_state(
        symbol="BTC/USDT",
        timeframe="1D",
        forbid_indicators=["RSI"],
        timeout_sec=0.0,
    )
    assert isinstance(result, dict)
    assert result.get("verified") is False
    mismatch = result.get("mismatch") or []
    assert any("indicator_present:rsi" in str(item).lower() for item in mismatch)
