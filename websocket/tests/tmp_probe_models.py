import asyncio, os, httpx
from services.openrouter_service import openrouter_service

async def main():
    models = await openrouter_service.get_models()
    ids=[m.get('id') for m in models if m.get('id')]
    print('models_count', len(ids))
    test_ids = ids[:40]
    headers={
      'Authorization': f"Bearer {os.getenv('OPENROUTER_API_KEY','').strip()}",
      'Content-Type':'application/json',
      'HTTP-Referer':'https://tradewithosmo.com',
      'X-Title':'Osmo Trading Terminal',
    }
    bad=[]
    async with httpx.AsyncClient(timeout=30.0) as c:
      for mid in test_ids:
        payload={'model':mid,'messages':[{'role':'user','content':'ping'}],'max_tokens':8}
        try:
          r=await c.post('https://openrouter.ai/api/v1/chat/completions',headers=headers,json=payload)
          if r.status_code>=400:
            bad.append((mid,r.status_code,(r.text or '')[:160].replace('\n',' ')))
        except Exception as e:
          bad.append((mid,'ERR',str(e)[:160]))
    print('bad_count',len(bad))
    for item in bad:
      print(item)

asyncio.run(main())
