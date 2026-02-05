
import asyncio
import sys
import os

# Add backend/websocket to path
sys.path.append(os.path.abspath("backend/websocket"))

from database.connection import init_db
from database.models import LedgerAccount
from services.order_service import OrderService
from connectors.init_connectors import connector_registry
from config import settings

async def test_summary():
    user = "0xC65870884989F6748aF9822f17b2758A48d97B79" 
    
    # Init DB
    await init_db()
    
    # Init Connectors (Mock Redis if needed, or just let it fail gracefully as we test DB part mostly)
    try:
        await connector_registry.initialize(redis_url=settings.REDIS_URL)
    except Exception as e:
        print(f"Connector init warning: {e}")

    service = OrderService()
    try:
        print(f"Fetching positions for {user}...")
        result = await service.get_user_positions(user)
        print("--- RESULT ---")
        print("Summary:", result.get('summary'))
        print("Positions:", len(result.get('positions', [])))
    except Exception as e:
        print("Error:", e)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_summary())
