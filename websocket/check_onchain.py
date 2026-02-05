
import asyncio
import sys
import os
import logging
logging.basicConfig(level=logging.INFO)
sys.path.append('d:\\WorkingSpace\\backend\\websocket')
from connectors.init_connectors import connector_registry

async def test():
    await connector_registry.initialize()
    conn = connector_registry.get_connector('onchain')
    if not conn:
        print("No onchain connector")
        return
    res = await conn.get_user_positions('0xC65870884989F6748aF9822f17b2758A48d97B79')
    print(res)

if __name__ == "__main__":
    asyncio.run(test())
