"""
Icon Resolver API
=================
Resolves icon URLs for market symbols with persistent Redis caching.

Endpoints:
  GET /api/icons?symbols=BTC,ETH,AAPL,EURUSD  – batch resolve icon URLs

Flow:
1. Check Redis for each symbol (30-day TTL)
2. Cache miss → probe fallback sources via HEAD requests
3. Return map: {symbol → {url, source}} or {symbol → {type:"forex", base, quote}}
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)
router = APIRouter()

REDIS_KEY_PREFIX = "icon:"
REDIS_TTL = 30 * 24 * 3600  # 30 days

# ── Forex detection ────────────────────────────────────────────────────────────
FIAT_CURRENCIES = {
    'USD', 'EUR', 'GBP', 'JPY', 'AUD', 'NZD', 'CAD', 'CHF', 'MXN',
    'SGD', 'HKD', 'NOK', 'SEK', 'DKK', 'TRY', 'ZAR', 'BRL', 'CNY',
    'INR', 'KRW', 'TWD', 'HUF', 'CZK', 'PLN', 'THB', 'IDR', 'MYR',
    'PHP', 'RUB', 'UAH', 'COP', 'CLP', 'PEN', 'ARS', 'VND',
}


def detect_forex(symbol: str) -> Optional[Dict[str, str]]:
    parts = symbol.split('-')
    if len(parts) == 2:
        b, q = parts[0].upper(), parts[1].upper()
        if b in FIAT_CURRENCIES and q in FIAT_CURRENCIES:
            return {"type": "forex", "base": b, "quote": q}
    clean = symbol.replace('-', '').upper()
    if len(clean) == 6:
        b, q = clean[:3], clean[3:]
        if b in FIAT_CURRENCIES and q in FIAT_CURRENCIES:
            return {"type": "forex", "base": b, "quote": q}
    return None


# ── Icon source lists ──────────────────────────────────────────────────────────
def get_sources(sym: str) -> List[str]:
    """Return ordered list of candidate URLs for any symbol (crypto + RWA)."""
    s = sym.lower()
    return [
        # Stocks / RWA first (nvstly has excellent stock coverage)
        f"https://raw.githubusercontent.com/nvstly/icons/main/ticker_icons/{sym}.png",
        # Crypto SVGs (web3icons — 2500+ curated tokens)
        f"https://raw.githubusercontent.com/0xa3k5/web3icons/main/raw-svgs/tokens/{sym}.svg",
        f"https://cdn.jsdelivr.net/gh/0xa3k5/web3icons@main/raw-svgs/tokens/{sym}.svg",
        # Crypto SVGs (cryptofont — 1200+ tokens)
        f"https://raw.githubusercontent.com/Cryptofonts/cryptofont/master/SVG/{s}.svg",
        f"https://cdn.jsdelivr.net/gh/Cryptofonts/cryptofont@master/SVG/{s}.svg",
        # Stocks — Parqet (EU + US coverage)
        f"https://assets.parqet.com/logos/symbol/{sym}",
        # Stocks — n3tn1nja
        f"https://raw.githubusercontent.com/n3tn1nja/StockTickerIcons/main/icons/{sym}.png",
        # Crypto — CoinCap CDN
        f"https://assets.coincap.io/assets/icons/{s}@2x.png",
        # Crypto — AtomicLabs (~800 coins)
        f"https://cdn.jsdelivr.net/gh/atomiclabs/cryptocurrency-icons@master/128/color/{s}.png",
        # Crypto — ErikThiart (3000+ coins)
        f"https://raw.githubusercontent.com/ErikThiart/cryptocurrency-icons/master/16/{s}.png",
        # Stocks — Financial Modeling Prep
        f"https://financialmodelingprep.com/image-stock/{sym}.png",
        # Stocks — Clearbit (works when ticker matches company .com domain)
        f"https://logo.clearbit.com/{s}.com",
    ]


# ── URL probe ─────────────────────────────────────────────────────────────────
async def probe_url(client: httpx.AsyncClient, url: str) -> bool:
    try:
        resp = await client.head(url, follow_redirects=True, timeout=5.0)
        return resp.status_code == 200
    except Exception:
        return False


async def resolve_symbol(client: httpx.AsyncClient, sym: str) -> Dict[str, Any]:
    """Find the first reachable icon URL for sym, probing in batches of 5."""
    sources = get_sources(sym)
    batch_size = 5
    for i in range(0, len(sources), batch_size):
        batch = sources[i:i + batch_size]
        results = await asyncio.gather(*[probe_url(client, u) for u in batch])
        for url, ok in zip(batch, results):
            if ok:
                logger.debug(f"Resolved icon for {sym}: {url}")
                return {"url": url}
    logger.debug(f"No icon found for {sym}")
    return {"url": None}


# ── Endpoint ──────────────────────────────────────────────────────────────────
@router.get("")
async def get_icons(symbols: str = Query(..., description="Comma-separated list of market symbols")):
    from storage.redis_manager import redis_manager

    symbol_list = [s.strip().upper() for s in symbols.split(',') if s.strip()]
    if not symbol_list:
        return {}

    result: Dict[str, Any] = {}
    to_resolve: List[str] = []

    # ── Check Redis cache ────────────────────────────────────────────────────
    r = redis_manager._redis
    if r:
        keys = [f"{REDIS_KEY_PREFIX}{sym}" for sym in symbol_list]
        cached_values = await r.mget(*keys)
        for sym, val in zip(symbol_list, cached_values):
            if val:
                result[sym] = json.loads(val)
            else:
                to_resolve.append(sym)
    else:
        to_resolve = symbol_list[:]

    # ── Detect forex (no HTTP probe needed) ──────────────────────────────────
    non_forex: List[str] = []
    for sym in to_resolve:
        forex = detect_forex(sym)
        if forex:
            result[sym] = forex
            if r:
                await r.setex(f"{REDIS_KEY_PREFIX}{sym}", REDIS_TTL, json.dumps(forex))
        else:
            non_forex.append(sym)

    # ── Probe remaining symbols concurrently ─────────────────────────────────
    if non_forex:
        async with httpx.AsyncClient() as client:
            resolved = await asyncio.gather(
                *[resolve_symbol(client, sym) for sym in non_forex]
            )
        for sym, data in zip(non_forex, resolved):
            result[sym] = data
            if r and data.get("url"):
                await r.setex(f"{REDIS_KEY_PREFIX}{sym}", REDIS_TTL, json.dumps(data))

    return result
