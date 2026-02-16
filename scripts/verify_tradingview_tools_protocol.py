"""
Lightweight TradingView write-tools verifier (no browser).

Goals:
- Verify backend endpoints are wired correctly.
- Verify TradingView write tools can execute end-to-end through the command loop:
  tool -> /api/connectors/tradingview/commands -> pending queue -> result report -> tool strict verification.
- Cover polymorphism:
  - indicator aliases -> canonical names
  - draw tool aliases -> canonical tools
  - setup_trade gp/gl vs validation/invalidation
  - set_symbol target_source inference

This does NOT verify real chart UI rendering (requires Playwright).
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
import uvicorn


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class ToolCallResult:
    ok: bool
    name: str
    detail: str


class FrontendSimulator:
    """
    Simulates the frontend TradingView command executor:
    - polls pending commands
    - emits deterministic 'success' evidence that matches tool expected_state checks
    """

    def __init__(self, base_url: str, symbol: str):
        self.base_url = base_url.rstrip("/")
        self.current_symbol = symbol
        self.current_timeframe = "1H"
        # Track active indicator names (TradingView study names).
        self.active_indicators: List[str] = ["Volume"]
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0) as client:
            # Poll current chart symbol, but update when set_symbol is executed.
            while not self._stop.is_set():
                try:
                    encoded_symbol = urllib.parse.quote(self.current_symbol, safe="")
                    resp = await client.get(f"/api/connectors/tradingview/commands/{encoded_symbol}")
                except Exception:
                    await asyncio.sleep(0.05)
                    continue

                if resp.status_code != 200:
                    await asyncio.sleep(0.05)
                    continue

                commands = resp.json()
                if not isinstance(commands, list) or not commands:
                    await asyncio.sleep(0.05)
                    continue

                for cmd in commands:
                    await self._handle_one(client, cmd)
                # Keep indicator cache alive.
                await self._post_indicators(client)

    async def _handle_one(self, client: httpx.AsyncClient, cmd: Dict[str, Any]) -> None:
        cmd_id = str(cmd.get("command_id") or "").strip()
        action = str(cmd.get("action") or "").strip()
        params = cmd.get("params") if isinstance(cmd.get("params"), dict) else {}

        evidence: Dict[str, Any] = {}
        if action == "set_timeframe":
            evidence = {"applied_symbol": cmd.get("symbol"), "applied_timeframe": params.get("timeframe")}
            tf = params.get("timeframe")
            if tf:
                self.current_timeframe = str(tf)
        elif action == "add_indicator":
            evidence = {"applied_symbol": cmd.get("symbol"), "applied_indicator": params.get("name")}
            name = str(params.get("name") or "").strip()
            if name and name not in self.active_indicators:
                self.active_indicators.append(name)
        elif action in {"remove_indicator", "clear_indicators"}:
            evidence = {"applied_symbol": cmd.get("symbol")}
            if action == "clear_indicators":
                keep_volume = bool(params.get("keep_volume") or params.get("keepVolume"))
                self.active_indicators = ["Volume"] if keep_volume else []
            else:
                name = str(params.get("name") or "").strip()
                self.active_indicators = [x for x in self.active_indicators if str(x) != name]
        elif action == "set_symbol":
            evidence = {"applied_symbol": params.get("symbol")}
            target = str(params.get("symbol") or "").strip()
            if target:
                self.current_symbol = target
        elif action == "setup_trade":
            # Mirror key fields used by strict verification.
            evidence = {
                "symbol": cmd.get("symbol"),
                "side": params.get("side"),
            }
            if params.get("validation") is not None:
                evidence["validation"] = params.get("validation")
            if params.get("invalidation") is not None:
                evidence["invalidation"] = params.get("invalidation")
        elif action == "draw_shape":
            evidence = {
                "symbol": cmd.get("symbol"),
                # Tools expect "drawing_id" when id is provided.
                "drawing_id": params.get("id"),
            }
            did = str(params.get("id") or "").strip()
            if did and did not in getattr(self, "drawing_tags", []):
                self.drawing_tags = getattr(self, "drawing_tags", [])
                self.drawing_tags.append(did)
        elif action == "update_drawing":
            evidence = {"symbol": cmd.get("symbol"), "drawing_id": params.get("id")}
        elif action == "clear_drawings":
            evidence = {"symbol": cmd.get("symbol"), "drawings_cleared": True}
            self.drawing_tags = []
        else:
            evidence = {"symbol": cmd.get("symbol")}

        payload = {
            "command_id": cmd_id,
            "status": "success",
            "result": evidence,
            "error": None,
        }
        await client.post("/api/connectors/tradingview/commands/result", json=payload)
        await self._post_indicators(client)

    async def _post_indicators(self, client: httpx.AsyncClient) -> None:
        # Minimal indicators payload. Values aren't needed for verification, just names list.
        payload = {
            "symbol": self.current_symbol,
            "timeframe": self.current_timeframe,
            "indicators": {},
            "active_indicators": list(self.active_indicators),
            "drawing_tags": list(getattr(self, "drawing_tags", [])),
            "timestamp": int(time.time() * 1000),
        }
        try:
            await client.post("/api/connectors/tradingview/indicators", json=payload)
        except Exception:
            pass


async def _wait_health(base_url: str, timeout_sec: float = 10.0) -> None:
    deadline = time.time() + timeout_sec
    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.time() < deadline:
            try:
                resp = await client.get(f"{base_url}/healthz")
                if resp.status_code == 200:
                    return
            except Exception:
                pass
            await asyncio.sleep(0.1)
    raise RuntimeError(f"Health check timed out for {base_url}")


async def _call_tool(client: httpx.AsyncClient, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    resp = await client.post(path, json=payload)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Tool response not dict for {path}: {data!r}")
    return data


def _assert_ok(result: Dict[str, Any], label: str) -> ToolCallResult:
    if result.get("error"):
        return ToolCallResult(False, label, f"error={result.get('error')}")
    if result.get("state_verified") is not True:
        ver = result.get("verification")
        return ToolCallResult(False, label, f"state_verified=false verification={ver}")
    return ToolCallResult(True, label, "ok")


async def main() -> int:
    # When running as a script, Python only adds this script's directory to sys.path.
    # Ensure the backend root is importable so `import websocket.*` works.
    backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)

    port = _pick_free_port()
    host = "127.0.0.1"
    base_url = f"http://{host}:{port}"

    # Ensure tool command client points to this server.
    os.environ["CONNECTORS_API_URL"] = f"{base_url}/api/connectors"

    # Import after env var is set (CONNECTORS_API_URL is read at import time).
    from websocket.e2e_main import app  # noqa: WPS433 (runtime import is intentional)

    config = uvicorn.Config(app=app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config=config)

    server_task = asyncio.create_task(server.serve())
    try:
        await _wait_health(base_url)

        symbol = "ETH-USD"
        sim = FrontendSimulator(base_url=base_url, symbol=symbol)
        sim_task = asyncio.create_task(sim.run())

        results: List[ToolCallResult] = []
        async with httpx.AsyncClient(base_url=base_url, timeout=20.0) as client:
            # Basic: set_timeframe + clear_indicators (covers timeframe normalization and keep_volume param).
            tf = await _call_tool(
                client,
                "/api/e2e/tools/tradingview/set_timeframe",
                {"symbol": symbol, "timeframe": "1H"},
            )
            results.append(_assert_ok(tf, "set_timeframe:1H"))

            # Verify we have a live cache for symbol+timeframe.
            v0 = await _call_tool(
                client,
                "/api/e2e/tools/tradingview/verify_state",
                {"symbol": symbol, "timeframe": "1H", "timeout_sec": 2.0},
            )
            if v0.get("verified") is True:
                results.append(ToolCallResult(True, "verify_state:baseline", "ok"))
            else:
                results.append(ToolCallResult(False, "verify_state:baseline", v0.get("error") or "not verified"))

            clr = await _call_tool(
                client,
                "/api/e2e/tools/tradingview/clear_indicators",
                {"symbol": symbol, "keep_volume": True},
            )
            results.append(_assert_ok(clr, "clear_indicators:keep_volume"))

            # Indicator aliases polymorphism (covers alias -> canonical name mapping).
            aliases_resp = await client.get("/api/e2e/tools/tradingview/indicator_aliases")
            aliases_resp.raise_for_status()
            alias_map = (aliases_resp.json() or {}).get("alias_map", {})
            if not isinstance(alias_map, dict) or not alias_map:
                raise RuntimeError("indicator_aliases returned empty alias_map")

            # Human-like flow: BTC -> add -> verify -> get -> remove; then switch to ETH and repeat quickly.
            for active_symbol in ["BTC-USD", "ETH-USD"]:
                if active_symbol != symbol:
                    sw = await _call_tool(
                        client,
                        "/api/e2e/tools/tradingview/set_symbol",
                        {"symbol": symbol, "target_symbol": active_symbol, "target_source": None},
                    )
                    results.append(_assert_ok(sw, f"set_symbol:{active_symbol}"))
                    symbol = active_symbol

                # Pick one canonical alias to simulate operator action.
                for alias in ["RSI", "MACD", "BB"]:
                    r1 = await _call_tool(
                        client,
                        "/api/e2e/tools/tradingview/add_indicator",
                        {"symbol": symbol, "name": alias, "inputs": {}, "force_overlay": True},
                    )
                    results.append(_assert_ok(r1, f"add_indicator_flow:{symbol}:{alias}"))

                    # Generic verification tool (covers indicator presence + symbol/timeframe cache exists).
                    v = await _call_tool(
                        client,
                        "/api/e2e/tools/tradingview/verify_state",
                        {
                            "symbol": symbol,
                            "timeframe": "1H",
                            "require_indicators": [alias_map.get(alias, alias)],
                            "timeout_sec": 2.0,
                        },
                    )
                    if v.get("verified") is True:
                        results.append(ToolCallResult(True, f"verify_state_indicator:{symbol}:{alias}", "ok"))
                    else:
                        results.append(ToolCallResult(False, f"verify_state_indicator:{symbol}:{alias}", v.get("error") or "not verified"))

                    r2 = await _call_tool(
                        client,
                        "/api/e2e/tools/tradingview/remove_indicator",
                        {"symbol": symbol, "name": alias},
                    )
                    results.append(_assert_ok(r2, f"remove_indicator_flow:{symbol}:{alias}"))

            # Full alias coverage (add/remove) for correctness.
            for alias, canonical in alias_map.items():
                r1 = await _call_tool(
                    client,
                    "/api/e2e/tools/tradingview/add_indicator",
                    {"symbol": symbol, "name": str(alias), "inputs": {}, "force_overlay": True},
                )
                results.append(_assert_ok(r1, f"add_indicator:{alias}->{canonical}"))

                r2 = await _call_tool(
                    client,
                    "/api/e2e/tools/tradingview/remove_indicator",
                    {"symbol": symbol, "name": str(alias)},
                )
                results.append(_assert_ok(r2, f"remove_indicator:{alias}->{canonical}"))

            # Draw tools polymorphism (covers all aliases).
            tools_resp = await client.get("/api/e2e/tools/tradingview/draw_tools")
            tools_resp.raise_for_status()
            draw_payload = tools_resp.json() or {}
            aliases = draw_payload.get("aliases", [])
            if not isinstance(aliases, list) or not aliases:
                raise RuntimeError("draw_tools returned empty aliases list")

            base_ts = int(time.time())
            p1 = {"time": base_ts - 3600, "price": 100.0}
            p2 = {"time": base_ts, "price": 110.0}

            for tool in aliases:
                tool_name = str(tool)
                draw_id = f"e2e_{tool_name}"
                r = await _call_tool(
                    client,
                    "/api/e2e/tools/tradingview/draw",
                    {"symbol": symbol, "tool": tool_name, "points": [p1, p2], "style": {"color": "#2962FF"}, "text": tool_name, "id": draw_id},
                )
                results.append(_assert_ok(r, f"draw:{tool_name}"))

                u = await _call_tool(
                    client,
                    "/api/e2e/tools/tradingview/update_drawing",
                    {"symbol": symbol, "id": draw_id, "points": [p1, {"time": base_ts, "price": 120.0}], "style": {"color": "#FF9800"}, "text": f"upd:{tool_name}"},
                )
                results.append(_assert_ok(u, f"update_drawing:{tool_name}"))

            c = await _call_tool(client, "/api/e2e/tools/tradingview/clear_drawings", {"symbol": symbol})
            results.append(_assert_ok(c, "clear_drawings"))

            # setup_trade polymorphism: gp/gl and validation/invalidation.
            st1 = await _call_tool(
                client,
                "/api/e2e/tools/tradingview/setup_trade",
                {"symbol": symbol, "side": "long", "entry": 100.0, "sl": 90.0, "tp": 120.0, "gp": 111.0, "gl": 95.0},
            )
            results.append(_assert_ok(st1, "setup_trade:gp_gl"))
            st2 = await _call_tool(
                client,
                "/api/e2e/tools/tradingview/setup_trade",
                {"symbol": symbol, "side": "short", "entry": 100.0, "sl": 110.0, "tp": 80.0, "validation": 99.0, "invalidation": 105.0},
            )
            results.append(_assert_ok(st2, "setup_trade:validation_invalidation"))

            # set_symbol polymorphism: inferred target_source.
            for target_symbol, expect_source in [
                ("BTC-USD", "hyperliquid"),
                ("XAU-USD", "ostium"),
                ("USD-CHF", "ostium"),
            ]:
                r = await _call_tool(
                    client,
                    "/api/e2e/tools/tradingview/set_symbol",
                    {"symbol": symbol, "target_symbol": target_symbol, "target_source": None},
                )
                results.append(_assert_ok(r, f"set_symbol:{target_symbol}"))
                actual_source = (((r.get("command") or {}).get("params") or {}).get("target_source") or "").strip().lower()
                if actual_source != expect_source:
                    results.append(ToolCallResult(False, f"set_symbol_source:{target_symbol}", f"expected={expect_source} actual={actual_source or 'EMPTY'}"))
                else:
                    results.append(ToolCallResult(True, f"set_symbol_source:{target_symbol}", "ok"))
                # Human behavior: once symbol is switched, subsequent commands target the new active symbol.
                symbol = target_symbol

            # Other write tools: add_price_alert + mark_trading_session.
            al = await _call_tool(
                client,
                "/api/e2e/tools/tradingview/add_price_alert",
                {"symbol": symbol, "price": 123.45, "message": "e2e"},
            )
            results.append(_assert_ok(al, "add_price_alert"))

            va = await _call_tool(
                client,
                "/api/e2e/tools/tradingview/verify_state",
                {"symbol": symbol, "timeframe": "1H", "require_drawings": ["alert_123"], "timeout_sec": 2.0},
            )
            if va.get("verified") is True:
                results.append(ToolCallResult(True, "verify_state:price_alert", "ok"))
            else:
                results.append(ToolCallResult(False, "verify_state:price_alert", va.get("error") or "not verified"))

            ms = await _call_tool(
                client,
                "/api/e2e/tools/tradingview/mark_session",
                {"symbol": symbol, "session": "ASIA"},
            )
            results.append(_assert_ok(ms, "mark_session:ASIA"))

            vs = await _call_tool(
                client,
                "/api/e2e/tools/tradingview/verify_state",
                {"symbol": symbol, "timeframe": "1H", "require_drawings": ["session_asia"], "timeout_sec": 2.0},
            )
            if vs.get("verified") is True:
                results.append(ToolCallResult(True, "verify_state:mark_session", "ok"))
            else:
                results.append(ToolCallResult(False, "verify_state:mark_session", vs.get("error") or "not verified"))

        sim.stop()
        await asyncio.wait_for(sim_task, timeout=2.0)

        failed = [r for r in results if not r.ok]
        total = len(results)
        ok = total - len(failed)

        # Print a small markdown summary.
        print(f"\nTradingView write-tools protocol check: {ok}/{total} OK\n")
        print("| Check | Status | Detail |")
        print("|---|---:|---|")
        for r in results:
            status = "OK" if r.ok else "FAIL"
            print(f"| {r.name} | {status} | {r.detail} |")

        return 0 if not failed else 1
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=5.0)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
