import asyncio
import httpx
import json

async def check_backend_state():
    print("Checking backend state...")
    try:
        # Check /api/markets to see what symbols are available and their sources
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get("http://127.0.0.1:8000/api/markets/")
            if resp.status_code == 200:
                data = resp.json()
                markets = data.get("markets", [])
                sources = {}
                for m in markets:
                    src = m.get("source")
                    sources[src] = sources.get(src, 0) + 1
                
                print(f"Markets found: {len(markets)}")
                for src, count in sources.items():
                    print(f"  - {src}: {count} symbols")
                
                # Sample some symbols from each source
                for src in sources:
                    sample = [m.get("symbol") for m in markets if m.get("source") == src][:3]
                    print(f"    Sample {src}: {sample}")
            else:
                print(f"Failed to fetch markets: {resp.status_code}")
    except Exception as e:
        print(f"Error checking backend: {e}")

if __name__ == "__main__":
    asyncio.run(check_backend_state())
