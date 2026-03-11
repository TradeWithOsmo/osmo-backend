"""
Test place_order, check order history, and get positions via API.
Run on VPS: python3 test_api.py
"""
import json
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"
USER = "0x1234567890123456789012345678901234567890"


def post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": e.read().decode()}


def get(path, params=None):
    url = f"{BASE_URL}{path}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": e.read().decode()}


print("=" * 60)
print("1. PLACE ORDER (BTC-USD BUY $100 5x simulation)")
print("=" * 60)
result = post("/api/orders/place", {
    "user_address": USER,
    "symbol": "BTC-USD",
    "side": "buy",
    "order_type": "market",
    "amount_usd": 100,
    "leverage": 5,
    "exchange": "simulation",
})
print(json.dumps(result, indent=2))
order_id = result.get("order_id")

print("\n")
print("=" * 60)
print("2. CHECK ORDER HISTORY")
print("=" * 60)
orders = get("/api/orders/history", {"user_address": USER, "exchange": "simulation"})
print(json.dumps(orders, indent=2))

print("\n")
print("=" * 60)
print("3. CHECK POSITIONS")
print("=" * 60)
positions = get("/api/orders/positions", {"user_address": USER, "exchange": "simulation"})
print(json.dumps(positions, indent=2))
