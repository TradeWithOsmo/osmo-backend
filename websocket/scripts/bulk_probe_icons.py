"""
bulk_probe_icons.py
===================
Probes ALL platform symbols concurrently for icons and saves results
permanently to the icon_cache PostgreSQL table.

Run once manually or at container startup:
  python3 /app/scripts/bulk_probe_icons.py

Steps:
  1. Bulk-import ALL icon_map.json symbols into DB (instant, no probing)
  2. For platform registry symbols not yet in DB, probe CDN sources
  3. Re-probe any existing null entries with expanded CDN source list
  4. Save all results permanently (null = probed, nothing found)

Uses a semaphore to avoid overwhelming connections (max 80 concurrent probes).
"""

import asyncio
import json
import logging
import os

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://osmo_user:osmo_password@db:5432/osmo_db')
SYMBOL_REGISTRY_PATH = os.getenv('SYMBOL_REGISTRY_PATH', '/app/contracts/config/symbol_registry.json')
ICON_MAP_PATH = '/app/icon-repos/icon_map.json'
MAX_CONCURRENT = 80  # semaphore limit for CDN probes

_TV = 'https://s3-symbol-logo.tradingview.com'
COMMODITY_URLS = {
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
}

FIAT_CURRENCIES = {
    'USD', 'EUR', 'GBP', 'JPY', 'AUD', 'NZD', 'CAD', 'CHF', 'MXN',
    'SGD', 'HKD', 'NOK', 'SEK', 'DKK', 'TRY', 'ZAR', 'BRL', 'CNY',
    'INR', 'KRW', 'TWD', 'HUF', 'CZK', 'PLN', 'THB', 'IDR', 'MYR',
    'PHP', 'RUB', 'UAH', 'COP', 'CLP', 'PEN', 'ARS', 'VND',
}

QUOTE_SUFFIXES = ['USDT', 'USD', 'USDC', 'BTC', 'ETH', 'BUSD', 'EUR', 'GBP']


def extract_base(trading_symbol: str) -> str:
    """Extract base token from any trading symbol format.
    'AAVE-AEVO' → 'AAVE', 'AAVEUSDT' → 'AAVE', 'BTC' → 'BTC'
    """
    # Handle dash-delimited formats (e.g. AAVE-AEVO, EUR-USD)
    if '-' in trading_symbol:
        return trading_symbol.split('-')[0].upper()
    # Handle concatenated formats (e.g. AAVEUSDT)
    ts = trading_symbol.upper()
    for q in QUOTE_SUFFIXES:
        if ts.endswith(q) and len(ts) > len(q):
            return ts[:-len(q)]
    return ts


def get_sources(sym: str):
    s = sym.lower()
    return [
        # ── Locally cloned repos (CDN mirrors) ──────────────────────────────
        f"https://raw.githubusercontent.com/nvstly/icons/main/ticker_icons/{sym}.png",
        f"https://cdn.jsdelivr.net/gh/0xa3k5/web3icons@main/raw-svgs/tokens/background/{sym}.svg",
        f"https://cdn.jsdelivr.net/gh/0xa3k5/web3icons@main/raw-svgs/tokens/branded/{sym}.svg",
        f"https://raw.githubusercontent.com/Cryptofonts/cryptofont/master/SVG/{s}.svg",
        f"https://cdn.jsdelivr.net/gh/Cryptofonts/cryptofont@master/SVG/{s}.svg",
        f"https://cdn.jsdelivr.net/gh/Pymmdrza/CryptocurrencyIcons@main/PNG/{sym}.png",
        # ── TradingView CDN (crypto + stock) ────────────────────────────────
        f"https://s3-symbol-logo.tradingview.com/crypto/XTVC{sym}--big.svg",
        f"https://s3-symbol-logo.tradingview.com/{s}--big.svg",
        # ── Crypto asset CDNs ───────────────────────────────────────────────
        f"https://assets.coincap.io/assets/icons/{s}@2x.png",
        f"https://cdn.jsdelivr.net/gh/atomiclabs/cryptocurrency-icons@master/128/color/{s}.png",
        f"https://raw.githubusercontent.com/ErikThiart/cryptocurrency-icons/master/16/{s}.png",
        f"https://lcw.nyc3.cdn.digitaloceanspaces.com/production/currencies/128/{s}.webp",
        # ── Stock / financial logos ──────────────────────────────────────────
        f"https://assets.parqet.com/logos/symbol/{sym}",
        f"https://financialmodelingprep.com/image-stock/{sym}.png",
        f"https://logo.clearbit.com/{s}.com",
    ]


async def probe_url(client: httpx.AsyncClient, url: str) -> bool:
    try:
        resp = await client.head(url, follow_redirects=True, timeout=6.0)
        return resp.status_code == 200
    except Exception:
        return False


async def find_icon(client: httpx.AsyncClient, sem: asyncio.Semaphore, sym: str) -> str | None:
    async with sem:
        sources = get_sources(sym)
        batch_size = 5
        for i in range(0, len(sources), batch_size):
            batch = sources[i:i + batch_size]
            results = await asyncio.gather(*[probe_url(client, u) for u in batch])
            for url, ok in zip(batch, results):
                if ok:
                    return url
    return None


async def main():
    # ── Connect to DB ────────────────────────────────────────────────────────
    conn = await asyncpg.connect(DATABASE_URL)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS icon_cache (
            symbol TEXT PRIMARY KEY,
            url TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # ── Step 1: Bulk-import ALL icon_map.json symbols ────────────────────────
    # This gets us 7000+ entries instantly from the locally cloned repos.
    icon_map: dict = {}
    if os.path.isfile(ICON_MAP_PATH):
        with open(ICON_MAP_PATH) as f:
            icon_map = json.load(f)
        logger.info(f'icon_map: {len(icon_map)} symbols — bulk importing to DB...')

        icon_map_entries = list(icon_map.items())
        await conn.executemany(
            "INSERT INTO icon_cache (symbol, url) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            icon_map_entries,
        )
        logger.info(f'Imported {len(icon_map_entries)} icon_map symbols to DB (skipped duplicates)')
    else:
        logger.warning('icon_map.json not found — skipping bulk import')

    # ── Step 2: Platform registry — find unique base symbols ─────────────────
    with open(SYMBOL_REGISTRY_PATH) as f:
        registry = json.load(f)

    all_entries = registry.get('symbols', [])
    base_symbols: set[str] = set()
    for entry in all_entries:
        ts = entry.get('tradingSymbol', '') if isinstance(entry, dict) else str(entry)
        base = extract_base(ts)
        if base:
            base_symbols.add(base)

    logger.info(f'Platform base symbols: {len(base_symbols)}')

    # ── Step 3: Re-probe existing nulls with expanded source list ─────────────
    null_rows = await conn.fetch("SELECT symbol FROM icon_cache WHERE url IS NULL")
    null_symbols = {r['symbol'] for r in null_rows}
    if null_symbols:
        await conn.execute("DELETE FROM icon_cache WHERE url IS NULL")
        logger.info(f'Deleted {len(null_symbols)} null entries — will re-probe with expanded sources')
        # Add them back to be re-probed (only platform bases or previously probed ones)
        base_symbols.update(null_symbols)

    # ── Step 4: Resolve remaining symbols ────────────────────────────────────
    rows = await conn.fetch("SELECT symbol FROM icon_cache")
    cached = {r['symbol'] for r in rows}
    logger.info(f'Already in icon_cache DB: {len(cached)}')

    to_probe = []
    auto_resolved = {}

    for sym in base_symbols:
        if sym in cached:
            continue
        if sym in icon_map:
            auto_resolved[sym] = icon_map[sym]
        elif sym in COMMODITY_URLS:
            auto_resolved[sym] = COMMODITY_URLS[sym]
        elif sym in FIAT_CURRENCIES:
            pass  # handled by frontend — no DB entry needed
        else:
            to_probe.append(sym)

    if auto_resolved:
        await conn.executemany(
            "INSERT INTO icon_cache (symbol, url) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            list(auto_resolved.items()),
        )
        logger.info(f'Saved {len(auto_resolved)} from icon_map/commodity to DB')

    logger.info(f'Symbols to CDN-probe: {len(to_probe)}')
    if not to_probe:
        total = await conn.fetchval("SELECT COUNT(*) FROM icon_cache")
        found = await conn.fetchval("SELECT COUNT(*) FROM icon_cache WHERE url IS NOT NULL")
        logger.info(f'All done — icon_cache: {total} total, {found} with icons')
        await conn.close()
        return

    # ── Step 5: CDN probe with semaphore ─────────────────────────────────────
    logger.info(f'Starting CDN probe (max {MAX_CONCURRENT} concurrent)...')
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    async with httpx.AsyncClient() as client:
        icon_urls = await asyncio.gather(*[find_icon(client, sem, sym) for sym in to_probe])

    found = sum(1 for u in icon_urls if u)
    logger.info(f'Probe complete: {found}/{len(to_probe)} found')

    # Save ALL probe results (null = "probed, no icon found")
    probe_entries = list(zip(to_probe, icon_urls))
    await conn.executemany(
        "INSERT INTO icon_cache (symbol, url) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        probe_entries,
    )
    logger.info(f'Saved {len(probe_entries)} probe entries to DB')

    missing = [sym for sym, url in zip(to_probe, icon_urls) if url is None]
    logger.info(f'No icon for {len(missing)} symbols: {sorted(missing)}')

    total = await conn.fetchval("SELECT COUNT(*) FROM icon_cache")
    with_icon = await conn.fetchval("SELECT COUNT(*) FROM icon_cache WHERE url IS NOT NULL")
    logger.info(f'Final DB state: {total} total symbols, {with_icon} with icons')

    await conn.close()
    logger.info('Done.')


if __name__ == '__main__':
    asyncio.run(main())
