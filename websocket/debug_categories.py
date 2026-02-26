import asyncio
import httpx
from collections import Counter

async def check_categories():
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get("http://127.0.0.1:8000/api/markets/?canonical_only=true")
            if resp.status_code == 200:
                markets = resp.json().get("markets", [])
                print(f"Total Canonical Markets: {len(markets)}")
                
                categories = [m.get("category") for m in markets]
                counts = Counter(categories)
                print("\nCategory Counts:")
                for cat, count in counts.items():
                    print(f"  - {cat}: {count}")
                
                # Sample of "None" or unknown categories
                missing = [m.get("symbol") for m in markets if m.get("category") not in ['Crypto', 'Forex', 'Stocks', 'Commodities', 'Index']]
                print(f"\nSample of markets NOT in standard categories ({len(missing)}):")
                print(missing[:20])
                
            else:
                print(f"API Error: {resp.status_code}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_categories())
