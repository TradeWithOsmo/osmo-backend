from __future__ import annotations

import asyncio
import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import httpx


backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)
workspace_root = os.path.abspath(os.path.join(backend_root, ".."))
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)

from agent.Orchestrator.execution_adapter import ExecutionAdapter
from agent.Tools.tradingview.actions import _INDICATOR_NAME_MAP
from agent.Tools.tradingview.drawing.actions import TOOL_ALIAS_MAP


CONNECTORS = "http://localhost:8000/api/connectors"
TOOLS_API = "http://localhost:8000/api/tools"
FRONTEND_TRADE_URL = "http://localhost:5173/trade"
DEFAULT_WALLET = "0x" + "1" * 40


@dataclass
class CaseResult:
    phase: str
    tool: str
    case: str
    ok: bool
    detail: str
    latency_ms: int = 0


def _patch_execution_adapter() -> None:
    async def _ok(**kwargs: Any) -> Dict[str, Any]:
        return {"status": "ok", "args": kwargs}

    ExecutionAdapter.place_order = staticmethod(_ok)  # type: ignore[assignment]
    ExecutionAdapter.get_positions = staticmethod(_ok)  # type: ignore[assignment]
    ExecutionAdapter.adjust_position_tpsl = staticmethod(_ok)  # type: ignore[assignment]
    ExecutionAdapter.adjust_all_positions_tpsl = staticmethod(_ok)  # type: ignore[assignment]
    ExecutionAdapter.close_position = staticmethod(_ok)  # type: ignore[assignment]
    ExecutionAdapter.close_all_positions = staticmethod(_ok)  # type: ignore[assignment]
    ExecutionAdapter.reverse_position = staticmethod(_ok)  # type: ignore[assignment]
    ExecutionAdapter.cancel_order = staticmethod(_ok)  # type: ignore[assignment]


async def _run_full_registry_contract_pytest(results: List[CaseResult]) -> None:
    _patch_execution_adapter()
    cmd = [sys.executable, "-m", "pytest", "backend/agent/Tests/test_tool_functional_contracts.py", "-q"]
    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=workspace_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    elapsed = int((time.perf_counter() - started) * 1000)
    out = (proc.stdout or "").strip().replace("\n", " | ")
    if len(out) > 240:
        out = out[:240] + "..."
    results.append(
        CaseResult(
            phase="registry_contract",
            tool="all_registry_tools",
            case="pytest:test_tool_functional_contracts.py",
            ok=(proc.returncode == 0),
            detail=out or f"exit={proc.returncode}",
            latency_ms=elapsed,
        )
    )


def _now_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


async def _wait_consumer_online(timeout_sec: float = 30.0) -> Dict[str, Any]:
    deadline = time.time() + timeout_sec
    url = f"{CONNECTORS}/tradingview/consumer-status"
    async with httpx.AsyncClient(timeout=6.0) as client:
        while time.time() < deadline:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            if bool(data.get("consumer_online")):
                return data
            await asyncio.sleep(0.5)
    raise RuntimeError(
        "TradingView consumer is offline. Open real browser at "
        f"{FRONTEND_TRADE_URL} and keep it active, then rerun."
    )


def _extract_ok_from_http_payload(payload: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "non-dict response"
    if payload.get("error"):
        return False, str(payload.get("error"))
    status = str(payload.get("status") or "").strip().lower()
    if status in {"error", "failed", "fail"}:
        return False, f"status={status}"
    if payload.get("state_verified") is False:
        return False, "state_verified=false"
    command_result = payload.get("command_result") if isinstance(payload.get("command_result"), dict) else {}
    result_status = str(command_result.get("status") or "").strip().lower()
    if result_status and result_status not in {"success", "ok", "completed", "done"}:
        return False, f"command_result.status={result_status}"
    return True, "ok"


async def _post_tool(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=35.0) as client:
        resp = await client.post(path, json=payload)
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        if not isinstance(data, dict):
            raise RuntimeError(f"Invalid response type for {path}: {type(data).__name__}")
        return data


async def _run_live_browser_tv_phase(results: List[CaseResult], indicator_alias_limit: int = 0) -> None:
    await _wait_consumer_online(timeout_sec=35.0)

    symbol = "BTC"
    base_ts = _now_epoch()

    async def run_http_case(tool: str, case: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        started = time.perf_counter()
        attempts = 0
        last_data: Dict[str, Any] = {}
        ok = False
        detail = "unknown"
        while attempts < 3:
            attempts += 1
            await _wait_consumer_online(timeout_sec=20.0)
            last_data = await _post_tool(path, payload)
            ok, detail = _extract_ok_from_http_payload(last_data)
            if ok:
                break
            retryable_markers = ("http 5", "http 50", "offline", "timeout", "temporar")
            lowered = str(detail).lower()
            if not any(marker in lowered for marker in retryable_markers):
                break
            await asyncio.sleep(0.6)
            detail = f"{detail} (retry {attempts})"
        elapsed = int((time.perf_counter() - started) * 1000)
        results.append(CaseResult("live_browser_tv", tool, case, ok, detail, elapsed))
        return last_data

    # Core flows
    await run_http_case("set_timeframe", "1H", f"{TOOLS_API}/tradingview/set_timeframe", {"symbol": symbol, "timeframe": "1H"})
    await run_http_case("clear_indicators", "keep_volume", f"{TOOLS_API}/tradingview/clear_indicators", {"symbol": symbol, "keep_volume": True})

    indicator_aliases = sorted(_INDICATOR_NAME_MAP.keys())
    if indicator_alias_limit > 0:
        indicator_aliases = indicator_aliases[:indicator_alias_limit]
    for alias in indicator_aliases:
        await run_http_case("add_indicator", f"alias:{alias}", f"{TOOLS_API}/tradingview/add_indicator", {"symbol": symbol, "name": alias, "inputs": {}, "force_overlay": True})
        await run_http_case("remove_indicator", f"alias:{alias}", f"{TOOLS_API}/tradingview/remove_indicator", {"symbol": symbol, "name": alias})

    # Draw polymorphism aliases (stable subset validated on live bridge).
    stable_draw_aliases = sorted(
        {
            "line",
            "trend_line",
            "ray",
            "extended",
            "rect",
            "rectangle",
            "circle",
            "fib_retracement",
            "date_range",
            "long_position",
            "short_position",
            "price_range",
            "arrow",
        }
    )
    for alias in stable_draw_aliases:
        draw_id = f"tv_{alias}_{base_ts}"
        payload = {
            "symbol": symbol,
            "tool": alias,
            "points": [{"time": base_ts - 3600, "price": 90000.0}, {"time": base_ts, "price": 100000.0}],
            "style": {"color": "#2962FF"},
            "text": alias,
            "id": draw_id,
        }
        await run_http_case("draw", f"alias:{alias}", f"{TOOLS_API}/tradingview/draw", payload)
    await run_http_case("clear_drawings", "all", f"{TOOLS_API}/tradingview/clear_drawings", {"symbol": symbol})

    # setup_trade polymorphism
    await run_http_case(
        "setup_trade",
        "gp_gl",
        f"{TOOLS_API}/tradingview/setup_trade",
        {"symbol": symbol, "side": "long", "entry": 100000.0, "sl": 98000.0, "tp": 104000.0, "validation": 101000.0, "invalidation": 99000.0},
    )
    await run_http_case(
        "setup_trade",
        "validation_invalidation",
        f"{TOOLS_API}/tradingview/setup_trade",
        {"symbol": symbol, "side": "short", "entry": 100000.0, "sl": 102000.0, "tp": 96000.0, "validation": 99000.0, "invalidation": 101500.0},
    )

    for target_symbol, expected_source in [("BTC-USD", "hyperliquid"), ("ETH-USD", "hyperliquid")]:
        data = await run_http_case(
            "set_symbol",
            f"target:{target_symbol}",
            f"{TOOLS_API}/tradingview/set_symbol",
            {"symbol": symbol, "target_symbol": target_symbol, "target_source": None},
        )
        actual_source = str((((data.get("command") or {}).get("params") or {}).get("target_source") or "")).strip().lower()
        ok = actual_source == expected_source
        results.append(
            CaseResult(
                phase="live_browser_tv",
                tool="set_symbol",
                case=f"source_infer:{target_symbol}",
                ok=ok,
                detail=f"expected={expected_source} actual={actual_source or 'EMPTY'}",
                latency_ms=0,
            )
        )
        symbol = target_symbol

    await run_http_case("add_price_alert", "basic", f"{TOOLS_API}/tradingview/add_price_alert", {"symbol": symbol, "price": 123.45, "message": "e2e-alert"})
    await run_http_case("mark_trading_session", "ASIA", f"{TOOLS_API}/tradingview/mark_session", {"symbol": symbol, "session": "ASIA"})
    await run_http_case("mark_trading_session", "LONDON", f"{TOOLS_API}/tradingview/mark_session", {"symbol": symbol, "session": "LONDON"})

    # Navigation tools exposed by current /api/tools router
    await run_http_case("focus_chart", "basic", f"{TOOLS_API}/tradingview/focus_chart", {"symbol": symbol})
    await run_http_case("pan", "time_left_small", f"{TOOLS_API}/tradingview/pan", {"symbol": symbol, "axis": "time", "direction": "left", "amount": "small"})
    await run_http_case("zoom", "in_small", f"{TOOLS_API}/tradingview/zoom", {"symbol": symbol, "mode": "in", "amount": "small"})
    await run_http_case("reset_view", "basic", f"{TOOLS_API}/tradingview/reset_view", {"symbol": symbol})
    await run_http_case("get_screenshot", "canvas", f"{TOOLS_API}/tradingview/get_screenshot", {"symbol": symbol})


def _print_results_table(results: List[CaseResult]) -> None:
    total = len(results)
    failed = [x for x in results if not x.ok]
    ok_count = total - len(failed)
    success_rate = (ok_count / total * 100.0) if total else 0.0

    print("\nFull Tools Coverage Report")
    print(f"- total={total}")
    print(f"- ok={ok_count}")
    print(f"- failed={len(failed)}")
    print(f"- success_rate={success_rate:.2f}%")
    print("\n| Phase | Tool | Case | Status | Detail | Latency (ms) |")
    print("|---|---|---|---:|---|---:|")
    for row in results:
        print(
            f"| {row.phase} | {row.tool} | {row.case} | "
            f"{'OK' if row.ok else 'FAIL'} | {row.detail} | {row.latency_ms} |"
        )

    if failed:
        print("\nFailed Cases:")
        for row in failed:
            print(f"- {row.phase}::{row.tool}::{row.case} -> {row.detail}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run full tools coverage with live TradingView browser bridge.")
    parser.add_argument("--skip-registry-contract", action="store_true", help="Skip pytest contract suite.")
    parser.add_argument("--indicator-alias-limit", type=int, default=0, help="Limit indicator alias polymorphism loop for faster runs (0 = all).")
    args = parser.parse_args()

    results: List[CaseResult] = []
    if not args.skip_registry_contract:
        await _run_full_registry_contract_pytest(results)
    await _run_live_browser_tv_phase(results, indicator_alias_limit=max(0, int(args.indicator_alias_limit or 0)))
    _print_results_table(results)
    return 0 if all(x.ok for x in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
