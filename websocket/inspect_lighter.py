from lighter import ApiClient, OrderApi
import asyncio

async def inspect():
    api_client = ApiClient()
    order_api = OrderApi(api_client)
    methods = [m for m in dir(order_api) if not m.startswith('_')]
    print("Methods in OrderApi:")
    for m in methods:
        print(f" - {m}")
    await api_client.close()

if __name__ == "__main__":
    asyncio.run(inspect())
