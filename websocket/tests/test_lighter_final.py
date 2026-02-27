import asyncio
import sys
sys.path.insert(0, '/app')

from Lighter.api_client import LighterAPIClient

async def main():
    c = LighterAPIClient()
    markets = await c.get_markets()
    print(f"Got {len(markets)} markets from Lighter")
    if markets:
        print("Sample:", markets[:3])

if __name__ == '__main__':
    asyncio.run(main())
