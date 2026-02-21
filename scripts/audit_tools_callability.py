"""
Audit tool callability for both runtime tools and legacy wrappers.

Goal:
- Ensure every exported tool function can be imported and invoked.
- Surface broken polymorphic wrappers early (missing symbol, wrong signature).

Usage:
  backend/.venv/Scripts/python.exe scripts/audit_tools_callability.py
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


MODULES: Tuple[str, ...] = (
    # Runtime modules
    "agent.Tools",
    "agent.Tools.trade_execution",
    "agent.Tools.data.market",
    "agent.Tools.data.analysis",
    "agent.Tools.data.analytics",
    "agent.Tools.data.web",
    "agent.Tools.data.memory",
    "agent.Tools.data.knowledge",
    "agent.Tools.data.research",
    "agent.Tools.data.trade",
    "agent.Tools.data.tradingview",
    "agent.Tools.tradingview.actions",
    "agent.Tools.tradingview.verify",
    "agent.Tools.tradingview.nav.actions",
    "agent.Tools.tradingview.drawing.actions",
    # Legacy compatibility wrappers
    "agent.src.tools.legacy.trade_execution",
    "agent.src.tools.legacy.data.market",
    "agent.src.tools.legacy.data.analysis",
    "agent.src.tools.legacy.data.analytics",
    "agent.src.tools.legacy.data.web",
    "agent.src.tools.legacy.data.memory",
    "agent.src.tools.legacy.data.knowledge",
    "agent.src.tools.legacy.data.research",
    "agent.src.tools.legacy.data.trade",
    "agent.src.tools.legacy.data.tradingview",
    "agent.src.tools.legacy.tradingview.actions",
    "agent.src.tools.legacy.tradingview.verify",
    "agent.src.tools.legacy.tradingview.command_client",
    "agent.src.tools.legacy.tradingview.nav.actions",
    "agent.src.tools.legacy.tradingview.drawing.actions",
)


def _pick_exports(module: Any) -> Iterable[str]:
    names = getattr(module, "__all__", None)
    if names:
        out: List[str] = []
        for name in [str(n) for n in names]:
            obj = getattr(module, name, None)
            if inspect.iscoroutinefunction(obj):
                out.append(name)
        return out

    out = []
    for name in dir(module):
        if name.startswith("_"):
            continue
        obj = getattr(module, name, None)
        if (
            inspect.iscoroutinefunction(obj)
            and getattr(obj, "__module__", "") == module.__name__
        ):
            out.append(name)
    return out


def _value_for_param(name: str, default: Any) -> Any:
    if default is not inspect._empty:
        return default

    lower = name.lower()
    mapping: Dict[str, Any] = {
        "symbol": "BTC-USD",
        "target_symbol": "ETH-USD",
        "target_source": "hyperliquid",
        "name": "RSI",
        "query": "btc market update",
        "text": "memory smoke test",
        "message": "smoke message",
        "mode": "quality",
        "source": "news",
        "category": "market",
        "timeframe": "1H",
        "asset_type": "crypto",
        "user_id": "0x1234567890abcdef1234567890abcdef12345678",
        "user_address": "0x1234567890abcdef1234567890abcdef12345678",
        "session": "london",
        "tool": "trend_line",
        "order_id": "ord-smoke-1",
        "side": "buy",
        "action": "focus_chart",
        "order_type": "market",
        "trigger_condition": "ABOVE",
        "caption": "smoke",
        "axis": "time",
        "direction": "left",
        "state": "click",
        "key": "Escape",
        "timeout_sec": 0.1,
        "poll_interval_sec": 0.05,
        "top_k": 2,
        "lookback": 7,
        "limit": 5,
        "amount_usd": 10.0,
        "leverage": 2,
        "entry": 100.0,
        "price": 100.0,
        "sl": 95.0,
        "tp": 110.0,
        "tp2": 112.0,
        "tp3": 115.0,
        "trailing_sl": 98.0,
        "validation": 103.0,
        "invalidation": 97.0,
        "gp": 103.0,
        "gl": 97.0,
        "x": 10,
        "y": 10,
        "from_right": 1,
        "active": True,
        "relative": False,
        "write_txn_id": "smoke",
        "force_overlay": True,
        "keep_volume": False,
    }
    if lower in mapping:
        return mapping[lower]
    if lower in {"tool_states", "inputs", "params", "metadata", "style"}:
        return {}
    if lower == "points":
        return [{"x": 1, "y": 100.0}, {"x": 2, "y": 101.0}]
    if lower == "messages":
        return [{"role": "user", "content": "smoke"}]
    if lower in {"include_depth", "is_limit"}:
        return False
    if lower in {"size_pct"}:
        return 1.0
    if lower in {"amount", "x_from_right"}:
        return "small"
    if lower in {"args", "kwargs"}:
        return {}
    return "smoke"


def _build_kwargs(fn: Callable[..., Any]) -> Dict[str, Any]:
    sig = inspect.signature(fn)
    kwargs: Dict[str, Any] = {}
    for name, param in sig.parameters.items():
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        kwargs[name] = _value_for_param(name, param.default)
    # Safety: avoid real execution paths.
    if "tool_states" in sig.parameters:
        state = kwargs.get("tool_states")
        if not isinstance(state, dict):
            state = {}
        state.setdefault("execution", False)
        state.setdefault("policy_mode", "advice_only")
        kwargs["tool_states"] = state
    return kwargs


async def _invoke_signature_only(fn: Callable[..., Any], kwargs: Dict[str, Any]) -> Any:
    # Signature smoke-check only: build coroutine object without executing body.
    result = fn(**kwargs)
    if not inspect.isawaitable(result):
        raise TypeError("Expected awaitable from async tool function.")
    closer = getattr(result, "close", None)
    if callable(closer):
        closer()
    return {"callable": True}


async def _invoke_runtime(
    fn: Callable[..., Any], kwargs: Dict[str, Any], timeout_sec: float
) -> Any:
    result = fn(**kwargs)
    if not inspect.isawaitable(result):
        raise TypeError("Expected awaitable from async tool function.")
    return await asyncio.wait_for(result, timeout=timeout_sec)


async def run_audit(timeout_sec: float, mode: str) -> Dict[str, Any]:
    records: List[Dict[str, Any]] = []
    for module_name in MODULES:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            records.append(
                {
                    "module": module_name,
                    "name": "*import*",
                    "status": "failed",
                    "error": str(exc),
                    "elapsed_ms": 0.0,
                }
            )
            continue

        for name in _pick_exports(module):
            fn = getattr(module, name, None)
            if not callable(fn):
                continue
            kwargs = _build_kwargs(fn)
            started = time.perf_counter()
            try:
                if mode == "runtime":
                    _ = await _invoke_runtime(fn, kwargs, timeout_sec=timeout_sec)
                else:
                    _ = await _invoke_signature_only(fn, kwargs)
                status = "ok"
                error = ""
            except Exception as exc:
                status = "failed"
                error = str(exc)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            records.append(
                {
                    "module": module_name,
                    "name": name,
                    "status": status,
                    "error": error,
                    "elapsed_ms": round(elapsed_ms, 2),
                }
            )

    total = len(records)
    failed = [r for r in records if r["status"] != "ok"]
    return {
        "summary": {
            "total": total,
            "ok": total - len(failed),
            "failed": len(failed),
            "pass_rate_pct": round(((total - len(failed)) / total * 100.0), 2)
            if total
            else 0.0,
        },
        "failed": failed,
        "records": records,
    }


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Audit tools callability.")
    parser.add_argument("--timeout-sec", type=float, default=8.0)
    parser.add_argument(
        "--mode",
        choices=("signature", "runtime"),
        default="signature",
        help="signature: verify call signatures only; runtime: execute tool bodies.",
    )
    parser.add_argument("--json-out", type=str, default="")
    args = parser.parse_args()

    result = await run_audit(
        timeout_sec=max(0.5, float(args.timeout_sec)),
        mode=str(args.mode),
    )
    summary = result["summary"]
    print(
        f"Tool callability: total={summary['total']} ok={summary['ok']} "
        f"failed={summary['failed']} pass_rate={summary['pass_rate_pct']}%"
    )
    if result["failed"]:
        print("Failed entries:")
        for item in result["failed"]:
            print(f"- {item['module']}::{item['name']} -> {item['error'][:240]}")

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"JSON report written: {out_path}")

    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
