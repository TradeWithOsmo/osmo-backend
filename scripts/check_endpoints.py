import requests
import json
import time

BASE_URL = "http://localhost:8000"

def check_endpoint(name, url, params=None):
    print(f"\n🔍 Checking {name} ({url})...")
    try:
        start = time.time()
        response = requests.get(url, params=params, timeout=15)
        elapsed = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Success ({response.status_code}) - {elapsed:.0f}ms")
            
            if isinstance(data, list):
                print(f"📊 Items found: {len(data)}")
                if len(data) > 0:
                    print("📝 Sample Data (First item):")
                    print(json.dumps(data[0], indent=2))
            else:
                print("📝 Response:", json.dumps(data, indent=2))
            return True
        else:
            print(f"❌ Failed: HTTP {response.status_code}")
            print("Response:", response.text[:200])
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    print("🚀 Starting Final System Verification")
    
    # 1. Health
    check_endpoint("Health", f"{BASE_URL}/health")
    
    # 2. Market Connectors
    check_endpoint("Hyperliquid Prices", f"{BASE_URL}/api/connectors/hyperliquid/prices")
    check_endpoint("Ostium Prices", f"{BASE_URL}/api/connectors/ostium/prices")
    
    # 3. History (TradingView)
    check_endpoint("History (BTC-USD HL)", f"{BASE_URL}/api/history", 
                   params={"symbol": "BTC-USD", "resolution": "60", "from": int(time.time()) - 86400, "to": int(time.time()), "source": "hyperliquid"})
    
    # 4. Usage
    # Using a placeholder address
    test_user = "0x0000000000000000000000000000000000000000"
    check_endpoint("Usage Stats", f"{BASE_URL}/api/usage/stats/{test_user}")
    check_endpoint("Usage History", f"{BASE_URL}/api/usage/history/{test_user}")

if __name__ == "__main__":
    main()
