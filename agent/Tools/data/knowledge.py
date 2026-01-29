"""
Knowledge Base Tool (Qdrant RAG)

Provides semantic search over the Osmo knowledge base for:
- Product awareness
- Drawing tools & rules
- Trade management
- Market analysis
- And more categories
"""

import os
from typing import Dict, Any, List, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Configuration
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
COLLECTION_NAME = "osmo_knowledge"

# Category mapping for user-friendly names
CATEGORY_MAP = {
    "identity": "01_identity",
    "drawing": "02_drawing_tools",
    "trade": "03_trade_management",
    "market": "04_market_analysis",
    "psychology": "05_psychology",
    "user": "06_user_adaptation",
    "experience": "07_experience",
}

# Initialize clients (lazy loading)
_qdrant_client = None
_openai_client = None


def _get_qdrant() -> QdrantClient:
    """Lazy load Qdrant client."""
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    return _qdrant_client


def _get_openai() -> OpenAI:
    """Lazy load OpenAI client."""
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )
    return _openai_client


def _get_embedding(text: str) -> List[float]:
    """Generate embedding for search query."""
    response = _get_openai().embeddings.create(
        input=text,
        model="openai/text-embedding-3-small"
    )
    return response.data[0].embedding


async def search_knowledge_base(
    query: str, 
    category: Optional[str] = None, 
    top_k: int = 3
) -> Dict[str, Any]:
    """
    Search the Osmo knowledge base for relevant information.
    
    This tool retrieves trading knowledge including:
    - Product capabilities ("What can you do?")
    - Drawing tool usage ("How to draw trendline?")
    - Trade management ("Where to place SL?")
    - Market analysis ("What market type is this?")
    
    Args:
        query: The question or topic to search for
        category: Optional filter - one of: identity, drawing, trade, market, psychology, user, experience
        top_k: Number of results to return (default 3)
    
    Returns:
        Dictionary with search results and metadata
    """
    try:
        # Generate query embedding
        query_vector = _get_embedding(query)
        
        # Build filter if category specified
        search_filter = None
        if category and category in CATEGORY_MAP:
            search_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="metadata.category",
                        match=models.MatchValue(value=CATEGORY_MAP[category])
                    )
                ]
            )
        
        # Search Qdrant
        results = _get_qdrant().search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector,
            query_filter=search_filter,
            limit=top_k,
            with_payload=True
        )
        
        # Format results
        formatted_results = []
        for hit in results:
            payload = hit.payload
            formatted_results.append({
                "score": round(hit.score, 4),
                "title": payload.get("metadata", {}).get("title", "Unknown"),
                "category": payload.get("metadata", {}).get("category", "general"),
                "subcategory": payload.get("metadata", {}).get("subcategory", ""),
                "content": payload.get("content", "")[:1500],  # Limit content length
                "source": payload.get("metadata", {}).get("source", "")
            })
        
        return {
            "status": "success",
            "query": query,
            "category_filter": category,
            "results_count": len(formatted_results),
            "results": formatted_results
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "query": query,
            "results": []
        }


async def get_drawing_guidance(tool_name: str) -> Dict[str, Any]:
    """
    Get specific guidance for a drawing tool.
    
    Args:
        tool_name: Name of the drawing tool (e.g., "trendline", "fib_retracement", "rectangle")
    
    Returns:
        Dictionary with tool-specific best practices
    """
    query = f"How to use {tool_name} drawing tool rules best practices"
    return await search_knowledge_base(query, category="drawing", top_k=2)


async def get_trade_management_guidance(topic: str) -> Dict[str, Any]:
    """
    Get trade management guidance.
    
    Args:
        topic: Topic like "stop loss", "take profit", "trailing", "entry"
    
    Returns:
        Dictionary with trade management rules
    """
    query = f"{topic} placement rules strategy"
    return await search_knowledge_base(query, category="trade", top_k=2)


async def get_market_context_guidance() -> Dict[str, Any]:
    """
    Get guidance on market context recognition.
    
    Returns:
        Dictionary with market analysis methodology
    """
    query = "market context classification trending ranging volatile"
    return await search_knowledge_base(query, category="market", top_k=2)


async def consult_strategy(question: str) -> str:
    """
    Consult the knowledge base and return a formatted answer.
    
    This is a high-level wrapper that searches and formats results
    for direct use in agent responses.
    
    Args:
        question: Natural language question about trading/drawing/etc.
    
    Returns:
        Formatted string with relevant knowledge
    """
    result = await search_knowledge_base(question, top_k=3)
    
    if result["status"] == "error":
        return f"❌ Error searching knowledge base: {result['error']}"
    
    if not result["results"]:
        return "❓ No relevant knowledge found for this query."
    
    # Format results
    output_parts = [f"📚 **Knowledge Found for:** \"{question}\"\n"]
    
    for i, r in enumerate(result["results"], 1):
        output_parts.append(f"\n### Result {i} (Score: {r['score']})")
        output_parts.append(f"**Source:** {r['category']}/{r['subcategory']}")
        output_parts.append(f"\n{r['content'][:1000]}")
        if len(r['content']) > 1000:
            output_parts.append("\n...[truncated]")
    
    return "\n".join(output_parts)


# Export all functions for tool registration
__all__ = [
    "search_knowledge_base",
    "get_drawing_guidance",
    "get_trade_management_guidance", 
    "get_market_context_guidance",
    "consult_strategy"
]
