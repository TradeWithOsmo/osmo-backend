
import os
import sys
from typing import List
from qdrant_client import QdrantClient
from qdrant_client.http import models
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Configuration
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
COLLECTION_NAME = "osmo_knowledge"

if not OPENROUTER_API_KEY:
    # Fallback checking/warning
    print("⚠️ Warning: OPENROUTER_API_KEY not found. Checking for OPENAI_API_KEY...")
    OPENROUTER_API_KEY = os.getenv("OPENAI_API_KEY")
    if not OPENROUTER_API_KEY:
        print("❌ Error: No API Key found (OPENROUTER_API_KEY or OPENAI_API_KEY).")
        sys.exit(1)

# Initialize Clients
qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

# OpenRouter Configuration
openai_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

def get_embedding(text: str) -> List[float]:
    """Generate embedding using OpenRouter (routed to OpenAI model)."""
    response = openai_client.embeddings.create(
        input=text,
        model="openai/text-embedding-3-small" # Explicit OpenRouter model ID
    )
    return response.data[0].embedding

def read_markdown_file(filepath: str) -> str:
    """Read content of a markdown file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"❌ Error reading file {filepath}: {e}")
        return ""

def chunk_markdown(text: str, source: str) -> List[dict]:
    """
    Simple chunking strategy: Split by headers (##).
    In a real system, we might use LangChain's MarkdownSplitter.
    """
    chunks = []
    # Split by '## ' to separate major sections
    sections = text.split('\n## ')
    
    for i, section in enumerate(sections):
        if not section.strip():
            continue
            
        # Re-add the '## ' unless it's the very first block if it didn't start with one
        content = "## " + section if i > 0 else section
        
        # Extract title purely for metadata (first line)
        lines = content.split('\n')
        title = lines[0].replace('#', '').strip()
        
        chunks.append({
            "content": content,
            "metadata": {
                "source": source,
                "title": title,
                "chunk_id": i
            }
        })
    return chunks

def ingest_files(file_paths: List[str]):
    print(f"🚀 Starting Ingestion to Qdrant ({QDRANT_HOST}:{QDRANT_PORT})...")
    
    # 1. Create Collection if not exists
    collections = qdrant.get_collections().collections
    exists = any(c.name == COLLECTION_NAME for c in collections)
    
    if not exists:
        print(f"📦 Creating collection '{COLLECTION_NAME}'...")
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=1536,  # OpenAI text-embedding-3-small dimension
                distance=models.Distance.COSINE
            )
        )
    else:
        print(f"ℹ️ Collection '{COLLECTION_NAME}' already exists.")

    total_chunks = 0
    
    # 2. Process Files
    for path in file_paths:
        filename = os.path.basename(path)
        print(f"\n📄 Processing: {filename}")
        
        text = read_markdown_file(path)
        if not text:
            continue
            
        chunks = chunk_markdown(text, source=filename)
        print(f"   ↳ Found {len(chunks)} sections.")
        
        points = []
        for chunk in chunks:
            vector = get_embedding(chunk['content'])
            
            # Create Point
            points.append(models.PointStruct(
                id=None, # Auto-generate UUID
                vector=vector,
                payload=chunk
            ))
            
        # 3. Upsert to Qdrant
        if points:
            # Upsert in batch
            operation_info = qdrant.upsert(
                collection_name=COLLECTION_NAME,
                points=points
            )
            print(f"   ✅ Upserted {len(points)} chunks. Status: {operation_info.status}")
            total_chunks += len(points)
            
    print(f"\n🎉 Ingestion Complete! Total {total_chunks} vectors stored in '{COLLECTION_NAME}'.")

if __name__ == "__main__":
    # Define files to ingest
    base_dir = r"d:\WorkingSpace"
    files = [
        os.path.join(base_dir, "Overview", "Product detail", "PRODUCT.md"),
        os.path.join(base_dir, "Overview", "dev - updete", "dev - updete.md")
    ]
    
    ingest_files(files)
