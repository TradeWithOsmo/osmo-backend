"""
mem0 Memory Connector - Self-Hosted with Qdrant

Full integration with mem0ai library for conversation storage and semantic search.
"""

import os
import logging
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime

from ..base_connector import BaseConnector, ConnectorStatus


logger = logging.getLogger(__name__)


class Mem0Connector(BaseConnector):
    """
    Self-Hosted mem0 Memory Layer Connector
    
    Features:
    - Persistent memory with mem0 library
    - Semantic search with Qdrant vector store
    - User-specific memory isolation
    - Multi-level memory (user, session, agent)
    
    Setup:
    - Requires: pip install mem0ai qdrant-client openai
    - Uses in-memory Qdrant by default (no external DB needed)
    - Configure OPENAI_API_KEY for embeddings
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("mem0", config)
        
        # Configuration
        self.enabled = config.get("enabled", False)
        self.openai_api_key = config.get("openai_api_key", os.getenv("OPENAI_API_KEY"))
        
        self.memory_client = None
        
        if self.enabled:
            try:
                from mem0 import Memory
                
                # Initialize mem0 with in-memory Qdrant
                mem0_config = {
                    "vector_store": {
                        "provider": "qdrant",
                        "config": {
                            "collection_name": "osmo_memories",
                            "host": os.getenv("QDRANT_HOST", "memory"),
                            "port": int(os.getenv("QDRANT_PORT", 6333)),
                        }
                    },
                    "llm": {
                        "provider": "openai",
                        "config": {
                            "model": "gpt-4o-mini",
                            "temperature": 0.1,
                            "api_key": self.openai_api_key
                        }
                    },
                    "embedder": {
                        "provider": "openai",
                        "config": {
                            "model": "text-embedding-3-small",
                            "api_key": self.openai_api_key
                        }
                    }
                }
                
                self.memory_client = Memory(config=mem0_config)
                self.status = ConnectorStatus.HEALTHY
                logger.info("✓ mem0 self-hosted mode enabled with Qdrant vector store")
                
            except ImportError:
                logger.error("mem0ai not installed. Run: pip install mem0ai qdrant-client")
                self.status = ConnectorStatus.OFFLINE
            except Exception as e:
                logger.error(f"mem0 initialization failed: {e}")
                self.status = ConnectorStatus.OFFLINE
        else:
            logger.info("mem0 connector disabled (set MEM0_ENABLED=true in .env)")
            self.status = ConnectorStatus.OFFLINE
    
    async def fetch(self, user_id: str, **kwargs) -> Dict[str, Any]:
        """
        Fetch memories using semantic search.
        
        Args:
            user_id: Wallet address or user ID
            **kwargs:
                - query: Search query for semantic search
                - limit: Max results to return (default 5)
        
        Returns:
            Normalized memory search results
        """
        if not self.enabled or not self.memory_client:
            return self.normalize({
                "user_id": user_id,
                "results": [],
                "error": "mem0 connector is disabled"
            }, "search")
        
        query = kwargs.get("query", "")
        limit = kwargs.get("limit", 5)
        
        try:
            # Search memories
            results = self.memory_client.search(
                query=query,
                user_id=user_id,
                limit=limit
            )
            
            return self.normalize({
                "user_id": user_id,
                "query": query,
                "results": results.get("results", []),
                "count": len(results.get("results", []))
            }, "search")
        
        except Exception as e:
            self.status = ConnectorStatus.ERROR
            raise Exception(f"mem0 search error: {e}")
    
    async def add_memory(
        self,
        user_id: str,
        messages: List[Dict],
        metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Add conversation to memory.
        
        Args:
            user_id: User/wallet ID
            messages: List of messages [{role, content}, ...]
            metadata: Optional metadata
        
        Returns:
            Result with memory IDs created
        """
        if not self.enabled or not self.memory_client:
            return {"stored": False, "error": "mem0 disabled"}
        
        try:
            # Add to mem0
            result = self.memory_client.add(
                messages=messages,
                user_id=user_id,
                metadata=metadata or {}
            )
            
            return {
                "stored": True,
                "user_id": user_id,
                "memory_ids": result.get("results", []),
                "count": len(result.get("results", []))
            }
        
        except Exception as e:
            logger.error(f"mem0 add error: {e}")
            return {"stored": False, "error": str(e)}
    
    async def get_all_memories(self, user_id: str) -> Dict[str, Any]:
        """
        Get all memories for a user.
        
        Args:
            user_id: User ID
        
        Returns:
            All memories for this user
        """
        if not self.enabled or not self.memory_client:
            return {"memories": [], "error": "mem0 disabled"}
        
        try:
            # Get all memories
            memories = self.memory_client.get_all(user_id=user_id)
            
            return {
                "user_id": user_id,
                "memories": memories.get("results", []),
                "count": len(memories.get("results", []))
            }
        
        except Exception as e:
            logger.error(f"mem0 get_all error: {e}")
            return {"memories": [], "error": str(e)}
    
    async def subscribe(
        self,
        user_id: str,
        callback: Callable,
        **kwargs
    ) -> None:
        """
        mem0 doesn't support real-time subscriptions.
        Memory operations are request/response based.
        """
        raise NotImplementedError(
            "mem0 doesn't support subscriptions. Use fetch() for memory retrieval."
        )
    
    def normalize(self, raw_data: Any, data_type: str) -> Dict[str, Any]:
        """Normalize memory data to standard format"""
        return {
            "source": self.name,
            "data_type": data_type,
            "timestamp": datetime.now().timestamp(),
            "data": raw_data
        }
    
    def get_status(self) -> dict:
        """Get connector status"""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "status": self.status.value,
            "has_client": self.memory_client is not None,
            "mode": "self-hosted" if self.enabled else "disabled",
            "vector_store": "qdrant (in-memory)" if self.enabled else None
        }
