
import asyncio
from Hyperliquid.http_client import http_client

async def main():
    try:
        print("Fetching Hyperliquid metadata...")
        data = await http_client.get_meta_and_asset_ctxs()
        if data and len(data) == 2:
            meta = data[0]
            universe = meta.get("universe", [])
            if universe:
                print(f"First asset in universe keys: {universe[0].keys()}")
                print(f"First asset content: {universe[0]}")
            else:
                print("Universe is empty.")
        else:
            print("Failed to fetch data or unexpected format.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
