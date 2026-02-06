
import requests
import json

def check_models():
    try:
        response = requests.get("http://localhost:8000/api/usage/models")
        response.raise_for_status()
        models = response.json()
        
        print(f"Total Models: {len(models)}")
        
        # Check Anthropic models specifically
        anthropic = [m for m in models if 'claude' in m['id'].lower()]
        print("\n--- Anthropic Models ---")
        for m in anthropic:
            print(f"ID: {m['id']} | Name: {m['name']}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_models()
