"""
Icon Resolver API
=================
Resolves icon data for market symbols with persistent Redis caching.

Endpoints:
  GET /api/icons?symbols=BTC,ETH,AAPL,EUR-USD  – batch resolve icon data

Response types per symbol:
  {type:"forex", base, quote}   – forex pair (use dual-flag UI)
  {type:"package", code}        – metal/commodity in global-trade-react-icon
  {type:"local", key}           – asset with bundled SVG in frontend
  {url:"..."}                   – resolved CDN/repo URL
  {url:null}                    – no icon found
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


# ── Codes handled by global-trade-react-icon npm package ──────────────────────
# Metals: XAU=Gold, XAG=Silver, XPD=Palladium, XPT=Platinum, CPR=Copper
# Commodities: OIL, GAS, NGS=NatGas, SOY, WHT=Wheat, CCO=Cocoa,
#              CFF=Coffee, CTN=Cotton, CRN=Corn, SGR=Sugar
PACKAGE_CODES = {
    'XAU', 'XAG', 'XPD', 'XPT', 'CPR',
    'OIL', 'GAS', 'NGS', 'SOY', 'WHT', 'CCO', 'CFF', 'CTN', 'CRN', 'SGR',
}

# ── Codes with bundled SVG assets in the frontend ─────────────────────────────
LOCAL_CODES = {
    # Commodities (local SVG, not in package)
    'CL', 'HG',
    # Stocks
    'AAPL', 'AMD', 'AMZN', 'BMNR', 'COST', 'CRCL', 'CVX', 'GLXY', 'GOOG', 'HOOD',
    'META', 'MSFT', 'MSTR', 'NFLX', 'NVDA', 'ORCL', 'PLTR', 'RIVN', 'XOM', 'COIN',
    'TSLA', 'SBET',
    # Indices (base and compound forms, e.g. DAX and DAXEUR)
    'DAX', 'DJI', 'FTSE', 'HSI', 'NDX', 'NIK', 'SPX',
    'DAXEUR', 'DJIUSD', 'FTSEGBP', 'HSIHKD', 'NDXUSD', 'NIKJPY', 'SPXUSD',
}


def classify_no_probe(sym: str) -> Optional[Dict[str, Any]]:
    """Classify symbol without HTTP probing. Returns None if probing is needed."""
    forex = detect_forex(sym)
    if forex:
        return forex

    # Extract base for compound pairs like XAU-USD → XAU, SPX-USD → SPX
    parts = sym.split('-')
    base = parts[0] if len(parts) >= 2 else sym

    if sym in PACKAGE_CODES or base in PACKAGE_CODES:
        code = base if base in PACKAGE_CODES else sym
        return {"type": "package", "code": code}

    if sym in LOCAL_CODES:
        return {"type": "local", "key": sym}
    if base in LOCAL_CODES:
        return {"type": "local", "key": base}

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

    # ── Classify without probing (forex, package, local) ─────────────────────
    to_probe: List[str] = []
    for sym in to_resolve:
        classified = classify_no_probe(sym)
        if classified:
            result[sym] = classified
            if r:
                await r.setex(f"{REDIS_KEY_PREFIX}{sym}", REDIS_TTL, json.dumps(classified))
        else:
            to_probe.append(sym)

    # ── Probe remaining symbols concurrently ─────────────────────────────────
    if to_probe:
        async with httpx.AsyncClient() as client:
            resolved = await asyncio.gather(
                *[resolve_symbol(client, sym) for sym in to_probe]
            )
        for sym, data in zip(to_probe, resolved):
            result[sym] = data
            if r and data.get("url"):
                await r.setex(f"{REDIS_KEY_PREFIX}{sym}", REDIS_TTL, json.dumps(data))

    return result
