"""
generate_icon_map.py
====================
Scans locally cloned icon repos and generates icon_map.json.

URL strategy (hybrid):
  - File EXISTS locally  → self-hosted URL  (faster, no external hop)
  - File MISSING locally → external CDN URL (jsDelivr / GitHub raw)

Priority (first match wins):
  1. web3icons/branded    → colored crypto SVGs, transparent bg   (SVG ~2KB)
  2. web3icons/background → crypto SVGs with shaped background    (SVG ~3KB)
  3. cryptofont/SVG       → mono SVGs, broad coverage             (SVG ~1KB)
  4. nvstly/ticker_icons  → stocks, RWA, some crypto              (PNG ~8KB)
  5. pymmdrza/PNG         → additional crypto                     (PNG ~10KB)

SVG sources are listed before PNG — same symbol with SVG wins over PNG.

Run:
  python3 generate_icon_map.py [repos_path] [base_url] [output_path]

Defaults:
  repos_path : /app/icon-repos
  base_url   : http://76.13.219.146:8000/icons   (or set ICONS_BASE_URL env)
  output     : {repos_path}/icon_map.json
"""

import json
import os
import sys

# ── Args / config ──────────────────────────────────────────────────────────────
REPOS    = sys.argv[1] if len(sys.argv) > 1 else '/app/icon-repos'
BASE_URL = (
    sys.argv[2]
    if len(sys.argv) > 2
    else os.environ.get('ICONS_BASE_URL', 'http://76.13.219.146:8000/icons')
).rstrip('/')
OUTPUT   = sys.argv[3] if len(sys.argv) > 3 else os.path.join(REPOS, 'icon_map.json')

print(f'Repos  : {REPOS}')
print(f'BaseURL: {BASE_URL}')
print(f'Output : {OUTPUT}')
print()

# ── Source definitions ─────────────────────────────────────────────────────────
# Each entry:
#   local_dir       — path to scan for files
#   ext             — file extension to match
#   self_url_tmpl   — URL when file exists locally   (uses {upper} / {lower})
#   cdn_url_tmpl    — URL when file is missing locally (fallback)
#
# {upper} = symbol uppercased  e.g. BTC
# {lower} = symbol lowercased  e.g. btc

SOURCES = [
    # ── SVG first (smallest, scalable) ────────────────────────────────────────
    {
        'dir':      os.path.join(REPOS, 'web3icons', 'raw-svgs', 'tokens', 'branded'),
        'ext':      '.svg',
        'self_url': f'{BASE_URL}/web3icons/raw-svgs/tokens/branded/{{upper}}.svg',
        'cdn_url':  'https://cdn.jsdelivr.net/gh/0xa3k5/web3icons@main/raw-svgs/tokens/branded/{upper}.svg',
    },
    {
        'dir':      os.path.join(REPOS, 'web3icons', 'raw-svgs', 'tokens', 'background'),
        'ext':      '.svg',
        'self_url': f'{BASE_URL}/web3icons/raw-svgs/tokens/background/{{upper}}.svg',
        'cdn_url':  'https://cdn.jsdelivr.net/gh/0xa3k5/web3icons@main/raw-svgs/tokens/background/{upper}.svg',
    },
    {
        'dir':      os.path.join(REPOS, 'cryptofont', 'SVG'),
        'ext':      '.svg',
        'self_url': f'{BASE_URL}/cryptofont/SVG/{{lower}}.svg',
        'cdn_url':  'https://cdn.jsdelivr.net/gh/Cryptofonts/cryptofont@master/SVG/{lower}.svg',
    },
    # ── PNG fallback (only when no SVG exists for the symbol) ─────────────────
    {
        'dir':      os.path.join(REPOS, 'nvstly', 'ticker_icons'),
        'ext':      '.png',
        'self_url': f'{BASE_URL}/nvstly/ticker_icons/{{upper}}.png',
        'cdn_url':  'https://raw.githubusercontent.com/nvstly/icons/main/ticker_icons/{upper}.png',
    },
    {
        'dir':      os.path.join(REPOS, 'pymmdrza', 'PNG'),
        'ext':      '.png',
        'self_url': f'{BASE_URL}/pymmdrza/PNG/{{upper}}.png',
        'cdn_url':  'https://cdn.jsdelivr.net/gh/Pymmdrza/CryptocurrencyIcons@main/PNG/{upper}.png',
    },
    # erikthiart intentionally excluded — 2.4GB, used only as live CDN probe fallback
]

# ── Build map ──────────────────────────────────────────────────────────────────
icon_map: dict = {}
stats = {'self': 0, 'cdn': 0, 'skipped': 0}

for source in SOURCES:
    directory   = source['dir']
    ext         = source['ext']
    self_tmpl   = source['self_url']
    cdn_tmpl    = source['cdn_url']

    if not os.path.isdir(directory):
        label = '/'.join(directory.split(os.sep)[-2:])
        print(f'  SKIP (not found): {label}')
        stats['skipped'] += 1
        continue

    count_self = 0
    count_cdn  = 0

    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(ext):
            continue

        stem   = filename[:-len(ext)]
        symbol = stem.upper()

        if symbol in icon_map:
            continue  # already mapped by higher-priority source

        filepath = os.path.join(directory, filename)
        file_exists_locally = os.path.isfile(filepath)

        if file_exists_locally:
            url = self_tmpl.format(upper=stem.upper(), lower=stem.lower())
            count_self += 1
            stats['self'] += 1
        else:
            # File listed in dir scan but not accessible (symlink broken etc.)
            # Fall through to CDN
            url = cdn_tmpl.format(upper=stem.upper(), lower=stem.lower())
            count_cdn += 1
            stats['cdn'] += 1

        icon_map[symbol] = url

    label = '/'.join(directory.split(os.sep)[-2:])
    print(f'  {label}: +{count_self} self-hosted, +{count_cdn} CDN fallback')

# ── pymmdrza special case: not cloned locally → all CDN ──────────────────────
# (If pymmdrza dir missing, symbols not found in other sources get CDN URL)
# Already handled above via SKIP + cdn_url path.

# ── Summary ────────────────────────────────────────────────────────────────────
print(f'\nTotal  : {len(icon_map)} symbols mapped')
print(f'  Self-hosted : {stats["self"]}')
print(f'  CDN fallback: {stats["cdn"]}')
print(f'  Skipped dirs: {stats["skipped"]}')

# ── Save ───────────────────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(OUTPUT) or '.', exist_ok=True)
with open(OUTPUT, 'w') as f:
    json.dump(icon_map, f, separators=(',', ':'), sort_keys=True)

print(f'\nSaved  : {OUTPUT}')

# ── Samples ────────────────────────────────────────────────────────────────────
samples = ['BTC', 'ETH', 'SOL', 'ARC', '42', 'AAPL', 'NVDA', 'EUR', 'XAU']
print('\nSamples:')
for s in samples:
    val = icon_map.get(s, 'NOT FOUND')
    src = '(self)' if BASE_URL in val else '(cdn) ' if val != 'NOT FOUND' else ''
    print(f'  {s:<8} {src}  {val}')