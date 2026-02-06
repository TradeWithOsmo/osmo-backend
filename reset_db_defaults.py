
import asyncio
import json
from database.connection import AsyncSessionLocal
from database.models import UserEnabledModels
from sqlalchemy import select, delete

async def reset_defaults():
    NEW_DEFAULTS = [
        'anthropic/claude-4.5-sonnet',
        'deepseek/deepseek-chat-v3.1',
        'google/gemini-3-pro',
        'openai/gpt-5.1',
        'x-ai/grok-4',
        'x-ai/grok-420',
        'moonshot/kimi-k2-thinking',
        'qwen/qwen-3-max',
        'groq/openai/gpt-oss-120b'
    ]
    
    print("Connecting to database...")
    async with AsyncSessionLocal() as session:
        # Delete existing global_default if it exists to let it fallback or just update it
        print("Updating global_default in database...")
        result = await session.execute(
            select(UserEnabledModels).filter(UserEnabledModels.user_address == "global_default")
        )
        record = result.scalars().first()
        
        models_json = json.dumps(NEW_DEFAULTS)
        if record:
            record.model_list = models_json
            print("Existing record updated.")
        else:
            record = UserEnabledModels(
                user_address="global_default",
                model_list=models_json
            )
            session.add(record)
            print("New record created.")
        
        await session.commit()
    print("Successfully reset global defaults.")

if __name__ == "__main__":
    import os
    import sys
    sys.path.append(os.getcwd())
    asyncio.run(reset_defaults())
