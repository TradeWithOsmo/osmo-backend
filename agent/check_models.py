import json
import os
import sys

import requests

API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
if not API_KEY:
    print("Missing OPENROUTER_API_KEY environment variable")
    sys.exit(1)

response = requests.get(
    "https://openrouter.ai/api/v1/models",
    headers={"Authorization": f"Bearer {API_KEY}"},
    timeout=30,
)
response.raise_for_status()

data = response.json()
print(f"Total models: {len(data.get('data', []))}")

# Check first 5 models structure
for i, model in enumerate(data.get("data", [])[:5]):
    print(f"\n--- Model {i + 1} ---")
    print(f"ID: {model.get('id')}")
    print(f"Name: {model.get('name')}")
    caps = model.get("capabilities", {})
    print(f"Capabilities: {json.dumps(caps, indent=2)}")
    print(f"Has tool_calling: {'tool_calling' in caps}")
    print(f"Has reasoning: {'reasoning' in caps}")
