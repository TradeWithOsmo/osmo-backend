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
        get_orderbook,
    )
    from agent.Tools.data.analysis import get_technical_analysis
except Exception:
    from backend.agent.Tools.data.market import (
        get_price,
        get_funding_rate,
        get_high_low_levels,
        get_orderbook,
    )
    from backend.agent.Tools.data.analysis import get_technical_analysis


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class MarketSnapshot:
    """Data snapshot from a single market source."""
    market: str  # "hyperliquid" or "ostium"
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _fetch_market_snapshot(
    symbol: str,
    asset_type: str,
    timeframe: str = "1H",
    include_depth: bool = False,
) -> MarketSnapshot:
    """Gather price, technicals, levels, and optionally depth for one market."""
    market_name = "hyperliquid" if asset_type == "crypto" else "ostium"
    snap = MarketSnapshot(market=market_name, symbol=symbol)

    # 1 – Price
    price_data = await get_price(symbol, asset_type=asset_type)
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

    task_pairs: List[tuple[str, Any]] = [
        (
            "technical",
            get_technical_analysis(symbol, timeframe=timeframe, asset_type=asset_type),
        ),
        (
            "levels",
            get_high_low_levels(
                symbol, timeframe=timeframe, lookback=7, asset_type=asset_type
            ),
        ),
    ]
    if asset_type == "crypto":
        task_pairs.append(("funding", get_funding_rate(symbol, asset_type=asset_type)))
        if include_depth:
            task_pairs.append(("depth", get_orderbook(symbol, asset_type=asset_type)))

    labels = [name for name, _ in task_pairs]
    raw_results = await asyncio.gather(
        *[coro for _, coro in task_pairs], return_exceptions=True
    )
    result_map = dict(zip(labels, raw_results))

    ta_data = result_map.get("technical")
    if isinstance(ta_data, dict) and not ta_data.get("error"):
        indicators = ta_data.get("indicators", {})
        snap.rsi = indicators.get("RSI_14")
        snap.patterns = ta_data.get("patterns", [])

    levels = result_map.get("levels")
    if isinstance(levels, dict) and levels.get("status") == "ok":
        snap.support = levels.get("support")
        snap.resistance = levels.get("resistance")

    funding = result_map.get("funding")
    if isinstance(funding, dict) and not funding.get("error"):
        snap.funding_rate = funding.get("rate") or funding.get("funding_rate")

    depth = result_map.get("depth")
    if isinstance(depth, dict) and not depth.get("error"):
        bids = depth.get("bids", [])
        asks = depth.get("asks", [])
        if bids and asks:
            try:
                best_bid = float(bids[0][0])
                best_ask = float(asks[0][0])
                if best_bid > 0:
                    ob_spread = (best_ask - best_bid) / best_bid * 100
                    if ob_spread > 1.0:
                        snap.error = f"Wide spread detected: {ob_spread:.2f}%"
            except Exception:
                pass

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
        if s.rsi is not None:
            lines.append(f"- RSI(14): {s.rsi:.1f}")
        if s.support is not None and s.resistance is not None:
            lines.append(f"- Support: ${s.support:,.4f} | Resistance: ${s.resistance:,.4f}")
        if s.funding_rate is not None:
            lines.append(f"- Funding rate: {s.funding_rate}")
        if s.patterns:
            lines.append(f"- Patterns: {', '.join(s.patterns[:5])}")

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
    Research a symbol across ALL available markets (Hyperliquid + Ostium).
    Compares prices, technicals, levels, and trading conditions.

    Args:
        symbol: Trading symbol to research (e.g. "BTC", "ETH", "EUR-USD", "XAU-USD").
        timeframe: Timeframe for technical analysis (default "1H").
        include_depth: If True, also fetch orderbook depth (crypto only).

    Returns:
        Comprehensive multi-market research report with price comparison,
        cross-market spread, technical context, and key levels.
    """
    # Run both market fetches concurrently
    tasks = [
        _fetch_market_snapshot(symbol, asset_type="crypto", timeframe=timeframe, include_depth=include_depth),
        _fetch_market_snapshot(symbol, asset_type="rwa", timeframe=timeframe, include_depth=include_depth),
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
    Get a high-level overview of available markets and top movers.
    Scans Hyperliquid (crypto) and/or Ostium (RWA) for broad market context.

    Args:
        asset_class: "crypto" for Hyperliquid only, "rwa" for Ostium only,
                     or "all" for both markets.

    Returns:
        Overview of available markets with price data for each.
    """
    try:
        from agent.Config.tools_config import DATA_SOURCES
    except Exception:
        from backend.agent.Config.tools_config import DATA_SOURCES

    connectors_api = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")
    results: Dict[str, Any] = {"status": "ok", "markets": {}}

    client = await get_http_client(timeout_sec=10.0)
    if asset_class in ("crypto", "all"):
        try:
            resp = await client.get(f"{connectors_api}/hyperliquid/prices")
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                # Sort by volume, take top 10
                sorted_data = sorted(
                    data,
                    key=lambda x: float(x.get("volume_24h") or 0),
                    reverse=True,
                )
                results["markets"]["hyperliquid"] = {
                    "total_pairs": len(data),
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
            results["markets"]["hyperliquid"] = {"error": str(e)}

    if asset_class in ("rwa", "all"):
        try:
            resp = await client.get(f"{connectors_api}/ostium/prices")
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                sorted_data = sorted(
                    data,
                    key=lambda x: abs(float(x.get("change_percent_24h") or 0)),
                    reverse=True,
                )
                results["markets"]["ostium"] = {
                    "total_pairs": len(data),
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
            results["markets"]["ostium"] = {"error": str(e)}

    return results
