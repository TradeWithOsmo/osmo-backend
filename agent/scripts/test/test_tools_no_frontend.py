#!/usr/bin/env python
"""
Test all agent tools that do NOT require a frontend (TradingView/browser).

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

def _ok(name: str, detail: str, ms: float) -> None:
    results.append({"name": name, "status": "PASS", "detail": detail, "ms": ms})
    print(f"  {GREEN}PASS{RESET}  {name:<45} {detail[:60]}  ({ms:.0f}ms)")

def _fail(name: str, detail: str, ms: float) -> None:
    results.append({"name": name, "status": "FAIL", "detail": detail, "ms": ms})
    print(f"  {RED}FAIL{RESET}  {name:<45} {detail[:60]}  ({ms:.0f}ms)")

def _skip(name: str, reason: str) -> None:
    results.append({"name": name, "status": "SKIP", "detail": reason, "ms": 0})
    print(f"  {YELLOW}SKIP{RESET}  {name:<45} {reason}")

async def run(name: str, coro, *, expect_key: str | None = None) -> Any:
    t0 = time.perf_counter()
    try:
        result = await coro
        ms = (time.perf_counter() - t0) * 1000
        if isinstance(result, dict) and "error" in result:
            _fail(name, str(result["error"])[:80], ms)
        elif expect_key and (not isinstance(result, dict) or expect_key not in result):
            _fail(name, f"missing key '{expect_key}' in {list(result.keys()) if isinstance(result, dict) else type(result)}", ms)
        else:
            summary = str(result)[:60] if not isinstance(result, dict) else str(list(result.keys()))
            _ok(name, summary, ms)
        return result
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        _fail(name, f"{type(exc).__name__}: {exc}"[:80], ms)
        return None


# -- imports -------------------------------------------------------------------
try:
    from agent.Tools.data.market import (
        get_price, get_funding_rate,
        get_ticker_stats, get_chainlink_price, get_high_low_levels,
    )
    from agent.Tools.data.analysis import (
        get_technical_analysis, get_indicators, get_technical_summary,
    )
    from agent.Tools.data.web import search_news, search_sentiment, search_web_hybrid
    from agent.Tools.data.memory import add_memory, search_memory, get_recent_history
    from agent.Tools.data.research import research_market, compare_markets, scan_market_overview
    from agent.Tools.data.trade import get_positions
    from agent.Tools.data.tradingview import get_active_indicators
except ImportError:
    from Tools.data.market import (
        get_price, get_funding_rate,
        get_ticker_stats, get_chainlink_price, get_high_low_levels,
    )
    from Tools.data.analysis import (
        get_technical_analysis, get_indicators, get_technical_summary,
    )
    from Tools.data.web import search_news, search_sentiment, search_web_hybrid
    from Tools.data.memory import add_memory, search_memory, get_recent_history
    from Tools.data.research import research_market, compare_markets, scan_market_overview
    from Tools.data.trade import get_positions
    from Tools.data.tradingview import get_active_indicators


# -- test suites ---------------------------------------------------------------

async def test_market() -> None:
    print("\n" + "-"*60)
    print("MARKET DATA — Hyperliquid (crypto)")
    print('-'*60)
    await run("get_price BTC  [hyperliquid]", get_price("BTC"),                       expect_key="price")
    await run("get_price ETH  [hyperliquid]", get_price("ETH",  exchange="hyperliquid"), expect_key="price")
    await run("get_price SOL  [hyperliquid]", get_price("SOL",  exchange="hyperliquid"), expect_key="price")
    await run("get_price ARB  [hyperliquid]", get_price("ARB",  exchange="hyperliquid"), expect_key="price")
    await run("get_price DOGE [hyperliquid]", get_price("DOGE", exchange="hyperliquid"), expect_key="price")
    await run("get_funding_rate BTC",         get_funding_rate("BTC"))
    await run("get_ticker_stats BTC",         get_ticker_stats("BTC"))
    await run("get_high_low_levels BTC 4H",   get_high_low_levels("BTC", "4H"))
    _skip("get_chainlink_price (BTC)", "not exposed in API connector")

    print("\n" + "-"*60)
    print("MARKET DATA — Ostium (RWA: forex, metals, stocks)")
    print('-'*60)
    await run("get_price EURUSD [ostium]",  get_price("EURUSD", exchange="ostium"),  expect_key="price")
    await run("get_price GBPUSD [ostium]",  get_price("GBPUSD", exchange="ostium"),  expect_key="price")
    await run("get_price XAU    [ostium]",  get_price("XAU",    exchange="ostium"),  expect_key="price")
    await run("get_price SPX    [ostium]",  get_price("SPX",    exchange="ostium"),  expect_key="price")
    await run("get_price USDJPY [ostium]",  get_price("USDJPY", exchange="ostium"),  expect_key="price")
    await run("get_funding_rate EURUSD",    get_funding_rate("EURUSD", asset_type="rwa"))
    await run("get_high_low_levels XAU 1D", get_high_low_levels("XAU", "1D", asset_type="rwa"))


async def test_analysis() -> None:
    print(f"\n{'-'*60}")
    print("ANALYSIS")
    print("-"*60)
    await run("get_technical_analysis (BTC 4H)",  get_technical_analysis("BTC", "4H"))
    await run("get_indicators (BTC 4H)",           get_indicators("BTC", "4H"))
    await run("get_technical_summary (BTC 1H)",    get_technical_summary("BTC", "1H"))




async def test_web() -> None:
    print(f"\n{'-'*60}")
    print("WEB / SEARCH  (may be slow)")
    print("-"*60)
    await run("search_news (BTC)",         search_news("BTC latest news"))
    await run("search_sentiment (ETH)",    search_sentiment("ETH"))
    await run("search_web_hybrid (SOL)",   search_web_hybrid("SOL price analysis"))


async def test_memory() -> None:
    print(f"\n{'-'*60}")
    print("MEMORY")
    print("-"*60)
    test_uid = "test_script_user"
    await run("add_memory",         add_memory(test_uid, "BTC analysis: bullish on 4H"))
    await run("search_memory",      search_memory(test_uid, "BTC"))
    await run("get_recent_history", get_recent_history(test_uid))


async def test_research() -> None:
    print(f"\n{'-'*60}")
    print("RESEARCH")
    print("-"*60)
    await run("research_market (BTC)",     research_market("BTC"))
    await run("compare_markets (BTC ETH)", compare_markets(["BTC", "ETH"]))
    await run("scan_market_overview",      scan_market_overview())


async def test_knowledge() -> None:
    print(f"\n{'-'*60}")
    print("KNOWLEDGE BASE")
    print("-"*60)
    pass


async def test_trade_readonly() -> None:
    print(f"\n{'-'*60}")
    print("TRADE (read-only)")
    print("-"*60)
    _skip("get_positions", "requires services module (run inside Docker on VPS)")


async def test_tradingview_readonly() -> None:
    print(f"\n{'-'*60}")
    print("TRADINGVIEW (read-only, no DOM needed)")
    print("-"*60)
    # get_active_indicators reads from backend state, not DOM
    await run("get_active_indicators", get_active_indicators(symbol="BTC"))


# -- summary -------------------------------------------------------------------

def print_summary() -> None:
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    total = passed + failed + skipped

    print(f"\n{'='*60}")
    print(f"  TOTAL: {total}   {GREEN}PASS: {passed}{RESET}   {RED}FAIL: {failed}{RESET}   {YELLOW}SKIP: {skipped}{RESET}")
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

    await test_market()
    await test_analysis()

    await test_web()
    await test_memory()
    await test_research()
    await test_knowledge()
    await test_trade_readonly()
    await test_tradingview_readonly()

    print_summary()
    sys.exit(1 if any(r["status"] == "FAIL" for r in results) else 0)


if __name__ == "__main__":
    asyncio.run(main())
