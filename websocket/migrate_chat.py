
import asyncio
from sqlalchemy import text
from database.connection import AsyncSessionLocal

async def migrate():
    async with AsyncSessionLocal() as session:
        print("Starting manual migration...")
        
        # Add columns to chat_sessions
        try:
            await session.execute(text("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS model_id VARCHAR"))
            await session.execute(text("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS workspace_id VARCHAR"))
            print("✅ Added model_id and workspace_id to chat_sessions")
        except Exception as e:
            print(f"❌ Error updating chat_sessions: {e}")

        # Add columns to chat_messages
        try:
            await session.execute(text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS input_tokens INTEGER DEFAULT 0"))
            await session.execute(text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS output_tokens INTEGER DEFAULT 0"))
            await session.execute(text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS cost FLOAT DEFAULT 0.0"))
            print("✅ Added tokens and cost columns to chat_messages")
        except Exception as e:
            print(f"❌ Error updating chat_messages: {e}")

        # Add columns to chat_workspaces
        try:
            await session.execute(text("ALTER TABLE chat_workspaces ADD COLUMN IF NOT EXISTS icon VARCHAR"))
            await session.execute(text("ALTER TABLE chat_workspaces ADD COLUMN IF NOT EXISTS is_expanded BOOLEAN DEFAULT TRUE"))
            print("✅ Added icon and is_expanded to chat_workspaces")
        except Exception as e:
            print(f"❌ Error updating chat_workspaces: {e}")

        await session.commit()
        print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
