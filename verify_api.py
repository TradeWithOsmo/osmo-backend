
import asyncio
import httpx
import sys
import os

async def test_backend_api():
    base_url = "http://localhost:8000"
    print(f"Testing Backend API at {base_url}...")
    
    async with httpx.AsyncClient() as client:
        # 1. Test Model list
        try:
            print("\n1. Testing /api/usage/models...")
            resp = await client.get(f"{base_url}/api/usage/models")
            if resp.status_code == 200:
                models = resp.json()
                groq_models = [m['id'] for m in models if 'groq' in m['id'].lower()]
                print(f"Found {len(models)} models total.")
                print(f"Groq models found: {groq_models}")
                if not groq_models:
                    print("ERROR: No Groq models in API response!")
            else:
                print(f"FAILED: Status {resp.status_code}")
        except Exception as e:
            print(f"ERROR connecting to API: {e}")

        # 2. Test Default Enabled Models
        try:
            print("\n2. Testing /api/usage/models/enabled/default...")
            resp = await client.get(f"{base_url}/api/usage/models/enabled/default")
            if resp.status_code == 200:
                defaults = resp.json()
                groq_defaults = [m for m in defaults if 'groq' in m.lower()]
                print(f"Default enabled models: {len(defaults)}")
                print(f"Groq in defaults: {groq_defaults}")
            else:
                print(f"FAILED: Status {resp.status_code}")
        except Exception as e:
            print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(test_backend_api())
