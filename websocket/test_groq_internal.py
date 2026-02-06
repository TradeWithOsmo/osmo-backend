
import os
import asyncio
from agent.Core.llm_factory import LLMFactory
from langchain_core.messages import HumanMessage

async def test_groq():
    api_key = os.getenv("GROQ_API_KEY")
    print(f"Using API Key: {api_key[:10]}...{api_key[-5:] if api_key else 'None'}")
    
    try:
        llm = LLMFactory.get_llm("groq/openai/gpt-oss-120b")
        print("Invoking LLM...")
        response = await llm.ainvoke([HumanMessage(content="Halo, jawab 'OK' saja.")])
        print(f"RESULT: {response.content}")
    except Exception as e:
        print(f"ERROR: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_groq())
