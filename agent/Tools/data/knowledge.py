"""
Knowledge Base Tool (Qdrant)

Wraps Qdrant vector search for retrieving static knowledge (Strategies, Docs).
"""

import httpx
from typing import Dict, Any, List
from backend.agent.Config.tools_config import DATA_SOURCES

QDRANT_API = DATA_SOURCES.get("qdrant", "http://localhost:6333")

async def search_knowledge_base(query: str, collection: str = "strategies", limit: int = 3) -> List[Dict]:
    """
    Search the static knowledge base (RAG).
    """
    # This would typically use the qdrant-client or an HTTP endpoint wrapping it.
    # Current implementation is a placeholder pending RAG API exposure.
    return [
        {
            "score": 0.95,
            "content": "Example Strategy: Bull Flag Breakout - Buy when price breaks above upper resistance..."
        }
    ]
