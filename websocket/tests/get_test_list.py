import asyncio
import httpx
import json

async def get_test_list():
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get("http://127.0.0.1:8000/api/markets/")
            if resp.status_code == 200:
                markets = resp.json().get("markets", [])
                
                exchanges = ["hyperliquid", "ostium", "aster", "vest", "lighter", "avantis"]
                result = {}
                
                for exc in exchanges:
                    syms = [m.get("symbol") for m in markets if m.get("source") == exc]
                    # Filter for some interesting ones or just take top 5
                    result[exc] = syms[:5]
                
                print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(get_test_list())
