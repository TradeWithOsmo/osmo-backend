import asyncio
import httpx

async def main():
    urls = [
        "https://mainnet.zklighter.elliot.ai/orderbooks",
        "https://mainnet.zklighter.elliot.ai/stream/orderbooks",
        "https://mainnet.zklighter.elliot.ai/v1/orderbooks",
        "https://api.zklighter.com/orderbooks",
        "https://api.zklighter.com/api/v1/orderbooks",
    ]
    async with httpx.AsyncClient(verify=False, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for u in urls:
            try:
                r = await client.get(u)
                print(f"{u} -> {r.status_code}")
                if r.status_code == 200:
                    print("  Success:", len(r.json()), "items")
                else:
                    print("  Fail:", r.text[:100])
            except Exception as e:
                print(f"{u} -> ERROR: {e}")

if __name__ == '__main__':
    asyncio.run(main())
