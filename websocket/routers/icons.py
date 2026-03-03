"""
Icon Resolver API
=================
Resolves icon data for market symbols with permanent PostgreSQL caching.

Lookup order per symbol:
  1. _ICON_MAP  — in-memory dict from icon_map.json (7943+ symbols, instant)
  2. icon_cache — PostgreSQL permanent table (survives restarts, no TTL)
  3. classify_no_probe — forex / commodity shortcuts (no I/O)
  4. CDN probe  — HTTP HEAD checks, result saved to icon_cache forever

Endpoint:
  GET /api/icons?symbols=BTC,ETH,AAPL,EUR-USD
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Query
from sqlalchemy import text

logger = logging.getLogger(__name__)
router = APIRouter()

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


# ── Commodity/metal icon URLs (TradingView CDN) ────────────────────────────────
_TV = 'https://s3-symbol-logo.tradingview.com'
COMMODITY_URLS: dict = {
    'XAU': f'{_TV}/metal/gold--big.svg',
    'XAG': f'{_TV}/metal/silver--big.svg',
    'XPD': f'{_TV}/metal/palladium--big.svg',
    'XPT': f'{_TV}/metal/platinum--big.svg',
    'CPR': f'{_TV}/metal/copper--big.svg',
    'XCU': f'{_TV}/metal/copper--big.svg',
    'WHT': f'{_TV}/commodity/wheat--big.svg',
    'CRN': f'{_TV}/commodity/corn--big.svg',
    'SGR': f'{_TV}/commodity/sugar--big.svg',
    'CTN': f'{_TV}/commodity/cotton--big.svg',
    'CFF': f'{_TV}/commodity/coffee--big.svg',
    'SOY': f'{_TV}/commodity/soybean--big.svg',
    'OIL': None, 'GAS': None, 'NGS': None, 'CCO': None,
}

# ── Codes with bundled SVG assets in the frontend ─────────────────────────────
LOCAL_CODES = {
    'CL', 'HG',
    'AAPL', 'AMD', 'AMZN', 'BMNR', 'COST', 'CRCL', 'CVX', 'GLXY', 'GOOG', 'HOOD',
    'META', 'MSFT', 'MSTR', 'NFLX', 'NVDA', 'ORCL', 'PLTR', 'RIVN', 'XOM', 'COIN',
    'TSLA', 'SBET',
    'DAX', 'DJI', 'FTSE', 'HSI', 'NDX', 'NIK', 'SPX',
    'DAXEUR', 'DJIUSD', 'FTSEGBP', 'HSIHKD', 'NDXUSD', 'NIKJPY', 'SPXUSD',
}


def classify_no_probe(sym: str) -> Optional[Dict[str, Any]]:
    """Classify symbol without HTTP probing. Returns None if probing is needed."""
    forex = detect_forex(sym)
    if forex:
        return forex
    parts = sym.split('-')
    base = parts[0] if len(parts) >= 2 else sym
    if sym in COMMODITY_URLS or base in COMMODITY_URLS:
        code = base if base in COMMODITY_URLS else sym
        return {"url": COMMODITY_URLS[code]}
    if sym in LOCAL_CODES:
        return {"type": "local", "key": sym}
    if base in LOCAL_CODES:
        return {"type": "local", "key": base}
    return None


# ── In-memory icon map (loaded once at startup) ────────────────────────────────
# Support both VPS path and Docker path
ICON_REPOS_PATH = next((p for p in ['/root/icon-repos', '/app/icon-repos'] if os.path.isdir(p)), '/app/icon-repos')
_ICON_MAP_PATH = f'{ICON_REPOS_PATH}/icon_map.json'
# Self-hosted base URL — eliminates GitHub/jsDelivr CDN hops for frontend
ICONS_BASE_URL = os.environ.get('ICONS_BASE_URL', 'http://76.13.219.146:8000/icons')


def _build_icon_map() -> dict:
    _b = ICONS_BASE_URL
    sources = [
        (f'{ICON_REPOS_PATH}/nvstly/ticker_icons', '.png',
         f'{_b}/nvstly/ticker_icons/{{u}}.png'),
        (f'{ICON_REPOS_PATH}/web3icons/raw-svgs/tokens/branded', '.svg',
         f'{_b}/web3icons/raw-svgs/tokens/branded/{{u}}.svg'),
        (f'{ICON_REPOS_PATH}/web3icons/raw-svgs/tokens/background', '.svg',
         f'{_b}/web3icons/raw-svgs/tokens/background/{{u}}.svg'),
        (f'{ICON_REPOS_PATH}/atomiclabs/128/color', '.png',
         f'{_b}/atomiclabs/128/color/{{l}}.png'),
        (f'{ICON_REPOS_PATH}/erikthiart/16', '.png',
         f'{_b}/erikthiart/16/{{l}}.png'),
        (f'{ICON_REPOS_PATH}/pymmdrza/PNG', '.png',
         'https://cdn.jsdelivr.net/gh/Pymmdrza/CryptocurrencyIcons@main/PNG/{u}.png'),
        (f'{ICON_REPOS_PATH}/cryptofont/SVG', '.svg',
         f'{_b}/cryptofont/SVG/{{l}}.svg'),
    ]
    m: dict = {}
    for directory, ext, tmpl in sources:
        if not os.path.isdir(directory):
            continue
        for fname in os.listdir(directory):
            if not fname.endswith(ext):
                continue
            stem = fname[:-len(ext)]
            sym = stem.upper()
            if sym not in m:
                m[sym] = tmpl.format(u=stem.upper(), l=stem.lower())
    return m


def _load_icon_map() -> dict:
    if os.path.isfile(_ICON_MAP_PATH):
        try:
            with open(_ICON_MAP_PATH) as f:
                data = json.load(f)
            logger.info(f'Icon map loaded: {len(data)} symbols')
            return data
        except Exception as e:
            logger.warning(f'Failed to load icon_map.json: {e}')
    if os.path.isdir(ICON_REPOS_PATH):
        logger.info('Generating icon_map.json from repos...')
        data = _build_icon_map()
        try:
            with open(_ICON_MAP_PATH, 'w') as f:
                json.dump(data, f, separators=(',', ':'))
        except Exception:
            pass
        return data
    logger.warning('Icon repos not found — using CDN probe only')
    return {}


_ICON_MAP: dict = _load_icon_map()


def find_local_icon(base: str) -> Optional[str]:
    return _ICON_MAP.get(base.upper())


# ── PostgreSQL permanent cache ─────────────────────────────────────────────────
async def _db_batch_get(symbols: List[str]) -> Dict[str, Any]:
    """Batch lookup from icon_cache. Only returns symbols that exist in DB."""
    try:
        from database.connection import engine
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT symbol, url FROM icon_cache WHERE symbol = ANY(:syms)"),
                {"syms": symbols}
            )
            return {row[0]: row[1] for row in rows}
    except Exception as e:
        logger.warning(f'icon_cache DB lookup failed: {e}')
        return {}


async def _db_save_many(entries: List[tuple]) -> None:
    """Batch insert (symbol, url) pairs into icon_cache. Ignores conflicts."""
    if not entries:
        return
    try:
        from database.connection import engine
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO icon_cache (symbol, url)
                    SELECT unnest(:syms::text[]), unnest(:urls::text[])
                    ON CONFLICT (symbol) DO NOTHING
                """),
                {"syms": [e[0] for e in entries], "urls": [e[1] for e in entries]}
            )
    except Exception as e:
        logger.warning(f'icon_cache DB save failed: {e}')


# ── CDN probe ─────────────────────────────────────────────────────────────────
def get_sources(sym: str) -> List[str]:
    s = sym.lower()
    b = ICONS_BASE_URL
    return [
        # ── Self-hosted repos (fastest — no external CDN hop) ────────────────
        f"{b}/nvstly/ticker_icons/{sym}.png",
        f"{b}/web3icons/raw-svgs/tokens/branded/{sym}.svg",
        f"{b}/atomiclabs/128/color/{s}.png",
        f"{b}/erikthiart/16/{s}.png",
        # ── External CDNs for repos not self-hosted ──────────────────────────
        f"https://cdn.jsdelivr.net/gh/Pymmdrza/CryptocurrencyIcons@main/PNG/{sym}.png",
        # ── TradingView CDN (crypto + stock) ────────────────────────────────
        f"https://s3-symbol-logo.tradingview.com/crypto/XTVC{sym}--big.svg",
        f"https://s3-symbol-logo.tradingview.com/{s}--big.svg",
        # ── Crypto asset CDNs ───────────────────────────────────────────────
        f"https://assets.coincap.io/assets/icons/{s}@2x.png",
        f"https://lcw.nyc3.cdn.digitaloceanspaces.com/production/currencies/128/{s}.webp",
        # ── Stock / financial logos ──────────────────────────────────────────
        f"https://assets.parqet.com/logos/symbol/{sym}",
        f"https://financialmodelingprep.com/image-stock/{sym}.png",
        f"https://logo.clearbit.com/{s}.com",
        # ── Fallback: background-shaped / mono icons (last resort) ───────────
        f"{b}/web3icons/raw-svgs/tokens/background/{sym}.svg",
        f"{b}/cryptofont/SVG/{s}.svg",
    ]


async def probe_url(client: httpx.AsyncClient, url: str) -> bool:
    try:
        resp = await client.head(url, follow_redirects=True, timeout=5.0)
        return resp.status_code == 200
    except Exception:
        return False


async def resolve_symbol(client: httpx.AsyncClient, sym: str) -> Dict[str, Any]:
    parts = sym.split('-')
    base = parts[0] if len(parts) >= 2 else sym

    local_url = find_local_icon(base)
    if local_url:
        return {"url": local_url}

    sources = get_sources(base) if base != sym else get_sources(sym)
    batch_size = 5
    for i in range(0, len(sources), batch_size):
        batch = sources[i:i + batch_size]
        results = await asyncio.gather(*[probe_url(client, u) for u in batch])
        for url, ok in zip(batch, results):
            if ok:
                return {"url": url}
    return {"url": None}


# ── Endpoint ──────────────────────────────────────────────────────────────────
@router.get("")
async def get_icons(symbols: str = Query(..., description="Comma-separated list of market symbols")):
    symbol_list = [s.strip().upper() for s in symbols.split(',') if s.strip()]
    if not symbol_list:
        return {}

    result: Dict[str, Any] = {}
    need_db: List[str] = []

    # 1. In-memory icon_map — instant, no I/O
    for sym in symbol_list:
        parts = sym.split('-')
        base = parts[0] if len(parts) >= 2 else sym
        url = find_local_icon(base)
        if url:
            result[sym] = {"url": url}
        else:
            need_db.append(sym)

    # 2. PostgreSQL permanent cache — single batch query
    if need_db:
        db_hits = await _db_batch_get(need_db)
        still_missing: List[str] = []
        for sym in need_db:
            if sym in db_hits:
                result[sym] = {"url": db_hits[sym]}
            else:
                still_missing.append(sym)
        need_db = still_missing

    # 3. Classify forex/commodity (no I/O)
    to_probe: List[str] = []
    for sym in need_db:
        classified = classify_no_probe(sym)
        if classified:
            result[sym] = classified
        else:
            to_probe.append(sym)

    # 4. CDN probe — all concurrent, save to DB permanently
    if to_probe:
        async with httpx.AsyncClient() as client:
            resolved = await asyncio.gather(
                *[resolve_symbol(client, sym) for sym in to_probe]
            )
        to_save: List[tuple] = []
        for sym, data in zip(to_probe, resolved):
            result[sym] = data
            to_save.append((sym, data.get("url")))
        await _db_save_many(to_save)

    return result
