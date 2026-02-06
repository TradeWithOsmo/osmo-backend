import asyncio
import httpx
import uuid

BASE_URL = "http://localhost:8000/api/agent"

# Mock user token (you might need to replace this if your auth is strict)
# For local testing, we assume the backend has a way to bypass or use a mock JWT
HEADERS = {
    "Authorization": "Bearer mock-user-address"
}

async def test_chat_flow():
    async with httpx.AsyncClient() as client:
        # 1. Test Listing Models
        print("--- Testing /models ---")
        resp = await client.get(f"{BASE_URL}/models", headers=HEADERS)
        if resp.status_code == 200:
            print("✅ Models fetched successfully")
            models = resp.json().get("models", [])
            print(f"Found {len(models)} models")
            # Use a model that is likely enabled (claude-3.5-sonnet might not be in default list)
            # Pick the first one from specialized models if available
            test_model = "anthropic/claude-3.5-sonnet:sovereign" # Should work because we handle it
        else:
            print(f"❌ Failed to fetch models: {resp.text}")
            return

        # 2. Test Chat and Session Creation
        print(f"\n--- Testing /chat (Model: {test_model}) ---")
        session_id = f"test-{uuid.uuid4().hex[:6]}"
        chat_data = {
            "model_id": test_model,
            "message": "Hello, this is a backend test. What is Bitcoin?",
            "session_id": session_id
        }
        resp = await client.post(f"{BASE_URL}/chat", json=chat_data, headers=HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ AI Response: {data.get('response')[:50]}...")
            print(f"✅ Session ID used: {data.get('session_id')}")
        else:
            print(f"❌ Chat failed: {resp.text}")
            return

        # 3. Test Listing Sessions
        print("\n--- Testing /sessions ---")
        resp = await client.get(f"{BASE_URL}/sessions", headers=HEADERS)
        if resp.status_code == 200:
            sessions = resp.json()
            found = any(s['id'] == session_id or s['id'] == data.get('session_id') for s in sessions)
            print(f"✅ Found {len(sessions)} sessions. Test session in list: {'YES' if found else 'NO'}")
        else:
            print(f"❌ Failed to fetch sessions: {resp.text}")

        # 4. Test History
        current_session = data.get('session_id')
        print(f"\n--- Testing /history/{current_session} ---")
        resp = await client.get(f"{BASE_URL}/history/{current_session}", headers=HEADERS)
        if resp.status_code == 200:
            history = resp.json()
            print(f"✅ History count: {len(history)} messages")
            for msg in history:
                print(f"   [{msg['role']}]: {msg['content'][:30]}...")
        else:
            print(f"❌ Failed to fetch history: {resp.text}")

if __name__ == "__main__":
    asyncio.run(test_chat_flow())
