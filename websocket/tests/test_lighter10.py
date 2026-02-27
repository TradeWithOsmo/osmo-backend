import asyncio
import lighter
from lighter import ApiClient, OrderApi

async def main():
    print("APIs:")
    for m in dir(lighter):
        if m.endswith('Api'):
            print("-", m)
    
    c = ApiClient()
    o = OrderApi(c)
    print("OrderApi methods with 'book':")
    for m in dir(o):
        if 'book' in m.lower():
            print("-", m)

if __name__ == '__main__':
    asyncio.run(main())
