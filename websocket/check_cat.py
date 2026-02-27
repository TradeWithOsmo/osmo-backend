import json

data = json.load(open('contracts/config/symbol_registry.json', encoding='utf-8'))
missing = []
for s in data['symbols']:
    if not s.get('category') or not s.get('subCategory'):
        missing.append(s['tradingSymbol'])

print(f"Total symbols: {len(data['symbols'])}")
print(f"Missing category: {len(missing)}")
if missing:
    print(f"First 10 missing: {missing[:10]}")
