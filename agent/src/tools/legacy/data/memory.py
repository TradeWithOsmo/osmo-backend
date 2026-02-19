"""
Memory Tool (mem0)

Wraps mem0 memory layer for user context and long-term memory.
"""

import httpx
from typing import Dict, Any, List, Optional
try:
    from agent.Config.tools_config import DATA_SOURCES
except Exception:
    from backend.agent.Config.tools_config import DATA_SOURCES

# Prefer direct mem0 API server; fallback to connectors route if needed.
MEM0_API = (DATA_SOURCES.get("mem0", "http://localhost:8888") or "").rstrip("/")
CONNECTORS_API = (DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors") or "").rstrip("/")
REQUEST_TIMEOUT_SEC = 8.0


def _memory_add_endpoints() -> List[str]:
    return [f"{MEM0_API}/memories", f"{CONNECTORS_API}/memory/add"]


def _memory_search_endpoints() -> List[str]:
    return [f"{MEM0_API}/search", f"{CONNECTORS_API}/memory/search"]


def _memory_list_endpoints(user_id: str) -> List[str]:
    return [f"{MEM0_API}/memories?user_id={user_id}", f"{CONNECTORS_API}/memory/all?user_id={user_id}"]


def _normalize_search_results(payload: Any) -> List[Dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            results = data.get("results")
            if isinstance(results, list):
                return results
        results = payload.get("results")
        if isinstance(results, list):
            return results
        if isinstance(data, list):
            return data
        return [payload]
    return [{"raw": payload}]


def _compact_error(error: Exception) -> str:
    text = str(error or "").strip()
    if not text:
        return error.__class__.__name__
    first_line = text.splitlines()[0].strip()
    # Strip verbose docs suffix from httpx errors.
    first_line = first_line.replace(" For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/", "")
    return first_line


async def _try_post_json(endpoints: List[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SEC) as client:
        for url in endpoints:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                return response.json() if response.content else {"ok": True}
            except Exception as error:
                errors.append(f"{url} -> {_compact_error(error)}")
    return {"error": " | ".join(errors) if errors else "Unknown memory route failure"}


async def _try_get_json(endpoints: List[str]) -> Dict[str, Any]:
    errors: List[str] = []
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SEC) as client:
        for url in endpoints:
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.json() if response.content else {"ok": True}
            except Exception as error:
                errors.append(f"{url} -> {_compact_error(error)}")
    return {"error": " | ".join(errors) if errors else "Unknown memory route failure"}


async def add_memory_messages(
    user_id: str,
    messages: List[Dict[str, str]],
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Store one or more messages for the user.
    """
    safe_messages = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user").strip().lower() or "user"
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        safe_messages.append({"role": role, "content": content})

    if not safe_messages:
        return {"error": "Memory store failed: empty messages payload."}

    payload = {
        "messages": safe_messages,
        "user_id": user_id,
        "metadata": metadata or {},
    }
    result = await _try_post_json(_memory_add_endpoints(), payload=payload)
    if isinstance(result, dict) and result.get("error"):
        return {"error": f"Memory store failed: {result.get('error')}"}
    return result if isinstance(result, dict) else {"result": result}


async def add_memory(user_id: str, text: str, metadata: Dict = None) -> Dict[str, Any]:
    """
    Store a new memory for the user.
    """
    return await add_memory_messages(
        user_id=user_id,
        messages=[{"role": "user", "content": text}],
        metadata=metadata or {},
    )


async def search_memory(user_id: str, query: str, limit: int = 5) -> Dict[str, Any]:
    """
    Search user's memory for relevant context.
    """
    safe_limit = max(1, min(int(limit or 5), 20))
    payload = {
        "user_id": user_id,
        "query": query,
        "limit": safe_limit,
        "filters": {"limit": safe_limit},
    }

    result = await _try_post_json(_memory_search_endpoints(), payload=payload)
    if isinstance(result, dict) and result.get("error"):
        return {
            "user_id": user_id,
            "query": query,
            "results": [],
            "error": f"Memory search failed: {result.get('error')}",
        }
    normalized = _normalize_search_results(result)
    trimmed = normalized[:safe_limit] if safe_limit > 0 else normalized
    return {
        "user_id": user_id,
        "query": query,
        "results": trimmed,
        "count": len(trimmed),
    }


async def get_recent_history(user_id: str, limit: int = 10) -> Dict[str, Any]:
    """
    Get recent interaction history.
    """
    safe_limit = max(1, min(int(limit or 10), 50))
    result = await _try_get_json(_memory_list_endpoints(user_id))
    if isinstance(result, dict) and result.get("error"):
        return {
            "user_id": user_id,
            "results": [],
            "error": f"Memory history fetch failed: {result.get('error')}",
        }

    items = result if isinstance(result, list) else result.get("memories") or result.get("results") or []
    if not isinstance(items, list):
        items = []
    trimmed = items[:safe_limit]
    return {
        "user_id": user_id,
        "results": trimmed,
        "count": len(trimmed),
    }
