"""
Knowledge Base Ingestion Pipeline with Category Support
Ingests categorized markdown files into Qdrant vector database.
"""

import os
import sys
import uuid
from typing import List, Optional
from pathlib import Path
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
COLLECTION_NAME = os.getenv("QDRANT_KB_COLLECTION", "osmo_knowledge_base")
CONTENT_CATS_DIR = Path(__file__).parent / "ContectCats"

if not OPENROUTER_API_KEY:
    print("⚠️ Warning: OPENROUTER_API_KEY not found. Checking for OPENAI_API_KEY...")
    OPENROUTER_API_KEY = os.getenv("OPENAI_API_KEY")
    if not OPENROUTER_API_KEY:
        print("❌ Error: No API Key found (OPENROUTER_API_KEY or OPENAI_API_KEY).")
        sys.exit(1)

# Initialize Clients
qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

openai_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)


def get_embedding(text: str) -> List[float]:
    """Generate embedding using OpenRouter (routed to OpenAI model)."""
    response = openai_client.embeddings.create(
        input=text,
        model="openai/text-embedding-3-small"
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


def get_category_from_path(filepath: Path) -> str:
    """Extract category from file path."""
    parts = filepath.parts
    for i, part in enumerate(parts):
        if part == "ContectCats" and i + 1 < len(parts):
            return parts[i + 1]  # e.g., "01_identity"
    return "general"


def get_subcategory_from_path(filepath: Path) -> str:
    """Extract subcategory (filename without extension)."""
    return filepath.stem  # e.g., "product_awareness"


def chunk_markdown_with_category(
    text: str, 
    source: str, 
    category: str, 
    subcategory: str
) -> List[dict]:
    """
    Chunk markdown by headers with category metadata.
    """
    chunks = []
    # Split by '## ' to separate major sections
    sections = text.split('\n## ')
    
    for i, section in enumerate(sections):
        if not section.strip():
            continue
            
        # Re-add the '## ' unless it's the very first block
        content = "## " + section if i > 0 else section
        
        # Extract title from first line
        lines = content.split('\n')
        title = lines[0].replace('#', '').strip()
        
        # Skip if content is too short
        if len(content) < 50:
            continue
        
        chunks.append({
            "content": content,
            "metadata": {
                "source": source,
                "category": category,
                "subcategory": subcategory,
                "title": title,
                "chunk_id": i
            }
        })
    return chunks


def discover_knowledge_files(base_dir: Path) -> List[Path]:
    """Discover all markdown files in ContectCats directory."""
    files = []
    for md_file in base_dir.rglob("*.md"):
        files.append(md_file)
    return files


def create_collection():
    """Create Qdrant collection if not exists."""
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
        
        # Create payload indexes for filtering
        qdrant.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="metadata.category",
            field_schema=models.PayloadSchemaType.KEYWORD
        )
        qdrant.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="metadata.subcategory",
            field_schema=models.PayloadSchemaType.KEYWORD
        )
        print(f"  ✅ Collection created with category indexes.")
    else:
        print(f"ℹ️ Collection '{COLLECTION_NAME}' already exists.")


def ingest_categorized_files():
    """Ingest all files from ContectCats directory."""
    print(f"🚀 Starting Categorized Ingestion to Qdrant ({QDRANT_HOST}:{QDRANT_PORT})...")
    print(f"📁 Source: {CONTENT_CATS_DIR}")
    
    # Check if directory exists
    if not CONTENT_CATS_DIR.exists():
        print(f"❌ Error: Directory not found: {CONTENT_CATS_DIR}")
        sys.exit(1)
    
    # Create collection
    create_collection()
    
    # Discover files
    files = discover_knowledge_files(CONTENT_CATS_DIR)
    print(f"\n📄 Found {len(files)} markdown files.\n")
    
    if not files:
        print("⚠️ No files found. Exiting.")
        return
    
    total_chunks = 0
    
    # Process each file
    for filepath in files:
        filename = filepath.name
        category = get_category_from_path(filepath)
        subcategory = get_subcategory_from_path(filepath)
        
        print(f"📄 Processing: {category}/{filename}")
        
        text = read_markdown_file(str(filepath))
        if not text:
            continue
            
        chunks = chunk_markdown_with_category(
            text, 
            source=filename, 
            category=category, 
            subcategory=subcategory
        )
        print(f"   ↳ Found {len(chunks)} sections.")
        
        points = []
        for chunk in chunks:
            try:
                vector = get_embedding(chunk['content'])
                
                # Create Point with UUID
                points.append(models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload=chunk
                ))
            except Exception as e:
                print(f"   ❌ Error embedding chunk: {e}")
                continue
            
        # Upsert to Qdrant
        if points:
            try:
                operation_info = qdrant.upsert(
                    collection_name=COLLECTION_NAME,
                    points=points
                )
                print(f"   ✅ Upserted {len(points)} chunks. Status: {operation_info.status}")
                total_chunks += len(points)
            except Exception as e:
                print(f"   ❌ Error upserting: {e}")
            
    print(f"\n🎉 Ingestion Complete! Total {total_chunks} vectors stored in '{COLLECTION_NAME}'.")
    
    # Print summary by category
    print("\n📊 Summary by Category:")
    category_counts = {}
    for filepath in files:
        cat = get_category_from_path(filepath)
        category_counts[cat] = category_counts.get(cat, 0) + 1
    for cat, count in sorted(category_counts.items()):
        print(f"   • {cat}: {count} files")


def trigger_inngest_ingestion():
    """Trigger ingestion via Inngest events (For async/PDF processing)."""
    try:
        from backend.agent.Knowledge.inngest_worker import inngest_client
    except ImportError:
        try:
             # Fallback for when running directly within the module
             from inngest_worker import inngest_client
        except ImportError:
            print("❌ Error: inngest library not installed or worker not found.")
            return

    print("🚀 Triggering Inngest workflow for categorization...")
    files = discover_knowledge_files(CONTENT_CATS_DIR)
    
    events = []
    for filepath in files:
        category = get_category_from_path(filepath)
        subcategory = get_subcategory_from_path(filepath)
        
        try:
            rel_path = filepath.relative_to(CONTENT_CATS_DIR)
            file_path_to_send = str(rel_path)
        except ValueError:
            file_path_to_send = str(filepath)

        events.append({
            "name": "knowledge/markdown.upload",
            "data": {
                "file_path": file_path_to_send,
                "category": category,
                "subcategory": subcategory
            }
        })
    
    if events:
        import httpx
        # Send events to Inngest (Assumes Inngest is running locally or configured)
        # Note: In a production env, INNGEST_EVENT_KEY and INNGEST_URL are needed.
        async def send_events():
            async with httpx.AsyncClient() as client:
                await inngest_client.send(events)
        
        import asyncio
        asyncio.run(send_events())
        print(f"✅ Sent {len(events)} events to Inngest.")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Osmo Knowledge Ingestion")
    parser.add_argument("--clear", action="store_true", help="Clear collection before ingesting")
    parser.add_argument("--inngest", action="store_true", help="Use Inngest worker for ingestion")
    args = parser.parse_args()
    
    if args.clear:
        clear_collection()
    
    if args.inngest:
        trigger_inngest_ingestion()
    else:
        ingest_categorized_files()

