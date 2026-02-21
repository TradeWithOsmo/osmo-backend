import asyncio
import inspect
import json
import time
from typing import Any, Dict

from Core.agent_brain import AgentBrain
from Core.tool_registry import build_tool_registry

WALLET = "0x" + "1" * 40


def sample_value(name: str, default: Any = inspect._empty) -> Any:
    if default is not inspect._empty:
        return default
    key = str(name or "").strip().lower()
    now = int(time.time())
    mapping: Dict[str, Any] = {
        "symbol": "BTC-USD",
        "symbols": ["BTC-USD", "ETH-USD"],
        "target_symbol": "ETH-USD",
        "target_source": "hyperliquid",
        "timeframe": "1H",
        "lookback": 7,
        "limit": 7,
        "asset_type": "crypto",
        "query": "bitcoin market",
        "mode": "quality",
        "source": "news",
        "name": "RSI",
        "text": "audit memory",
        "category": "notes",
        "metadata": {"source": "audit"},
        "user_address": WALLET,
        "user_id": WALLET,
        "session": "ASIA",
        "tool": "trend_line",
        "id": "audit_draw_1",
        "message": "audit",
        "side": "buy",
        "amount_usd": 10.0,
        "leverage": 2,
        "order_type": "market",
        "entry": 65000.0,
        "entry_price": 65000.0,
        "price": 65000.0,
        "stop_price": 64000.0,
        "sl": 64000.0,
        "tp": 67000.0,
        "tp2": 67500.0,
        "tp3": 68000.0,
        "gp": 65500.0,
        "gl": 64500.0,
        "validation": 65500.0,
        "invalidation": 64500.0,
        "from_right": 1,
        "x": 100,
        "y": 100,
        "axis": "time",
        "direction": "right",
        "amount": "small",
        "active": True,
        "state": "click",
        "key": "Escape",
        "relative": False,
        "force_overlay": True,
        "keep_volume": False,
        "min_size_usd": 100000,
        "top_k": 3,
        "poll_interval_sec": 0.2,
        "timeout_sec": 3.0,
        "write_txn_id": "audit",
        "style": {"color": "#2962FF", "linewidth": 2},
        "inputs": {"length": 14},
    }
    if key in mapping:
        return mapping[key]
    if key == "points":
        return [
            {"time": now - 3600, "price": 65000.0},
            {"time": now, "price": 66000.0},
        ]
    if key in {"tool_states", "params"}:
        return {}
    return "audit"


def build_kwargs(fn: Any) -> Dict[str, Any]:
    sig = inspect.signature(fn)
    kwargs: Dict[str, Any] = {}
    for pname, p in sig.parameters.items():
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        value = sample_value(pname, p.default)
        # Important: don't send explicit None for optional fields;
        # parser will coerce against declared type and may fail on None.
        if value is None and p.default is None:
            continue
        kwargs[pname] = value
    return kwargs


async def maybe_prepare(brain: AgentBrain, tool_name: str, kwargs: Dict[str, Any]) -> None:
    if tool_name in {"remove_indicator", "verify_indicator_present"}:
        prep = {"symbol": kwargs.get("symbol", "BTC-USD"), "name": kwargs.get("name", "RSI")}
        await brain._execute_tool_call(name="add_indicator", arguments=prep)
    if tool_name == "update_drawing":
        draw_args = {
            "symbol": kwargs.get("symbol", "BTC-USD"),
            "tool": "trend_line",
            "points": kwargs.get("points") or sample_value("points"),
            "id": kwargs.get("id", "audit_draw_1"),
            "text": "prep",
        }
        await brain._execute_tool_call(name="draw", arguments=draw_args)


async def run() -> Dict[str, Any]:
    registry = build_tool_registry()
    tools = sorted(registry.keys())
    records = []

    for tool_name in tools:
        brain = AgentBrain(
            model_id="anthropic/claude-3.5-sonnet",
            tool_states={
                "write": True,
                "execution": True,
                "policy_mode": "advice_only",
                "memory_enabled": True,
                "web_observation_enabled": True,
                "market_symbol": "BTC-USD",
                "market_timeframe": "1H",
            },
            user_context={"user_address": WALLET},
        )
        spec = brain._tool_registry.get(tool_name)
        if not isinstance(spec, dict):
            records.append({"tool": tool_name, "ok": False, "error": "missing spec"})
            continue

        try:
            fn = brain._get_tool_callable(tool_name, spec)
            kwargs = build_kwargs(fn)
            await maybe_prepare(brain, tool_name, kwargs)
            started = time.perf_counter()
            result = await brain._execute_tool_call(name=tool_name, arguments=kwargs)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            records.append(
                {
                    "tool": tool_name,
                    "ok": bool(result.get("ok")),
                    "error_type": result.get("error_type", ""),
                    "error": str(result.get("error") or "")[:320],
                    "elapsed_ms": elapsed_ms,
                }
            )
        except Exception as exc:
            records.append(
                {
                    "tool": tool_name,
                    "ok": False,
                    "error_type": "exception",
                    "error": str(exc)[:320],
                    "elapsed_ms": 0,
                }
            )

    failed = [r for r in records if not r["ok"]]
    return {
        "summary": {
            "total": len(records),
            "ok": len(records) - len(failed),
            "failed": len(failed),
            "pass_rate_pct": round((len(records) - len(failed)) * 100.0 / len(records), 2) if records else 0.0,
        },
        "failed": failed,
        "records": records,
    }


if __name__ == "__main__":
    out = asyncio.run(run())
    print(json.dumps(out, ensure_ascii=False))
