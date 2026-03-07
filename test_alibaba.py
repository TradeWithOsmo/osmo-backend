import asyncio
from agent.src.core.llm_factory import LLMFactory

async def test():
    try:
        print('Getting LLM: alibaba/qwen-plus')
        llm = LLMFactory.get_llm('alibaba/qwen-plus')
        print('Sending test message to Alibaba...')
        response = await llm.ainvoke('Halo, ini test message. Balas dengan tulisan "OK" saja.')
        print('=====================================')
        print(f'SUCCESS! Response from Alibaba: {response.content}')
        print('=====================================')
    except Exception as e:
        print(f'ERROR: {e}')

asyncio.run(test())
