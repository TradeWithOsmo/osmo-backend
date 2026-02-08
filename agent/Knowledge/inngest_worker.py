import os
import uuid
from typing import List, Dict, Any
from flask import Flask, request, jsonify
from inngest.flask import serve
from inngest import Inngest, Step
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
COLLECTION_NAME = os.getenv("QDRANT_KB_COLLECTION", "osmo_knowledge_base")

# Initialize Inngest
inngest_client = Inngest(app_id="osmo_agent")

app = Flask(__name__)

# Initialize Clients
qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
openai_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

def get_embedding(text: str) -> List[float]:
    """Generate embedding using OpenAI model via OpenRouter."""
    response = openai_client.embeddings.create(
        input=text,
        model="openai/text-embedding-3-small"
    )
    return response.data[0].embedding

async def upsert_to_qdrant(chunks: List[Dict[str, Any]]):
    """Batch upsert chunks to Qdrant."""
    points = []
    for chunk in chunks:
        vector = get_embedding(chunk['content'])
        points.append(models.PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload=chunk
        ))
    
    if points:
        qdrant_client.upsert(
            collection_name=COLLECTION_NAME,
            points=points
        )

@inngest_client.create_function(
    fn_id="ingest-markdown-file",
    trigger=inngest_client.Trigger(event="knowledge/markdown.upload"),
)
async def ingest_markdown(ctx, step: Step):
    file_path = ctx.event.data.get("file_path")
    category = ctx.event.data.get("category", "general")
    subcategory = ctx.event.data.get("subcategory", "general")
    
    if not os.path.exists(file_path):
        raise Exception(f"File not found: {file_path}")

    # Step 1: Read and Chunk (simulated as separate step for retries)
    async def process_file():
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
        
        filename = os.path.basename(file_path)
        chunks = []
        sections = text.split('\n## ')
        
        for i, section in enumerate(sections):
            if not section.strip(): continue
            content = "## " + section if i > 0 else section
            title = content.split('\n')[0].replace('#', '').strip()
            
            if len(content) < 50: continue
            
            chunks.append({
                "content": content,
                "metadata": {
                    "source": filename,
                    "category": category,
                    "subcategory": subcategory,
                    "title": title,
                    "chunk_id": i,
                    "type": "markdown"
                }
            })
        return chunks

    chunks = await step.run("read_and_chunk", process_file)
    
    # Step 2: Vectorize and Store
    await step.run("upsert_to_qdrant", lambda: upsert_to_qdrant(chunks))
    
    return {"status": "success", "chunks": len(chunks)}


# Register functions with Flask app
# Important: Inngest requires PUT/POST/GET handling on /api/inngest
app.add_url_rule(
    "/api/inngest",
    view_func=serve(app, inngest_client, [ingest_markdown]),
    methods=["GET", "POST", "PUT"]
)

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "ok", "service": "osmo-inngest-worker"}), 200

if __name__ == "__main__":
    print("🚀 Osmo Inngest Worker Started on port 8000")
    print("👉 Inngest Dev Server endpoint: http://localhost:8000/api/inngest")
    app.run(port=8000, debug=True)
