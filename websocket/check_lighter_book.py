from lighter import ApiClient, OrderApi
import asyncio

async def check_book():
    api_client = ApiClient()
    try:
        order_api = OrderApi(api_client)
        resp = await order_api.order_books()
        books = resp.order_books if hasattr(resp, "order_books") else []
        if books:
            book = books[0]
            d = book.dict() if hasattr(book, "dict") else book.__dict__
            print("Keys in book:", list(d.keys()))
            if 'asks' in d or 'bids' in d:
                print("Found asks/bids!")
                print(f"Asks count: {len(d.get('asks', []))}")
    finally:
        await api_client.close()

if __name__ == "__main__":
    asyncio.run(check_book())
