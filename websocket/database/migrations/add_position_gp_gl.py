import asyncio
import sys
import os
from sqlalchemy import text

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database.connection import engine

async def migrate():
    print("Adding GP/GL columns to positions table...")
    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE positions ADD COLUMN gp FLOAT DEFAULT NULL;"))
            print("Added gp to positions")
        except Exception as e:
            print(f"Note: {e}")
            
        try:
            await conn.execute(text("ALTER TABLE positions ADD COLUMN gl FLOAT DEFAULT NULL;"))
            print("Added gl to positions")
        except Exception as e:
            print(f"Note: {e}")
            
        try:
            await conn.execute(text("ALTER TABLE positions ADD COLUMN gp_triggered BOOLEAN DEFAULT FALSE;"))
            print("Added gp_triggered to positions")
        except Exception as e:
            print(f"Note: {e}")
            
        try:
            await conn.execute(text("ALTER TABLE positions ADD COLUMN gl_triggered BOOLEAN DEFAULT FALSE;"))
            print("Added gl_triggered to positions")
        except Exception as e:
            print(f"Note: {e}")
            
    print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
