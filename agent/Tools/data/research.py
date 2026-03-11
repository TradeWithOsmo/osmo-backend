"""
Multi-Market Research Agent Tool

Researches a symbol across multiple markets (Hyperliquid crypto, Ostium RWA)
to compare prices, spreads, availability, and trading conditions.
Designed to run within the existing agent workflow as a tool.
"""

import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict

try:
    from agent.Tools.http_client import get_http_client
except Exception:
    from backend.agent.Tools.http_client import get_http_client

try:
    from agent.Tools.data.market import (
        get_price,
        get_funding_rate,
        get_high_low_levels,
    )
except Exception:
    from backend.agent.Tools.data.market import (
        get_price,
        get_funding_rate,
        get_high_low_levels,
    )


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class MarketSnapshot:
    """Data snapshot from a single exchange."""
    market: str  # exchange name: "hyperliquid", "ostium", "aster", etc.
    symbol: str
    price: Optional[float] = None
    change_24h: Optional[float] = None
    change_pct_24h: Optional[float] = None
    volume_24h: Optional[float] = None
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None
    funding_rate: Optional[float] = None
    support: Optional[float] = None
    resistance: Optional[float] = None
    rsi: Optional[float] = None
    patterns: Optional[List[str]] = None
    available: bool = False
    error: Optional[str] = None


@dataclass
class ResearchReport:
    """Result of multi-market research for a single symbol."""
    symbol: str
    markets: List[MarketSnapshot] = field(default_factory=list)
    spread_pct: Optional[float] = None
    best_price_market: Optional[str] = None
    summary: str = ""
    warnings: List[str] = field(default_factory=list)


# All supported exchanges on the platform
ALL_EXCHANGES = ["hyperliquid", "ostium", "avantis", "aster", "vest", "orderly", "paradex", "dydx", "aevo"]

# Exchange descriptions for agent context
EXCHANGE_INFO = {
    "hyperliquid": "Crypto perpetuals DEX — BTC, ETH, SOL, ARB, and 200+ altcoin tokens.",
    "ostium":      "Real-World Asset (RWA) DEX — forex pairs (EURUSD, GBPUSD, USDJPY...), metals (XAU, XAG), stock indices (SPX, NDX, DAX) and individual stocks (AAPL, TSLA, NVDA...).",
    "avantis":     "Crypto + RWA perpetuals on Base. Overlaps with Hyperliquid (BTC, ETH, SOL) and some forex/commodity pairs.",
    "aster":       "Crypto perpetuals (USDT-quoted). Covers BTC, ETH, SOL and mid/small-cap tokens.",
    "vest":        "Crypto perpetuals — BTC, ETH, SOL and a selection of altcoins.",
    "orderly":     "Crypto spot and perps — primarily BTC, ETH, SOL and USDC pairs.",
    "paradex":     "Crypto perpetuals on StarkNet — BTC, ETH, SOL and select altcoins.",
    "dydx":        "Crypto perpetuals (dYdX chain) — BTC, ETH, SOL and 50+ tokens.",
    "aevo":        "Crypto options + perpetuals — BTC, ETH, SOL and mid-cap tokens.",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _fetch_market_snapshot(
    symbol: str,
    exchange: str,
    timeframe: str = "1H",
) -> MarketSnapshot:
    """Gather price, levels, and funding for one exchange."""
    snap = MarketSnapshot(market=exchange, symbol=symbol)

    # Determine routing params
    _PRIMARY = {"hyperliquid": "crypto", "ostium": "rwa"}
    if exchange in _PRIMARY:
        price_data = await get_price(symbol, asset_type=_PRIMARY[exchange])
    else:
        price_data = await get_price(symbol, exchange=exchange)

    if isinstance(price_data, dict) and price_data.get("error"):
        snap.error = price_data["error"]
        return snap

    snap.available = True
    snap.price = price_data.get("price")
    snap.change_24h = price_data.get("change_24h")
    snap.change_pct_24h = price_data.get("change_percent_24h")
    snap.volume_24h = price_data.get("volume_24h")
    snap.high_24h = price_data.get("high_24h")
    snap.low_24h = price_data.get("low_24h")

    # Levels + funding (best-effort, only for primary sources)
    asset_type = _PRIMARY.get(exchange)
    if asset_type:
        task_pairs: List[tuple[str, Any]] = [
            (
                "levels",
                get_high_low_levels(
                    symbol, timeframe=timeframe, lookback=7, asset_type=asset_type
                ),
            ),
        ]
        if asset_type == "crypto":
            task_pairs.append(("funding", get_funding_rate(symbol, asset_type=asset_type)))

        labels = [name for name, _ in task_pairs]
        raw_results = await asyncio.gather(
            *[coro for _, coro in task_pairs], return_exceptions=True
        )
        result_map = dict(zip(labels, raw_results))

        levels = result_map.get("levels")
        if isinstance(levels, dict) and levels.get("status") == "ok":
            snap.support = levels.get("support")
            snap.resistance = levels.get("resistance")

        funding = result_map.get("funding")
        if isinstance(funding, dict) and not funding.get("error"):
            snap.funding_rate = funding.get("rate") or funding.get("funding_rate")

    return snap


def _compute_spread(snapshots: List[MarketSnapshot]) -> Optional[float]:
    """Compute percentage price spread across available markets."""
    prices = [s.price for s in snapshots if s.available and s.price is not None]
    if len(prices) < 2:
        return None
    min_p = min(prices)
    max_p = max(prices)
    if min_p <= 0:
        return None
    return round(((max_p - min_p) / min_p) * 100, 4)


def _best_price_market(snapshots: List[MarketSnapshot]) -> Optional[str]:
    """Identify the market with the lowest ask/price (best entry for long)."""
    available = [s for s in snapshots if s.available and s.price is not None]
    if not available:
        return None
    return min(available, key=lambda s: s.price).market  # type: ignore[arg-type]


def _build_summary(symbol: str, snapshots: List[MarketSnapshot], spread_pct: Optional[float]) -> str:
    available = [s for s in snapshots if s.available]
    unavailable = [s for s in snapshots if not s.available]

    lines: List[str] = [f"## Research: {symbol}"]
    lines.append(f"Markets checked: {len(snapshots)} | Available: {len(available)}")

    if not available:
        lines.append("No markets have this symbol listed.")
        return "\n".join(lines)

    for s in available:
        market_label = s.market.capitalize()
        price_str = f"${s.price:,.4f}" if s.price is not None else "N/A"
        lines.append(f"\n### {market_label}")
        lines.append(f"- Price: {price_str}")
        if s.change_pct_24h is not None:
            lines.append(f"- 24h change: {s.change_pct_24h:+.2f}%")
        if s.volume_24h is not None:
            lines.append(f"- 24h volume: ${s.volume_24h:,.0f}")
        if s.support is not None and s.resistance is not None:
            lines.append(f"- Support: ${s.support:,.4f} | Resistance: ${s.resistance:,.4f}")
        if s.funding_rate is not None:
            lines.append(f"- Funding rate: {s.funding_rate}")

    if spread_pct is not None:
        lines.append(f"\n**Cross-market spread: {spread_pct:.4f}%**")

    for s in unavailable:
        lines.append(f"\n_{s.market.capitalize()}: not available ({s.error or 'symbol not found'})_")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------


async def research_market(
    symbol: str,
    timeframe: str = "1H",
    include_depth: bool = False,
) -> Dict[str, Any]:
    """
    Research a symbol across ALL 9 available exchanges.
    Compares prices, spread, and trading conditions.

    Args:
        symbol: Trading symbol to research (e.g. "BTC", "ETH", "EUR-USD", "XAU-USD").
        timeframe: Timeframe for technical analysis (default "1H").
        include_depth: Unused, kept for backwards compatibility.

    Returns:
        Comprehensive multi-market research report with price comparison,
        cross-market spread, technical context, and key levels.
    """
    # Query all 9 exchanges concurrently
    tasks = [
        _fetch_market_snapshot(symbol, exchange=ex, timeframe=timeframe)
        for ex in ALL_EXCHANGES
    ]
    snapshots = await asyncio.gather(*tasks, return_exceptions=True)

    # Handle exceptions gracefully
    results: List[MarketSnapshot] = []
    for snap in snapshots:
        if isinstance(snap, Exception):
            results.append(MarketSnapshot(
                market="unknown",
                symbol=symbol,
                error=str(snap),
            ))
        else:
            results.append(snap)

    spread = _compute_spread(results)
    best_market = _best_price_market(results)
    summary = _build_summary(symbol, results, spread)

    warnings: List[str] = []
    available_count = sum(1 for s in results if s.available)
    if available_count == 0:
        warnings.append(f"Symbol '{symbol}' not found on any market.")
    elif available_count == 1:
        warnings.append("Only available on one market; cross-market comparison not possible.")
    if spread is not None and spread > 0.5:
        warnings.append(f"Significant cross-market spread detected: {spread:.4f}%.")

    report = ResearchReport(
        symbol=symbol,
        markets=results,
        spread_pct=spread,
        best_price_market=best_market,
        summary=summary,
        warnings=warnings,
    )

    return {
        "status": "ok",
        "symbol": symbol,
        "markets_checked": len(results),
        "markets_available": available_count,
        "spread_pct": spread,
        "best_price_market": best_market,
        "summary": summary,
        "warnings": warnings,
        "snapshots": [asdict(s) for s in results],
    }


async def compare_markets(
    symbols: List[str],
    timeframe: str = "1H",
) -> Dict[str, Any]:
    """
    Compare multiple symbols across all available markets simultaneously.
    Useful for scanning opportunities across crypto (Hyperliquid) and RWA (Ostium).

    Args:
        symbols: List of symbols to compare (e.g. ["BTC", "ETH", "XAU-USD"]).
        timeframe: Timeframe for technical analysis (default "1H").

    Returns:
        Combined research report for all requested symbols with
        cross-market price comparisons.
    """
    # Cap at 5 symbols to avoid excessive API calls
    capped_symbols = symbols[:5]

    tasks = [
        research_market(symbol=sym, timeframe=timeframe)
        for sym in capped_symbols
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    reports: List[Dict[str, Any]] = []
    for idx, result in enumerate(raw_results):
        if isinstance(result, Exception):
            reports.append({
                "symbol": capped_symbols[idx],
                "status": "error",
                "error": str(result),
            })
        else:
            reports.append(result)

    # Build aggregate summary
    total_available = sum(
        r.get("markets_available", 0) for r in reports if isinstance(r, dict)
    )
    summaries = [
        r.get("summary", "") for r in reports
        if isinstance(r, dict) and r.get("summary")
    ]

    return {
        "status": "ok",
        "symbols_requested": len(capped_symbols),
        "symbols": capped_symbols,
        "total_markets_available": total_available,
        "reports": reports,
        "combined_summary": "\n\n---\n\n".join(summaries) if summaries else "No data available.",
    }


async def scan_market_overview(
    asset_class: str = "all",
) -> Dict[str, Any]:
    """
    Get a high-level overview of available markets and top movers across all 9 exchanges.

    Args:
        asset_class: "crypto" for crypto exchanges, "rwa" for Ostium only,
                     or "all" for all 9 exchanges.

    Returns:
        Overview of available markets with price data for each exchange.
    """
    try:
        from agent.Config.tools_config import DATA_SOURCES
    except Exception:
        from backend.agent.Config.tools_config import DATA_SOURCES

    connectors_api = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")
    markets_base = connectors_api.replace("/api/connectors", "")
    results: Dict[str, Any] = {"status": "ok", "markets": {}}

    client = await get_http_client(timeout_sec=15.0)

    # Determine which exchanges to scan
    _RWA_EXCHANGES = {"ostium"}
    _CRYPTO_EXCHANGES = set(ALL_EXCHANGES) - _RWA_EXCHANGES
    if asset_class == "crypto":
        exchanges_to_scan = _CRYPTO_EXCHANGES
    elif asset_class == "rwa":
        exchanges_to_scan = _RWA_EXCHANGES
    else:
        exchanges_to_scan = set(ALL_EXCHANGES)

    # Primary sources have dedicated /prices endpoints (faster)
    _PRIMARY_ENDPOINTS = {
        "hyperliquid": f"{connectors_api}/hyperliquid/prices",
        "ostium": f"{connectors_api}/ostium/prices",
    }

    async def _fetch_exchange(ex: str) -> tuple:
        try:
            if ex in _PRIMARY_ENDPOINTS:
                resp = await client.get(_PRIMARY_ENDPOINTS[ex])
            else:
                resp = await client.get(f"{markets_base}/api/markets/", params={"exchange": ex})
            resp.raise_for_status()
            data = resp.json()
            markets = data if isinstance(data, list) else data.get("markets", data.get("data", []))
            sorted_data = sorted(
                markets,
                key=lambda x: abs(float(x.get("volume_24h") or x.get("change_percent_24h") or 0)),
                reverse=True,
            )
            return ex, {
                "total_pairs": len(markets),
                "top_movers": [
                    {
                        "symbol": m.get("symbol"),
                        "price": m.get("price"),
                        "change_24h": m.get("change_percent_24h"),
                        "volume_24h": m.get("volume_24h"),
                    }
                    for m in sorted_data[:10]
                ],
            }
        except Exception as e:
            return ex, {"error": str(e)}

    fetches = await asyncio.gather(
        *[_fetch_exchange(ex) for ex in exchanges_to_scan],
        return_exceptions=True,
    )
    for item in fetches:
        if isinstance(item, Exception):
            continue
        ex_name, ex_data = item
        results["markets"][ex_name] = ex_data

    return results


async def list_symbols(
    search: str = "",
    exchange: str = "all",
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search tradeable symbols and show which exchanges support them.

    Results are grouped by symbol so you can see all exchanges that offer the same asset.
    Use this tool when the user asks:
      - "which exchanges have ETH?" / "show me ETH markets"
      - "where can I trade EURUSD?"
      - "what can I trade on hyperliquid?"
      - "list forex pairs" / "what RWA pairs are available?"
      - "is SOL on dydx?"

    EXCHANGES (9 total):
      crypto perpetuals : hyperliquid, avantis, aster, vest, orderly, paradex, dydx, aevo
      RWA / forex/metals: ostium  (avantis also covers some RWA)

    Args:
        search: Symbol keyword to search, e.g. "ETH", "BTC", "EUR", "XAU".
                Leave empty to list all symbols on the given exchange.
        exchange: Filter to a specific exchange — "hyperliquid", "ostium", "avantis",
                  "aster", "vest", "orderly", "paradex", "dydx", "aevo" — or "all".
                  When search is provided, "all" is the most useful value.
        category: Optional category filter — "Forex", "Metals", "Crypto", "Stocks", "Index".

    Returns grouped results: each unique symbol with the list of exchanges that offer it,
    plus price per exchange. Much more compact than a flat per-row listing.
    """
    try:
        from agent.Config.tools_config import DATA_SOURCES
    except Exception:
        from backend.agent.Config.tools_config import DATA_SOURCES

    connectors_url = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")
    markets_base = connectors_url.replace("/api/connectors", "")

    client = await get_http_client(timeout_sec=15.0)

    exchange_key = exchange.strip().lower()
    if exchange_key not in ALL_EXCHANGES and exchange_key != "all":
        return {
            "error": f"Unknown exchange '{exchange}'. Valid: {', '.join(ALL_EXCHANGES)} or 'all'.",
            "available_exchanges": ALL_EXCHANGES,
        }

    params: Dict[str, Any] = {}
    if exchange_key != "all":
        params["exchange"] = exchange_key

    try:
        resp = await client.get(f"{markets_base}/api/markets/", params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"error": f"Failed to fetch markets: {e}"}

    markets_list = data if isinstance(data, list) else data.get("markets", data.get("data", []))

    # Filter by search — exact match on base asset ("from") or symbol prefix (e.g. "ETH" → "ETH-USD")
    if search:
        kw = search.strip().upper()
        markets_list = [
            m for m in markets_list
            if str(m.get("from", "")).upper() == kw
            or str(m.get("symbol", "")).upper() == kw
            or str(m.get("symbol", "")).upper().startswith(kw + "-")
        ]

    # Filter by category (API uses snake_case "sub_category")
    if category:
        cat_lower = category.lower()
        markets_list = [
            m for m in markets_list
            if cat_lower in str(m.get("sub_category", "") or "").lower()
            or cat_lower in str(m.get("category", "") or "").lower()
        ]

    # Group by base asset — show which exchanges have it and at what price
    grouped: Dict[str, Dict] = {}
    for m in markets_list:
        base = m.get("from") or str(m.get("symbol", "")).split("-")[0]
        sym = m.get("symbol")
        src = m.get("source")
        if not base or not src:
            continue
        key = base.upper()
        if key not in grouped:
            grouped[key] = {
                "symbol": key,
                "category": m.get("category"),
                "subCategory": m.get("sub_category"),
                "exchanges": [],
            }
        grouped[key]["exchanges"].append({
            "exchange": src,
            "pair": sym,
            "price": m.get("price"),
            "max_leverage": m.get("max_leverage"),
        })

    # Compute basis (price spread) for symbols listed on 2+ exchanges
    for entry in grouped.values():
        prices = [
            (e["exchange"], float(e["price"]))
            for e in entry["exchanges"]
            if e["price"] is not None
        ]
        if len(prices) >= 2:
            prices_sorted = sorted(prices, key=lambda x: x[1])
            low_ex, low_px = prices_sorted[0]
            high_ex, high_px = prices_sorted[-1]
            spread = high_px - low_px
            spread_pct = (spread / low_px * 100) if low_px else 0
            entry["basis"] = {
                "lowest":     {"exchange": low_ex,  "price": low_px},
                "highest":    {"exchange": high_ex, "price": high_px},
                "spread":     round(spread, 6),
                "spread_pct": round(spread_pct, 4),
            }

    results = sorted(grouped.values(), key=lambda x: x["symbol"])

    # If listing a specific exchange without search — return full pairs directly (no grouping needed)
    if not search and exchange_key != "all":
        compact = sorted(
            [
                {
                    "symbol": m.get("symbol"),
                    "base": m.get("from"),
                    "price": m.get("price"),
                    "category": m.get("category"),
                    "max_leverage": m.get("max_leverage"),
                }
                for m in markets_list
                if m.get("symbol")
            ],
            key=lambda x: x["symbol"],
        )
        return {
            "exchange": exchange_key,
            "total": len(compact),
            "symbols": compact,
        }

    return {
        "search": search or None,
        "exchange_filter": exchange_key,
        "total_unique_symbols": len(results),
        "results": results,
    }
