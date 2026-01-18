"""
Memory Tool (mem0)

Wraps mem0 memory layer for user context and long-term memory.
"""

import httpx
from typing import Dict, Any, List
from backend.agent.Config.tools_config import DATA_SOURCES

# Using the mem0 independent service URL or the connectors API if integrated
MEM0_API = DATA_SOURCES.get("mem0", "http://localhost:8888")

async def add_memory(user_id: str, text: str, metadata: Dict = None) -> Dict[str, Any]:
    """
    Store a new memory for the user.
    """
    url = f"{MEM0_API}/memories"
    payload = {
        "messages": [{"role": "user", "content": text}],
        "user_id": user_id,
        "metadata": metadata or {}
    }
    
    async with httpx.AsyncClient() as client:
        try:
            # Check if mem0 service matches path expectations
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": f"Memory store failed: {str(e)}"}

async def search_memory(user_id: str, query: str, limit: int = 5) -> List[Dict]:
    """
    Search user's memory for relevant context.
    """
    url = f"{MEM0_API}/search"
    payload = {
        "user_id": user_id,
        "query": query,
        # 'limit' is not directly supported in current server request model, 
        # but we pass it just in case or if filters supports it.
        # "filters": {"limit": limit} 
    }
    
    async with httpx.AsyncClient() as client:
        # payload['user_id'] is query param for search usually, or body?
        # Check mem0 docs or server implementation. Standard mem0 server uses POST /search/
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return [{"error": str(e)}]

async def get_recent_history(user_id: str, limit: int = 10) -> List[Dict]:
    """
    Get recent interaction history.
    """
    # Placeholder
    return []
