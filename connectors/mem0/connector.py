"""
mem0 Memory Connector - Self-Hosted with Qdrant

Full integration with mem0ai library for conversation storage and semantic search.
"""

import logging
import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ..base_connector import BaseConnector, ConnectorStatus


logger = logging.getLogger(__name__)


class Mem0Connector(BaseConnector):
    """
    Self-Hosted mem0 Memory Layer Connector.

    Features:
    - Persistent memory with mem0 library
    - Semantic search with Qdrant vector store
    - User-specific memory isolation
    - Multi-level memory (user, session, agent)
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__("mem0", config)

        self.enabled = config.get("enabled", False)
        self.openai_api_key = config.get("openai_api_key", os.getenv("OPENAI_API_KEY"))
        self.google_api_key = config.get("google_api_key", os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))

        self.mem0_llm_provider = str(config.get("mem0_llm_provider", os.getenv("MEM0_LLM_PROVIDER", "openai"))).strip().lower()
        self.mem0_embedder_provider = str(
            config.get("mem0_embedder_provider", os.getenv("MEM0_EMBEDDER_PROVIDER", "openai"))
        ).strip().lower()
        _is_google_llm = self.mem0_llm_provider in ("gemini", "google_genai")
        _is_google_embed = self.mem0_embedder_provider in ("gemini", "google_genai")
        self.mem0_llm_model = str(
            config.get(
                "mem0_llm_model",
                os.getenv("MEM0_LLM_MODEL", "gemini-2.0-flash" if _is_google_llm else "gpt-4o-mini"),
            )
        ).strip()
        self.mem0_embedder_model = str(
            config.get(
                "mem0_embedder_model",
                os.getenv(
                    "MEM0_EMBEDDER_MODEL",
                    "models/text-embedding-004" if _is_google_embed else "text-embedding-3-small",
                ),
            )
        ).strip()
        self.embedding_dims = int(
            config.get(
                "mem0_embedding_dims",
                os.getenv("MEM0_EMBEDDING_DIMS", "768" if _is_google_embed else "1536"),
            )
        )

        self.memory_client = None

        if self.enabled:
            self._init_memory_client()
        else:
            logger.info("mem0 connector disabled (set MEM0_ENABLED=true in .env)")
            self.status = ConnectorStatus.OFFLINE

    def _provider_api_key(self, provider: str) -> Optional[str]:
        p = (provider or "").strip().lower()
        return self.google_api_key if p in ("gemini", "google_genai") else self.openai_api_key

    def _init_memory_client(self) -> None:
        try:
            from mem0 import Memory

            mem0_config = {
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "collection_name": "osmo_memories",
                        "host": os.getenv("QDRANT_HOST", "memory"),
                        "port": int(os.getenv("QDRANT_PORT", 6333)),
                        "embedding_model_dims": self.embedding_dims,
                    },
                },
                "llm": {
                    "provider": self.mem0_llm_provider,
                    "config": {
                        "model": self.mem0_llm_model,
                        "temperature": 0.1,
                    },
                },
                "embedder": {
                    "provider": self.mem0_embedder_provider,
                    "config": {
                        "model": self.mem0_embedder_model,
                        "embedding_dims": self.embedding_dims,
                    },
                },
            }
            llm_api_key = self._provider_api_key(self.mem0_llm_provider)
            if llm_api_key:
                mem0_config["llm"]["config"]["api_key"] = llm_api_key

            embed_api_key = self._provider_api_key(self.mem0_embedder_provider)
            if embed_api_key:
                mem0_config["embedder"]["config"]["api_key"] = embed_api_key

            init_fn = getattr(Memory, "from_config", None)
            if init_fn:
                self.memory_client = Memory.from_config(mem0_config)
            else:
                self.memory_client = Memory(config=mem0_config)
            self.status = ConnectorStatus.HEALTHY
            logger.info(
                "mem0 connector enabled: "
                f"llm={self.mem0_llm_provider}/{self.mem0_llm_model}, "
                f"embedder={self.mem0_embedder_provider}/{self.mem0_embedder_model}, "
                f"dims={self.embedding_dims}"
            )
        except ImportError:
            logger.error("mem0ai not installed. Run: pip install mem0ai qdrant-client")
            self.status = ConnectorStatus.OFFLINE
        except Exception as e:
            logger.error(f"mem0 initialization failed: {e}")
            self.status = ConnectorStatus.OFFLINE

    async def fetch(self, user_id: str, **kwargs) -> Dict[str, Any]:
        """
        Fetch memories using semantic search.
        """
        if not self.enabled or not self.memory_client:
            return self.normalize(
                {
                    "user_id": user_id,
                    "results": [],
                    "error": "mem0 connector is disabled",
                },
                "search",
            )

        query = kwargs.get("query", "")
        limit = kwargs.get("limit", 5)

        try:
            results = self.memory_client.search(
                query=query,
                user_id=user_id,
                limit=limit,
            )

            return self.normalize(
                {
                    "user_id": user_id,
                    "query": query,
                    "results": results.get("results", []),
                    "count": len(results.get("results", [])),
                },
                "search",
            )

        except Exception as e:
            self.status = ConnectorStatus.ERROR
            raise Exception(f"mem0 search error: {e}")

    async def add_memory(
        self,
        user_id: str,
        messages: List[Dict],
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Add conversation to memory.
        """
        if not self.enabled or not self.memory_client:
            return {"stored": False, "error": "mem0 disabled"}

        try:
            result = self.memory_client.add(
                messages=messages,
                user_id=user_id,
                metadata=metadata or {},
            )

            return {
                "stored": True,
                "user_id": user_id,
                "memory_ids": result.get("results", []),
                "count": len(result.get("results", [])),
            }

        except Exception as e:
            logger.error(f"mem0 add error: {e}")
            return {"stored": False, "error": str(e)}

    async def get_all_memories(self, user_id: str) -> Dict[str, Any]:
        """
        Get all memories for a user.
        """
        if not self.enabled or not self.memory_client:
            return {"memories": [], "error": "mem0 disabled"}

        try:
            memories = self.memory_client.get_all(user_id=user_id)

            return {
                "user_id": user_id,
                "memories": memories.get("results", []),
                "count": len(memories.get("results", [])),
            }

        except Exception as e:
            logger.error(f"mem0 get_all error: {e}")
            return {"memories": [], "error": str(e)}

    async def subscribe(
        self,
        user_id: str,
        callback: Callable,
        **kwargs,
    ) -> None:
        """
        mem0 doesn't support real-time subscriptions.
        """
        raise NotImplementedError("mem0 doesn't support subscriptions. Use fetch() for memory retrieval.")

    def normalize(self, raw_data: Any, data_type: str) -> Dict[str, Any]:
        """Normalize memory data to standard format."""
        return {
            "source": self.name,
            "data_type": data_type,
            "timestamp": datetime.now().timestamp(),
            "data": raw_data,
        }

    def get_status(self) -> dict:
        """Get connector status."""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "status": self.status.value,
            "has_client": self.memory_client is not None,
            "mode": "self-hosted" if self.enabled else "disabled",
            "vector_store": "qdrant (in-memory)" if self.enabled else None,
            "llm_provider": self.mem0_llm_provider,
            "llm_model": self.mem0_llm_model,
            "embedder_provider": self.mem0_embedder_provider,
            "embedder_model": self.mem0_embedder_model,
            "embedding_dims": self.embedding_dims,
        }
