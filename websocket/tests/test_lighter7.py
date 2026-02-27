import asyncio
import json
from lighter import ApiClient, OrderApi

async def main():
    try:
        c = ApiClient()
        o = OrderApi(c)
        res = getattr(await o.order_books(), 'order_books')
        
        first = res[0]
        # Pydantic models usually have .json() or .dict()
        if hasattr(first, 'dict'):
            print(json.dumps(first.dict(), indent=2))
        elif hasattr(first, 'to_dict'):
            print(json.dumps(first.to_dict(), indent=2))
        else:
            print(first)
    finally:
        await c.close()

if __name__ == '__main__':
    asyncio.run(main())
