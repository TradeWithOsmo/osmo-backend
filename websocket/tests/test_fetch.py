import asyncio
import sys
import logging

logging.basicConfig(level=logging.DEBUG)

sys.path.append("/app")
from routers.markets import _fetch_exchange

async def main():
    print("Testing aster...")
    aster = await _fetch_exchange("aster")
    print("Aster len:", len(aster))
    if len(aster) > 0: print(aster[0])

    print("Testing avantis...")
    avantis = await _fetch_exchange("avantis")
    print("Avantis len:", len(avantis))

    print("Testing lighter...")
    lighter = await _fetch_exchange("lighter")
    print("Lighter len:", len(lighter))

    print("Testing vest...")
    vest = await _fetch_exchange("vest")
    print("Vest len:", len(vest))

if __name__ == "__main__":
    asyncio.run(main())
