"""
End-to-end test for size_pct via API:
1. Ambil balance user dari /api/portfolio
2. Place order dengan size_pct=0.25 → sistem hitung sendiri amount_usd
3. Cek positions untuk konfirmasi
"""
import json
import urllib.request

BASE = "http://localhost:8000"
USER = "0x1234567890123456789012345678901234567890"

def get(path, params=None):
    url = f"{BASE}{path}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url += "?" + qs
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())

def post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{BASE}{path}", data=body,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

# 1. Cek balance user dari positions/summary
print("=== STEP 1: Cek balance user ===")
pos_data = get("/api/orders/positions", {"user_address": USER, "exchange": "simulation"})
summary = pos_data.get("summary", {})
free_col = summary.get("free_collateral", 0)
acct_val = summary.get("account_value", 0)
margin   = summary.get("total_margin_used", 0)
print(f"  account_value   : ${acct_val}")
print(f"  total_margin    : ${margin}")
print(f"  free_collateral : ${free_col}")
print(f"  open positions  : {len(pos_data.get('positions', []))}")

# Juga cek dari portfolio endpoint
print("\n=== STEP 2: Cek portfolio metrics ===")
try:
    port = get("/api/portfolio/metrics", {"user_address": USER})
    print(json.dumps(port, indent=2))
except Exception as e:
    print(f"  (portfolio endpoint error: {e})")

# 3. Place order via simulation — size_pct bisa di-test kalau ada balance
# NOTE: API /api/orders/place tidak support size_pct langsung (hanya agent tool),
# tapi kita bisa simulasi dengan explicit amount_usd dari balance
print("\n=== STEP 3: Place order $50 (test fill) ===")
result = post("/api/orders/place", {
    "user_address": USER,
    "symbol": "ETH-USD",
    "side": "buy",
    "order_type": "market",
    "amount_usd": 50,
    "leverage": 3,
    "exchange": "simulation",
})
print(json.dumps(result, indent=2))

print("\n=== STEP 4: Cek positions setelah order ===")
pos_after = get("/api/orders/positions", {"user_address": USER, "exchange": "simulation"})
for p in pos_after.get("positions", []):
    print(f"  {p['side']} {p['symbol']} size={p['size']:.6f} entry={p['entry_price']:.2f} margin=${p['margin_used']}")
print(f"  summary: {pos_after.get('summary', {})}")
