"""
Exchange Markets & Symbol Registry API
=======================================
Endpoints:
  GET /markets/                          – all markets across all exchanges (replaces mock)
  GET /markets/exchanges                 – exchange metadata + status
  GET /markets/symbols                   – symbol registry (from symbol_registry.json)
  GET /markets/symbols/{symbol}          – single symbol info
  GET /markets/canonical/{symbol}        – which connector is canonical for symbol
  POST /markets/canonical/{symbol}/override  – admin: override canonical source (Redis)
  DELETE /markets/canonical/{symbol}/override – admin: clear override
  GET /markets/symbols/refresh           – hot-reload registry from disk
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


def _clean_symbol(symbol: str) -> str:
    raw = str(symbol or "").strip().upper().replace("/", "-").replace("_", "-")
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    return raw


def _normalize_pair_symbol(symbol: str, default_quote: str = "USD") -> str:
    cleaned = _clean_symbol(symbol)
    if not cleaned:
        return cleaned
    compact = cleaned.replace("-", "")

    if cleaned.endswith("-PERP"):
        return f"{cleaned[:-5]}-{default_quote}"
    if cleaned.endswith("-LIGHTER"):
        return f"{cleaned[:-8]}-{default_quote}"
    if "-" in cleaned:
        parts = [p for p in cleaned.split("-") if p]
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}"

    for quote in ("USDC", "USDT", "USD"):
        if compact.endswith(quote) and len(compact) > len(quote):
            return f"{compact[:-len(quote)]}-{quote}"

    return f"{cleaned}-{default_quote}"


def _pair_from_record(record: Dict[str, Any], default_quote: str = "USD") -> str:
    base = _clean_symbol(record.get("from", "")).split("-")[0]
    quote = _clean_symbol(record.get("to", "")).split("-")[0]
    if base:
        q = quote or default_quote
        if q in {"PERP", "LIGHTER"}:
            q = default_quote
        return f"{base}-{q}"
    return _normalize_pair_symbol(record.get("symbol", ""), default_quote=default_quote)

# ── Symbol registry cache ─────────────────────────────────────────────────────
_SYMBOL_REGISTRY_CONFIG: Optional[Dict] = None

# Resolve path: env var (Docker) → relative from repo root → relative from file
_REGISTRY_PATH = (
    os.environ.get("SYMBOL_REGISTRY_PATH")
    or next(
        (p for p in [
            os.path.normpath(os.path.join(os.path.dirname(__file__), "../contracts/config/symbol_registry.json")),
            os.path.normpath(os.path.join(os.path.dirname(__file__), "../../../../contracts/config/symbol_registry.json")),
            os.path.normpath(os.path.join(os.path.dirname(__file__), "../../../contracts/config/symbol_registry.json")),
            "/app/contracts/config/symbol_registry.json",
        ] if os.path.exists(p)),
        "/app/contracts/config/symbol_registry.json"
    )
)

def _load_symbol_registry() -> Dict:
    global _SYMBOL_REGISTRY_CONFIG
    if _SYMBOL_REGISTRY_CONFIG is not None:
        return _SYMBOL_REGISTRY_CONFIG
    try:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            _SYMBOL_REGISTRY_CONFIG = json.load(f)
    except Exception as e:
        logger.warning(f"[markets] Could not load symbol_registry.json: {e}")
        _SYMBOL_REGISTRY_CONFIG = {"symbols": [], "exchange_metadata": {}}
    return _SYMBOL_REGISTRY_CONFIG


# ── Lazy client getters ───────────────────────────────────────────────────────
from services.client_registry import get_exchange_client as _get_client


# ── Per-exchange fetchers ─────────────────────────────────────────────────────
async def _fetch_exchange(name: str) -> List[Dict[str, Any]]:
    try:
        if name == "hyperliquid":
            from Hyperliquid.http_client import http_client
            from services.canonical_source_registry import canonical_registry
            raw_data = await http_client.get_meta_and_asset_ctxs()
            if not raw_data or len(raw_data) < 2:
                return []
            
            universe = raw_data[0].get("universe", [])
            ctxs = raw_data[1]
            
            results = []
            for i, asset_info in enumerate(universe):
                if i < len(ctxs):
                    coin = asset_info["name"]
                    ctx = ctxs[i]
                    sym = f"{coin}-USD"
                    try:
                        price = float(ctx.get("midPx") or ctx.get("markPx") or 0)
                    except Exception:
                        price = 0.0
                    results.append({
                        "symbol": sym,
                        "from": coin,
                        "to": "USD",
                        "price": price,
                        "source": "hyperliquid",
                        "canonical": canonical_registry.is_canonical_source(coin, "hyperliquid"),
                        "category": canonical_registry.get_category_sync(sym),
                        "sub_category": canonical_registry.get_subcategory_sync(sym)
                    })
            return results

        if name == "ostium":
            from Ostium.api_client import OstiumAPIClient
            from services.canonical_source_registry import canonical_registry
            client = OstiumAPIClient()
            raw = await client.get_latest_prices()
            if not raw or not isinstance(raw, list):
                return []
            return [
                {"symbol": f"{item.get('from')}-{item.get('to', 'USD')}",
                 "from": item.get("from"), "to": item.get("to", "USD"),
                 "price": float(item.get("mid", 0)),
                  "source": "ostium", 
                  "canonical": canonical_registry.is_canonical_source(item.get("from"), "ostium"),
                  "category": canonical_registry.get_category_sync(f"{item.get('from')}"),
                  "sub_category": canonical_registry.get_subcategory_sync(f"{item.get('from')}")}
                for item in raw if item.get("from")
            ]

        client = _get_client(name)
        if client and hasattr(client, "get_markets"):
            from services.canonical_source_registry import canonical_registry
            raw = await client.get_markets() or []
            enriched = []
            for m in raw:
                sym = _pair_from_record(m, default_quote="USDT" if name == "aster" else "USD")
                base = m.get("from") or (sym.split("-")[0] if "-" in sym else sym)
                m["symbol"] = sym
                if not m.get("category"):
                    m["category"] = canonical_registry.get_category_sync(base)
                if not m.get("sub_category"):
                    m["sub_category"] = canonical_registry.get_subcategory_sync(base)
                if not m.get("sub_category"):
                    m["sub_category"] = canonical_registry.get_subcategory_sync(base)
                # Always expose connector key as source for frontend routing consistency.
                m["source"] = name
                m["canonical"] = canonical_registry.is_canonical_source(base, name)
                enriched.append(m)
            return enriched

    except Exception as e:
        logger.warning(f"[markets] {name} fetch failed: {e}")
    return []


ALL_EXCHANGES = ["hyperliquid", "ostium", "avantis", "aster", "lighter", "vest"]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/")
async def get_markets(
    exchange: Optional[str] = Query(None, description="Filter by exchange name (hyperliquid, ostium, avantis, aster, lighter, vest)"),
    canonical_only: bool = Query(False, description="Only return canonical price source entries"),
):
    """
    Aggregate live market data from all supported exchanges.
    Replaces the old mock endpoint with real data.
    """
    targets = [exchange.lower()] if exchange else ALL_EXCHANGES
    if exchange and exchange.lower() not in ALL_EXCHANGES:
        raise HTTPException(404, f"Unknown exchange: {exchange}")

    results = await asyncio.gather(*[_fetch_exchange(e) for e in targets], return_exceptions=True)

    combined: List[Dict[str, Any]] = []
    for name, result in zip(targets, results):
        if isinstance(result, Exception):
            logger.warning(f"[markets] {name} error: {result}")
            continue
        combined.extend(result or [])

    if canonical_only:
        try:
            from services.canonical_source_registry import canonical_registry
            combined = [
                m for m in combined
                if canonical_registry.is_canonical_source(
                    m.get("from", m.get("symbol", "").split("-")[0]),
                    m.get("source", "")
                )
            ]
        except Exception:
            pass

    # Enrich with live 24h stats from the shared price cache (populated by WS pollers)
    try:
        from services.price_cache import latest_prices as _lp
        for m in combined:
            sym = m.get("symbol", "")
            cached = _lp.get(sym, {})
            if not cached:
                continue
            # Only fill in missing/zero fields from cache
            stat_fields = {
                "price":              "price",
                "change_24h":         "change_24h",
                "change_percent_24h": "change_percent_24h",
                "high_24h":           "high_24h",
                "low_24h":            "low_24h",
                "volume_24h":         "volume_24h",
                "openInterest":       "openInterest",
                "funding":            "funding",
                "markPrice":          "markPrice",
                "sub_category":       "sub_category",
            }
            for m_field, c_field in stat_fields.items():
                if c_field in cached:
                    cur = m.get(m_field)
                    if cur is None or cur == 0:
                        m[m_field] = cached[c_field]
    except Exception as e:
        logger.debug(f"[markets] price cache enrich skipped: {e}")

    return {
        "markets": combined,
        "count": len(combined),
        "exchanges_queried": targets,
    }


@router.get("/exchanges")
async def get_exchanges():
    """List all supported exchanges with chain and connector metadata."""
    cfg = _load_symbol_registry()
    return {"exchanges": cfg.get("exchange_metadata", {})}


@router.get("/symbols")
async def get_symbols(
    exchange: Optional[str] = Query(None, description="Filter by exchange"),
    canonical_only: bool = Query(True, description="Only canonical entries"),
):
    """
    Return symbol registry from symbol_registry.json.
    Update websocket/contracts/config/symbol_registry.json then call /markets/symbols/refresh.
    """
    cfg = _load_symbol_registry()
    symbols = cfg.get("symbols", [])
    if exchange:
        symbols = [s for s in symbols if s.get("exchange", "").lower() == exchange.lower()]
    if canonical_only:
        symbols = [s for s in symbols if s.get("canonical", False)]
    return {
        "symbols": symbols,
        "count": len(symbols),
        "generated_at": cfg.get("_generated_at", "unknown"),
    }


@router.get("/symbols/refresh")
async def refresh_symbols():
    """Hot-reload symbol_registry.json from disk (no restart needed)."""
    global _SYMBOL_REGISTRY_CONFIG
    _SYMBOL_REGISTRY_CONFIG = None
    cfg = _load_symbol_registry()
    try:
        from services.canonical_source_registry import canonical_registry
        canonical_registry.reload_from_config()
    except Exception:
        pass
    return {
        "status": "reloaded",
        "symbol_count": len(cfg.get("symbols", [])),
        "generated_at": cfg.get("_generated_at", "unknown"),
    }


@router.get("/symbols/{symbol}")
async def get_symbol(symbol: str):
    """Get registry entries for a specific symbol."""
    cfg = _load_symbol_registry()
    upper = _clean_symbol(symbol)
    query_pair = _normalize_pair_symbol(upper)
    query_base = query_pair.split("-")[0] if query_pair else upper.split("-")[0]

    matches = [
        s for s in cfg.get("symbols", [])
        if _clean_symbol(s.get("tradingSymbol", "")) == upper
        or _clean_symbol(s.get("chainlinkSymbol", "")) == query_pair
    ]

    if not matches and query_base:
        matches = [
            s for s in cfg.get("symbols", [])
            if _clean_symbol(s.get("chainlinkSymbol", "")).split("-")[0] == query_base
        ]
        canonical_matches = [s for s in matches if s.get("canonical", False)]
        if canonical_matches:
            matches = canonical_matches

    if not matches:
        raise HTTPException(404, f"Symbol '{symbol}' not found. Update symbol_registry.json and refresh /markets/symbols/refresh.")
    try:
        from services.canonical_source_registry import canonical_registry
        canonical = canonical_registry.get_canonical_source_sync(query_pair or symbol)
    except Exception:
        canonical = "unknown"
    return {"symbol": query_pair or upper, "entries": matches, "canonical_connector": canonical}


@router.get("/canonical/{symbol}")
async def get_canonical(symbol: str):
    """Which exchange connector is the canonical price/chart source for this symbol?"""
    try:
        from services.canonical_source_registry import canonical_registry
        canonical = await canonical_registry.get_canonical_source(symbol)
        return {"symbol": symbol.upper(), "canonical_connector": canonical}
    except Exception as e:
        raise HTTPException(500, str(e))


class OverrideRequest(BaseModel):
    connector: str


@router.post("/canonical/{symbol}/override")
async def set_canonical_override(symbol: str, body: OverrideRequest):
    """Admin: override canonical connector at runtime (stored in Redis, survives hot-reload)."""
    try:
        from services.canonical_source_registry import canonical_registry
        await canonical_registry.set_override(symbol, body.connector)
        return {"status": "ok", "symbol": symbol.upper(), "canonical_connector": body.connector}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/canonical/{symbol}/override")
async def clear_canonical_override(symbol: str):
    """Admin: remove override — reverts to config file / heuristic."""
    try:
        from services.canonical_source_registry import canonical_registry
        await canonical_registry.clear_override(symbol)
        return {"status": "ok", "symbol": symbol.upper(), "message": "Override cleared"}
    except Exception as e:
        raise HTTPException(500, str(e))
