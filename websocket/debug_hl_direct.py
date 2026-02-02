
import aiohttp
import asyncio
import json

async def main():
    url = "https://api.hyperliquid.xyz/info"
    payload = {"type": "metaAndAssetCtxs"}
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    # data is [meta, assetCtxs]
                    if data and len(data) == 2:
                        meta = data[0]
                        universe = meta.get("universe", [])
                        if universe:
                            print(f"First asset keys: {list(universe[0].keys())}")
                            print(f"First asset content: {universe[0]}")
                        else:
                            print("Universe is empty.")
                    else:
                        print("Unexpected data format.")
                else:
                    print(f"Error: {response.status} - {await response.text()}")
        except Exception as e:
            print(f"Exception: {e}")

if __name__ == "__main__":
    asyncio.run(main())
