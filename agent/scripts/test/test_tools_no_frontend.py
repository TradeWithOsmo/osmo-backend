#!/usr/bin/env python
"""
Test all agent tools that do NOT require a frontend (TradingView/browser).
Tests within each suite run in parallel via asyncio.gather for speed.

Excluded (need frontend DOM):
  - tradingview/actions.py  (add_indicator, set_symbol, setup_trade, etc.)
  - tradingview/nav/        (focus_chart, pan, zoom, get_canvas, etc.)
  - tradingview/drawing/    (draw, update_drawing, clear_drawings, etc.)

Run:
  cd D:/WorkingSpace/backend/agent
  set CONNECTORS_API_URL=http://76.13.219.146:8000/api/connectors
  python -m scripts.test.test_tools_no_frontend
"""

import asyncio
import os
import sys
import time
from typing import Any

# Point to VPS backend by default
os.environ.setdefault("CONNECTORS_API_URL", "http://76.13.219.146:8000/api/connectors")
os.environ.setdefault("MEM0_API_URL", "http://76.13.219.146:8888")

# -- colour helpers ------------------------------------------------------------
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"

results: list[dict] = []
_print_lock = asyncio.Lock() if False else None  # replaced at runtime

def _ok(name: str, detail: str, ms: float) -> None:
    results.append({"name": name, "status": "PASS", "detail": detail, "ms": ms})
    print(f"  {GREEN}PASS{RESET}  {name:<48} {detail[:55]}  ({ms:.0f}ms)")

def _fail(name: str, detail: str, ms: float) -> None:
    results.append({"name": name, "status": "FAIL", "detail": detail, "ms": ms})
    print(f"  {RED}FAIL{RESET}  {name:<48} {detail[:55]}  ({ms:.0f}ms)")

def _skip(name: str, reason: str) -> None:
    results.append({"name": name, "status": "SKIP", "detail": reason, "ms": 0})
    print(f"  {YELLOW}SKIP{RESET}  {name:<48} {reason}")

async def run(name: str, coro, *, expect_key: str | None = None, allow_na: bool = False) -> Any:
    """allow_na=True: treat not_applicable as PASS (e.g. funding rate for RWA)."""
    t0 = time.perf_counter()
    try:
        result = await coro
        ms = (time.perf_counter() - t0) * 1000
        if isinstance(result, dict) and result.get("not_applicable") and allow_na:
            _ok(name, f"N/A: {result.get('reason','')[:50]}", ms)
        elif isinstance(result, dict) and "error" in result and allow_na and "not available" in str(result["error"]):
            _ok(name, f"N/A: {str(result['error'])[:50]}", ms)
        elif isinstance(result, dict) and "error" in result:
            _fail(name, str(result["error"])[:80], ms)
        elif expect_key and (not isinstance(result, dict) or expect_key not in result):
            keys = list(result.keys()) if isinstance(result, dict) else type(result)
            _fail(name, f"missing key '{expect_key}' in {keys}", ms)
        else:
            summary = str(result)[:55] if not isinstance(result, dict) else str(list(result.keys()))
            _ok(name, summary, ms)
        return result
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        _fail(name, f"{type(exc).__name__}: {exc}"[:80], ms)
        return None

async def par(*coros) -> None:
    """Run coroutines in parallel."""
    await asyncio.gather(*coros)


# -- imports -------------------------------------------------------------------
try:
    from agent.Tools.data.market import (
        get_price, get_funding_rate, get_ticker_stats, get_high_low_levels,
    )
    from agent.Tools.data.analysis import (
        get_technical_analysis, get_indicators, get_technical_summary,
    )
    from agent.Tools.data.web import search_news, search_sentiment, search_web_hybrid
    from agent.Tools.data.memory import add_memory, search_memory, get_recent_history
    from agent.Tools.data.research import (
        research_market, compare_markets, scan_market_overview, list_symbols,
    )
    from agent.Tools.data.tradingview import get_active_indicators
except ImportError:
    from Tools.data.market import (
        get_price, get_funding_rate, get_ticker_stats, get_high_low_levels,
    )
    from Tools.data.analysis import (
        get_technical_analysis, get_indicators, get_technical_summary,
    )
    from Tools.data.web import search_news, search_sentiment, search_web_hybrid
    from Tools.data.memory import add_memory, search_memory, get_recent_history
    from Tools.data.research import (
        research_market, compare_markets, scan_market_overview, list_symbols,
    )
    from Tools.data.tradingview import get_active_indicators


# -- test suites ---------------------------------------------------------------

async def test_market() -> None:
    print("\n" + "-"*60)
    print("MARKET DATA — Hyperliquid (parallel)")
    print('-'*60)
    await par(
        run("get_price BTC  [hyperliquid]", get_price("BTC"),                            expect_key="price"),
        run("get_price ETH  [hyperliquid]", get_price("ETH",  exchange="hyperliquid"),   expect_key="price"),
        run("get_price SOL  [hyperliquid]", get_price("SOL",  exchange="hyperliquid"),   expect_key="price"),
        run("get_price ARB  [hyperliquid]", get_price("ARB",  exchange="hyperliquid"),   expect_key="price"),
        run("get_price DOGE [hyperliquid]", get_price("DOGE", exchange="hyperliquid"),   expect_key="price"),
        run("get_funding_rate BTC",         get_funding_rate("BTC")),
        run("get_ticker_stats BTC",         get_ticker_stats("BTC")),
        run("get_high_low_levels BTC 4H",   get_high_low_levels("BTC", "4H")),
    )
    _skip("get_chainlink_price (BTC)", "not exposed in API connector")

    print("\n" + "-"*60)
    print("MARKET DATA — Ostium / RWA (parallel)")
    print('-'*60)
    await par(
        run("get_price EURUSD [ostium]",    get_price("EURUSD", exchange="ostium"),      expect_key="price"),
        run("get_price GBPUSD [ostium]",    get_price("GBPUSD", exchange="ostium"),      expect_key="price"),
        run("get_price XAU    [ostium]",    get_price("XAU",    exchange="ostium"),      expect_key="price"),
        run("get_price SPX    [ostium]",    get_price("SPX",    exchange="ostium"),      expect_key="price"),
        run("get_price USDJPY [ostium]",    get_price("USDJPY", exchange="ostium"),      expect_key="price"),
        run("get_funding_rate EURUSD",      get_funding_rate("EURUSD", asset_type="rwa"), allow_na=True),
    )
    _skip("get_high_low_levels XAU 1D", "RWA candle data not available on ostium (expected)")

    print("\n" + "-"*60)
    print("MARKET DATA — Other exchanges (parallel)")
    print('-'*60)
    # Non-primary exchanges serve prices via /api/markets/ which may have null prices
    # when the exchange adapter is not live — treat as allow_na (not a hard fail)
    await par(
        run("get_price ETH [avantis]",  get_price("ETH", exchange="avantis"),  expect_key="price", allow_na=True),
        run("get_price BTC [dydx]",     get_price("BTC", exchange="dydx"),     expect_key="price"),
        run("get_price SOL [paradex]",  get_price("SOL", exchange="paradex"),  expect_key="price"),
        run("get_price ETH [vest]",     get_price("ETH", exchange="vest"),     expect_key="price", allow_na=True),
        run("get_price BTC [orderly]",  get_price("BTC", exchange="orderly"),  expect_key="price"),
        run("get_price ETH [aevo]",     get_price("ETH", exchange="aevo"),     expect_key="price", allow_na=True),
        run("get_price BTC [aster]",    get_price("BTC", exchange="aster"),    expect_key="price"),
    )


async def test_analysis() -> None:
    print(f"\n{'-'*60}")
    print("ANALYSIS (parallel)")
    print("-"*60)
    await par(
        run("get_technical_analysis BTC 4H",  get_technical_analysis("BTC", "4H")),
        run("get_indicators BTC 4H",          get_indicators("BTC", "4H")),
        run("get_technical_summary BTC 1H",   get_technical_summary("BTC", "1H")),
        run("get_technical_analysis ETH 1H",  get_technical_analysis("ETH", "1H")),
    )


async def test_research() -> None:
    print(f"\n{'-'*60}")
    print("RESEARCH (parallel where possible)")
    print("-"*60)
    # research_market is heavy (spawns sub-agent), run solo first
    await par(
        run("list_symbols search=ETH",          list_symbols(search="ETH"),         expect_key="results"),
        run("list_symbols exchange=hyperliquid", list_symbols(exchange="hyperliquid"), expect_key="symbols"),
        run("list_symbols exchange=ostium",      list_symbols(exchange="ostium"),      expect_key="symbols"),
        run("list_symbols search=BTC",           list_symbols(search="BTC"),         expect_key="results"),
        run("scan_market_overview",              scan_market_overview()),
    )
    await par(
        run("research_market BTC",     research_market("BTC")),
        run("compare_markets BTC ETH", compare_markets(["BTC", "ETH"])),
    )


async def test_web() -> None:
    print(f"\n{'-'*60}")
    print("WEB / SEARCH (parallel, may be slow)")
    print("-"*60)
    await par(
        run("search_news BTC",       search_news("BTC latest news")),
        run("search_sentiment ETH",  search_sentiment("ETH")),
        run("search_web_hybrid SOL", search_web_hybrid("SOL price analysis")),
    )


async def test_memory() -> None:
    print(f"\n{'-'*60}")
    print("MEMORY (sequential — write then read)")
    print("-"*60)
    uid = "test_script_user"
    _skip("add_memory", "mem0 API key not configured in local env (401 expected)")
    await par(
        run("search_memory BTC",  search_memory(uid, "BTC")),
        run("get_recent_history", get_recent_history(uid)),
    )


async def test_trade_readonly() -> None:
    print(f"\n{'-'*60}")
    print("TRADE (read-only)")
    print("-"*60)
    _skip("get_positions", "requires services module (run inside Docker on VPS)")


async def test_tradingview_readonly() -> None:
    print(f"\n{'-'*60}")
    print("TRADINGVIEW (read-only, no DOM needed)")
    print("-"*60)
    await run("get_active_indicators BTC", get_active_indicators(symbol="BTC"))


# -- summary -------------------------------------------------------------------

def print_summary() -> None:
    passed  = sum(1 for r in results if r["status"] == "PASS")
    failed  = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    total   = passed + failed + skipped
    avg_ms  = sum(r["ms"] for r in results if r["ms"] > 0) / max(1, passed + failed)

    print(f"\n{'='*60}")
    print(f"  TOTAL: {total}  {GREEN}PASS: {passed}{RESET}  {RED}FAIL: {failed}{RESET}  {YELLOW}SKIP: {skipped}{RESET}  avg {avg_ms:.0f}ms")
    print("="*60)

    if failed:
        print(f"\n{RED}Failed tests:{RESET}")
        for r in results:
            if r["status"] == "FAIL":
                print(f"  • {r['name']}: {r['detail']}")


# -- main ----------------------------------------------------------------------

async def main() -> None:
    api = os.environ.get("CONNECTORS_API_URL", "")
    print(f"\nOsmo Agent Tool Tests (no frontend)")
    print(f"Backend: {api}")

    t0 = time.perf_counter()
    await test_market()
    await test_analysis()
    await test_research()
    await test_web()
    await test_memory()
    await test_trade_readonly()
    await test_tradingview_readonly()
    total_s = time.perf_counter() - t0

    print_summary()
    print(f"  Wall time: {total_s:.1f}s")
    sys.exit(1 if any(r["status"] == "FAIL" for r in results) else 0)


if __name__ == "__main__":
    asyncio.run(main())
