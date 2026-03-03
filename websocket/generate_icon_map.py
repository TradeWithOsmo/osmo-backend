"""
generate_icon_map.py
Scans locally cloned icon repos and generates icon_map.json:
  { "BTC": "https://cdn.../btc.svg", "ETH": "...", ... }

Priority (first match wins):
  1. nvstly/ticker_icons      → stocks, RWA, some crypto (PNG, uppercase)
  2. web3icons/branded        → colored crypto SVGs, transparent bg (uppercase)
  3. web3icons/background     → crypto SVGs with shaped background (uppercase)
  4. pymmdrza                 → additional crypto PNGs (uppercase)
  5. cryptofont/SVG           → mono SVGs, fallback only (lowercase)

Run: python3 generate_icon_map.py [repos_path] [output_path]
Default repos_path: /app/icon-repos
Default output:     /app/icon-repos/icon_map.json
"""
import json
import os
import sys

REPOS = sys.argv[1] if len(sys.argv) > 1 else '/app/icon-repos'
OUTPUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(REPOS, 'icon_map.json')

SOURCES = [
    # (local_dir, filename_case, cdn_url_template)
    # filename_case: 'upper' or 'lower'
    # Priority: nvstly (stocks+some crypto) → web3icons background (colored circular)
    #           → web3icons branded (colored transparent) → cryptofont (mono, fallback only)
    (
        os.path.join(REPOS, 'nvstly', 'ticker_icons'),
        'upper', '.png',
        'https://raw.githubusercontent.com/nvstly/icons/main/ticker_icons/{upper}.png',
    ),
    (
        os.path.join(REPOS, 'web3icons', 'raw-svgs', 'tokens', 'branded'),
        'upper', '.svg',
        'https://cdn.jsdelivr.net/gh/0xa3k5/web3icons@main/raw-svgs/tokens/branded/{upper}.svg',
    ),
    (
        os.path.join(REPOS, 'web3icons', 'raw-svgs', 'tokens', 'background'),
        'upper', '.svg',
        'https://cdn.jsdelivr.net/gh/0xa3k5/web3icons@main/raw-svgs/tokens/background/{upper}.svg',
    ),
    (
        os.path.join(REPOS, 'pymmdrza', 'PNG'),
        'upper', '.png',
        'https://cdn.jsdelivr.net/gh/Pymmdrza/CryptocurrencyIcons@main/PNG/{upper}.png',
    ),
    (
        os.path.join(REPOS, 'cryptofont', 'SVG'),
        'lower', '.svg',
        'https://cdn.jsdelivr.net/gh/Cryptofonts/cryptofont@master/SVG/{lower}.svg',
    ),
]

icon_map = {}

for (directory, case, ext, url_template) in SOURCES:
    if not os.path.isdir(directory):
        print(f'  SKIP (not found): {directory}')
        continue

    count_new = 0
    for filename in os.listdir(directory):
        if not filename.endswith(ext):
            continue
        base = filename[:-len(ext)]  # strip extension
        symbol = base.upper()
        if symbol in icon_map:
            continue  # already mapped by higher-priority source
        url = url_template.format(upper=base.upper(), lower=base.lower())
        icon_map[symbol] = url
        count_new += 1

    print(f'  {directory.split(os.sep)[-2]}/{directory.split(os.sep)[-1]}: +{count_new} symbols')

print(f'\nTotal: {len(icon_map)} symbols mapped')

with open(OUTPUT, 'w') as f:
    json.dump(icon_map, f, separators=(',', ':'))

print(f'Saved: {OUTPUT}')

# Sample
samples = ['BTC', 'ETH', 'SOL', 'ARC', '42', 'AAPL', 'NVDA']
print('\nSamples:')
for s in samples:
    print(f'  {s}: {icon_map.get(s, "NOT FOUND")}')
