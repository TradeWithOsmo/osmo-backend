
import asyncio
import httpx
import uuid

BASE_URL = "http://localhost:8000/api/agent"
HEADERS = {
    "Authorization": "Bearer mock-0x123"
}

async def test_chat():
    async with httpx.AsyncClient() as client:
        print(f"Testing Chat with Groq...")
        chat_data = {
            "model_id": "groq/openai/gpt-oss-120b",
            "message": "Halo, ini tes backend.",
            "session_id": f"test-{uuid.uuid4().hex[:6]}"
        }
        try:
            resp = await client.post(f"{BASE_URL}/chat", json=chat_data, headers=HEADERS, timeout=60.0)
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.text}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_chat())
