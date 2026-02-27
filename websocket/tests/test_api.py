import urllib.request
import json
import logging

def main():
    try:
        req = urllib.request.Request("http://localhost:8000/api/markets?canonical_only=false")
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            exchanges = data.get("exchanges_queried", [])
            print(f"Exchanges queried: {exchanges}")
            
            counts = {}
            for m in data.get("markets", []):
                src = m.get("source", "unknown")
                counts[src] = counts.get(src, 0) + 1
                
            print(f"Source counts: {counts}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
