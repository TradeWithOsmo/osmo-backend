"""
Qdrant Vector Store Connector

Provides direct access to Qdrant for Knowledge Base and RAG (Retrieval-Augmented Generation) operations.
Distinct from mem0 (which handles conversation memory).
"""

import os
import logging
from typing import Dict, Any, List, Optional, Callable, Union
from datetime import datetime

from ..base_connector import BaseConnector, ConnectorStatus

logger = logging.getLogger(__name__)

class QdrantConnector(BaseConnector):
    """
    Qdrant Connector for Knowledge Base & RAG
    
    Features:
    - Raw vector search for documents/knowledge
    - Collection management
    - Point operations (upsert, delete)
    - Supports both Embedded (Disk) and Server mode
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("qdrant", config)
        
        self.enabled = config.get("enabled", False)
        self.host = config.get("host", "memory")  # 'memory' or 'localhost' or path
        self.port = config.get("port", 6333)
        self.collection_name = config.get("collection_name", os.getenv("QDRANT_KB_COLLECTION", "osmo_knowledge_base"))
        self.embedding_dims = int(config.get("embedding_dims", os.getenv("KB_EMBEDDING_DIMS", "768")))
        self.api_key = config.get("api_key")
        
        self.client = None
        
        if self.enabled:
            try:
                from qdrant_client import QdrantClient
                from qdrant_client.models import VectorParams, Distance
                
                # Initialize client
                if self.host == "memory" or self.host.startswith("/") or ":" in self.host:
                    # Local/Embedded mode or Path
                    self.client = QdrantClient(location=self.host)
                    logger.info(f"✓ Qdrant initialized in local mode: {self.host}")
                else:
                    # HTTP/Server mode
                    self.client = QdrantClient(host=self.host, port=self.port, api_key=self.api_key)
                    logger.info(f"✓ Qdrant initialized in server mode: {self.host}:{self.port}")
                
                # Verify/Create collection
                if not self.client.collection_exists(self.collection_name):
                    self.client.create_collection(
                        collection_name=self.collection_name,
                        vectors_config=VectorParams(size=self.embedding_dims, distance=Distance.COSINE)
                    )
                    logger.info(f"✓ Created Qdrant collection: {self.collection_name}")
                
                self.status = ConnectorStatus.HEALTHY
                
            except ImportError:
                logger.error("qdrant-client not installed. Run: pip install qdrant-client")
                self.status = ConnectorStatus.OFFLINE
            except Exception as e:
                logger.error(f"Qdrant initialization failed: {e}")
                self.status = ConnectorStatus.ERROR
        else:
            self.status = ConnectorStatus.OFFLINE

    async def fetch(self, query: Union[str, List[float]], **kwargs) -> Dict[str, Any]:
        """
        Search for similar vectors.
        
        Args:
            query: Vector (List[float]) or ID to search
            **kwargs:
                - limit: Max results
                - score_threshold: Min similarity score
        """
        if not self.enabled or not self.client:
            return {"error": "Qdrant disabled"}
            
        limit = kwargs.get("limit", 5)
        score_threshold = kwargs.get("score_threshold", 0.0)
        
        try:
            # Note: This connector assumes the caller handles embedding generation
            # and passes the vector, OR this is a placeholder for ID fetch
            # For true RAG, we typically pass the vector here.
            
            # If query is just a string, this is a mock implementation because
            # Qdrant needs a VECTOR, not text. In a real heavy RAG connector,
            # we would integrate an Embedder here or expect `query` to be List[float].
            
            # For this MVP connector, we'll return a status/info or raw point if query is ID
            if isinstance(query, str):
                 # Assume query is a Point ID fetch
                 results = self.client.retrieve(
                     collection_name=self.collection_name,
                     ids=[query]
                 )
                 return self.normalize(results, "point_retrieval")

            elif isinstance(query, list):
                # Vector search
                results = self.client.search(
                    collection_name=self.collection_name,
                    query_vector=query,
                    limit=limit,
                    score_threshold=score_threshold
                )
                return self.normalize(results, "vector_search")
                
        except Exception as e:
             return {"error": str(e)}

    async def subscribe(self, callback: Callable, **kwargs) -> None:
        raise NotImplementedError("Qdrant does not support subscriptions")

    def normalize(self, raw_data: Any, data_type: str) -> Dict[str, Any]:
        return {
            "source": "qdrant",
            "type": data_type,
            "data": raw_data,
            "timestamp": datetime.now().isoformat()
        }
