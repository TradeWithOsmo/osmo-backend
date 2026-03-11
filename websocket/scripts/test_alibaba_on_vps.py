import sys
import os

# Put backend and agent dirs in path
sys.path.append("/root/backend")
sys.path.append("/root/backend/agent")
sys.path.append("/root/backend/websocket")

from agent.src.core.llm_factory import LLMFactory
import asyncio

async def test_alibaba():
    print("Testing alibaba/qwen-max via LLMFactory...")
    try:
        llm = LLMFactory.get_llm(model_id="alibaba/qwen-max", temperature=0.7)
        print(f"Got LLM: {llm}")
        
        # Simple test message
        messages = [("user", "Hello, are you working?")]
        response = await llm.ainvoke(messages)
        print("--- Response ---")
        print(response.content)
        print("----------------")
        print("SUCCESS")
    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_alibaba())
