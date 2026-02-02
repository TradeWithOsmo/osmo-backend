
import asyncio
import sys
import os
import random
from datetime import datetime, timedelta

# Adds websocket root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.connection import SessionLocal
from services.usage_service import usage_service

async def populate_usage():
    print("🚀 Populating Mock Usage Data...")
    
    # Change this to your wallet address if needed
    user_address = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e" 
    
    models = [
        {"name": "gpt-4o", "cost_per_token": 0.00001, "tokens_range": (500, 2000)},
        {"name": "claude-3.5-sonnet", "cost_per_token": 0.000003, "tokens_range": (800, 3000)},
        {"name": "gemini-1.5-pro", "cost_per_token": 0.000002, "tokens_range": (1000, 5000)},
        {"name": "deepseek-v3", "cost_per_token": 0.0000005, "tokens_range": (2000, 8000)},
    ]
    
    # Generate logs for past 30 days
    db = SessionLocal()
    usage_service.db = db # Inject session
    
    try:
        for i in range(30):
            date = datetime.utcnow() - timedelta(days=i)
            daily_requests = random.randint(5, 15)
            
            print(f"Generating {daily_requests} requests for {date.strftime('%Y-%m-%d')}...")
            
            for _ in range(daily_requests):
                model = random.choice(models)
                tokens = random.randint(*model["tokens_range"])
                cost = tokens * model["cost_per_token"]
                
                # Mock Log
                await usage_service.log_usage(
                    user_address=user_address,
                    model=model["name"],
                    input_tokens=int(tokens * 0.7),
                    output_tokens=int(tokens * 0.3),
                    cost=cost,
                    session_id=f"sess-{random.randint(1000,9999)}"
                )
        
        print("✅ usage data populated successfully!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(populate_usage())
