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
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests
try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
except Exception:
    QdrantClient = None  # type: ignore[assignment]
    models = None  # type: ignore[assignment]

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore[assignment]
try:
    from fastembed import TextEmbedding
except Exception:
    TextEmbedding = None  # type: ignore[assignment]
from dotenv import load_dotenv

def _load_env_files() -> None:
    """
    Load environment files from common backend entrypoints so this tool works
    both in local runs and containerized websocket/inngest contexts.
    """
    this_file = Path(__file__).resolve()
    backend_root = this_file.parents[3]
    candidates = [
        Path.cwd() / ".env",
        backend_root / ".env",
        backend_root / "websocket" / ".env",
        backend_root / "inngest-py" / ".env",
    ]
    for env_path in candidates:
        try:
            if env_path.exists():
                load_dotenv(dotenv_path=env_path, override=False)
        except Exception:
            continue


_load_env_files()

# Configuration
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION_NAME = os.getenv("QDRANT_KB_COLLECTION", "osmo_knowledge_base").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
KB_EMBEDDING_PROVIDER = (
    os.getenv("KB_EMBEDDING_PROVIDER")
    or os.getenv("KB_EMBEDDER_PROVIDER")
    or "openrouter"
).strip().lower()
if KB_EMBEDDING_PROVIDER in {"local", "fastembed", "bge"}:
    _default_embedding_model = "BAAI/bge-small-en-v1.5"
    _default_embedding_dims = "384"
elif KB_EMBEDDING_PROVIDER == "gemini":
    _default_embedding_model = "models/text-embedding-004"
    _default_embedding_dims = "768"
else:
    _default_embedding_model = "qwen/qwen3-embedding-8b"
    _default_embedding_dims = "0"
KB_EMBEDDING_MODEL = os.getenv("KB_EMBEDDING_MODEL", _default_embedding_model).strip()
KB_EMBEDDING_DIMS = int(os.getenv("KB_EMBEDDING_DIMS", _default_embedding_dims))

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
_resolved_collection_name = None
_openai_client = None
_local_embedder = None


def _get_qdrant() -> QdrantClient:
    """Lazy load Qdrant client."""
    if QdrantClient is None:
        raise RuntimeError("qdrant_client dependency is not installed.")
    global _qdrant_client
    if _qdrant_client is None:
        host_candidates: List[str] = []
        if QDRANT_HOST:
            host_candidates.append(str(QDRANT_HOST).strip())
        if "localhost" not in {h.lower() for h in host_candidates}:
            host_candidates.append("localhost")

        last_error: Optional[Exception] = None
        for host in host_candidates:
            try:
                candidate = QdrantClient(host=host, port=QDRANT_PORT)
                candidate.get_collections()
                _qdrant_client = candidate
                break
            except Exception as exc:
                last_error = exc

        if _qdrant_client is None:
            raise RuntimeError(
                f"Unable to connect Qdrant host={QDRANT_HOST} port={QDRANT_PORT}: {last_error}"
            )
    return _qdrant_client


def _normalize_gemini_model_name(model_name: str) -> str:
    value = (model_name or "").strip()
    if value.startswith("models/"):
        return value[len("models/") :]
    return value


def _resolve_collection_name() -> str:
    global _resolved_collection_name
    if _resolved_collection_name:
        return _resolved_collection_name

    candidate_names: List[str] = []
    for value in [COLLECTION_NAME, "osmo_knowledge_base", "osmo_knowledge"]:
        clean = (value or "").strip()
        if clean and clean not in candidate_names:
            candidate_names.append(clean)

    collections = _get_qdrant().get_collections().collections
    available = {item.name for item in collections}
    for name in candidate_names:
        if name in available:
            _resolved_collection_name = name
            return _resolved_collection_name

    if candidate_names:
        _resolved_collection_name = candidate_names[0]
        return _resolved_collection_name

    raise RuntimeError(f"No Qdrant collection configured. Available collections: {sorted(available)}")


def _collection_vector_size() -> Optional[int]:
    try:
        info = _get_qdrant().get_collection(collection_name=_resolve_collection_name())
    except Exception:
        return None
    vectors_cfg = getattr(getattr(info, "config", None), "params", None)
    vectors = getattr(vectors_cfg, "vectors", None)
    if vectors is None:
        return None
    size = getattr(vectors, "size", None)
    if isinstance(size, int) and size > 0:
        return size
    if isinstance(vectors, dict):
        for _, params in vectors.items():
            named_size = getattr(params, "size", None)
            if isinstance(named_size, int) and named_size > 0:
                return named_size
    return None


def _resolve_target_dims() -> Optional[int]:
    if KB_EMBEDDING_DIMS > 0:
        return KB_EMBEDDING_DIMS
    return _collection_vector_size()


def _get_openai() -> OpenAI:
    """Lazy load OpenAI client."""
    if OpenAI is None:
        raise RuntimeError("openai dependency is not installed.")
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY/OPENAI_API_KEY is required for openai embedding mode.")
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )
    return _openai_client


def _get_local_embedder():
    """Lazy load local embedding model via FastEmbed."""
    if TextEmbedding is None:
        raise RuntimeError("fastembed dependency is not installed for local embedding mode.")
    global _local_embedder
    if _local_embedder is None:
        _local_embedder = TextEmbedding(model_name=KB_EMBEDDING_MODEL)
    return _local_embedder


def _embedding_openai(text: str, target_dims: Optional[int] = None) -> List[float]:
    response = _get_openai().embeddings.create(
        input=text,
        model=KB_EMBEDDING_MODEL,
    )
    vector = response.data[0].embedding
    return _fit_embedding_dims(vector, target_dims=target_dims)


def _fit_embedding_dims(vector: List[float], target_dims: Optional[int] = None) -> List[float]:
    dims = target_dims if target_dims is not None else KB_EMBEDDING_DIMS
    if dims <= 0:
        return vector
    if len(vector) == dims:
        return vector
    if len(vector) > dims:
        return vector[:dims]
    padded = list(vector)
    padded.extend([0.0] * (dims - len(padded)))
    return padded


def _embedding_local(text: str, target_dims: Optional[int] = None) -> List[float]:
    embedder = _get_local_embedder()
    vectors = list(embedder.embed([text]))
    if not vectors:
        raise RuntimeError("Local embedding response is empty.")
    first = vectors[0]
    if hasattr(first, "tolist"):
        vector = first.tolist()
    else:
        vector = list(first)
    return _fit_embedding_dims([float(v) for v in vector], target_dims=target_dims)


def _embedding_gemini(text: str, target_dims: Optional[int] = None) -> List[float]:
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY/GEMINI_API_KEY is required for gemini embedding mode.")
    primary_model = _normalize_gemini_model_name(KB_EMBEDDING_MODEL)
    model_candidates: List[str] = []
    for name in [primary_model, "gemini-embedding-001"]:
        clean = (name or "").strip()
        if clean and clean not in model_candidates:
            model_candidates.append(clean)

    last_error: Optional[Exception] = None
    for model_name in model_candidates:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:embedContent?key={GOOGLE_API_KEY}"
        )
        payload: Dict[str, Any] = {"content": {"parts": [{"text": text}]}}
        if model_name == "gemini-embedding-001" and (target_dims or KB_EMBEDDING_DIMS) > 0:
            payload["outputDimensionality"] = target_dims or KB_EMBEDDING_DIMS

        try:
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            values = (((data or {}).get("embedding") or {}).get("values")) or []
            if not values:
                raise RuntimeError("Gemini embedding response has no vector values.")
            return _fit_embedding_dims(values, target_dims=target_dims)
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Gemini embedding failed for all model candidates: {last_error}")


def _get_embedding(text: str) -> List[float]:
    """Generate embedding for search query using configured provider."""
    provider = (KB_EMBEDDING_PROVIDER or "openrouter").strip().lower()
    if provider == "openrouter":
        provider = "openai"
    target_dims = _resolve_target_dims()
    provider_order: List[str] = [provider]
    for candidate in ("openai", "gemini", "local"):
        if candidate not in provider_order:
            provider_order.append(candidate)

    last_error: Optional[Exception] = None
    for active in provider_order:
        try:
            if active in {"local", "fastembed", "bge"}:
                return _embedding_local(text, target_dims=target_dims)
            if active == "gemini":
                return _embedding_gemini(text, target_dims=target_dims)
            if active in {"openai", "openrouter"}:
                return _embedding_openai(text, target_dims=target_dims)
        except Exception as exc:
            last_error = exc
            continue

    raise RuntimeError(f"All embedding providers failed. Last error: {last_error}")


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
        if category and category in CATEGORY_MAP and models is not None:
            search_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="metadata.category",
                        match=models.MatchValue(value=CATEGORY_MAP[category])
                    )
                ]
            )
        
        collection_name = _resolve_collection_name()

        # Search Qdrant (compatible with both legacy and newer qdrant-client APIs).
        client = _get_qdrant()

        def _search_points(active_filter):
            if hasattr(client, "search"):
                return client.search(
                    collection_name=collection_name,
                    query_vector=query_vector,
                    query_filter=active_filter,
                    limit=top_k,
                    with_payload=True,
                )
            query_result = client.query_points(
                collection_name=collection_name,
                query=query_vector,
                query_filter=active_filter,
                limit=top_k,
                with_payload=True,
            )
            return getattr(query_result, "points", query_result)

        results = _search_points(search_filter)
        if search_filter is not None and not results:
            # Category naming can differ between datasets; fallback to unfiltered search.
            results = _search_points(None)
        
        # Format results
        formatted_results = []
        for hit in results:
            payload = getattr(hit, "payload", {}) or {}
            formatted_results.append({
                "score": round(float(getattr(hit, "score", 0.0) or 0.0), 4),
                "title": payload.get("metadata", {}).get("title", "Unknown"),
                "category": payload.get("metadata", {}).get("category", "general"),
                "subcategory": payload.get("metadata", {}).get("subcategory", ""),
                "content": payload.get("content", "")[:1500],  # Limit content length
                "source": payload.get("metadata", {}).get("source", "")
            })
        zero_similarity = bool(formatted_results) and all(item.get("score", 0.0) <= 0.0 for item in formatted_results)
        
        return {
            "status": "success",
            "query": query,
            "category_filter": category,
            "collection": collection_name,
            "results_count": len(formatted_results),
            "results": formatted_results,
            "warning": (
                "All similarity scores are zero. Knowledge vectors likely need re-indexing."
                if zero_similarity
                else None
            ),
            "warning_code": "zero_similarity" if zero_similarity else None,
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

    if result.get("warning_code") == "zero_similarity":
        return (
            "Knowledge base is connected, but index quality is invalid "
            "(all similarity scores = 0). Please re-ingest/re-embed documents "
            "to ensure accurate strategy retrieval."
        )
    
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
