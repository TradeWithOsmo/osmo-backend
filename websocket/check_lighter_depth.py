from lighter import ApiClient, OrderApi
import asyncio

async def check_details():
    api_client = ApiClient()
    try:
        order_api = OrderApi(api_client)
        # Assuming market_id 1 is valid (usually BTC-USD)
        resp = await order_api.order_book_details(market_id=1)
        print("Details content keys:", list(resp.dict().keys()))
        d = resp.dict()
        if 'asks' in d:
            print(f"Asks: {len(d['asks'])}")
        if 'bids' in d:
            print(f"Bids: {len(d['bids'])}")
    finally:
        await api_client.close()

if __name__ == "__main__":
    asyncio.run(check_details())
