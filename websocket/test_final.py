"""Quick end-to-end test via API HTTP calls"""
import json
import urllib.request

BASE = "http://localhost:8000"
USER = "0xabcdef1234567890abcdef1234567890abcdef12"

def post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def get(path, params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"{BASE}{path}?{qs}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

print("=== 1. PLACE ORDER ===")
r = post("/api/orders/place", {
    "user_address": USER, "symbol": "BTC-USD", "side": "buy",
    "order_type": "market", "amount_usd": 150, "leverage": 10,
    "exchange": "simulation"
})
print(json.dumps(r, indent=2))

print("\n=== 2. ORDER HISTORY ===")
orders = get("/api/orders/history", {"user_address": USER, "exchange": "simulation"})
for o in orders.get("orders", [])[:3]:
    print(f"  {o['side']} {o['symbol']} status={o['status']} filled_size={o.get('filled_size')} avg_fill={o.get('avg_fill_price')}")

print("\n=== 3. POSITIONS ===")
pos = get("/api/orders/positions", {"user_address": USER, "exchange": "simulation"})
for p in pos.get("positions", []):
    print(f"  {p['side']} {p['symbol']} size={p['size']:.6f} entry={p['entry_price']} margin={p['margin_used']} status={p['status']}")
