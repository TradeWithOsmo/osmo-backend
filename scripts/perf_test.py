import time
import requests
import sys

BASE_URL = "http://localhost:8000/api/usage"

def benchmark(name, url, params=None):
    start = time.time()
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        duration = (time.time() - start) * 1000
        data = response.json()
        count = len(data) if isinstance(data, list) else len(data.keys())
        print(f"[{name}] Status: {response.status_code} | Time: {duration:.2f}ms | Items: {count}")
        return duration
    except Exception as e:
        print(f"[{name}] Failed: {e}")
        return 0

def run_tests():
    print("--- Starting Performance Test ---\n")
    
    # 1. Fetch Providers (Frontend Initial Load)
    # This fetches the list of provider names. Should be fast if cached, slow if cold.
    print("1. Testing Get Providers (Initial Load)...")
    benchmark("Providers", f"{BASE_URL}/providers")
    
    # 2. Lazy Load a specific provider
    # Simulates user clicking on "Google" or "Anthropic"
    print("\n2. Testing Lazy Load (Specific Provider)...")
    benchmark("Provider: Anthropic", f"{BASE_URL}/models", {"provider": "Anthropic"})
    benchmark("Provider: Google", f"{BASE_URL}/models", {"provider": "Google"})
    
    # 3. Search
    # Simulates user typing "gpt"
    print("\n3. Testing Search (Filtering)...")
    benchmark("Search: 'gpt'", f"{BASE_URL}/models", {"search": "gpt"})
    benchmark("Search: 'claude'", f"{BASE_URL}/models", {"search": "claude"})

if __name__ == "__main__":
    try:
        run_tests()
    except requests.exceptions.ConnectionError:
        print("\nError: Could not connect to localhost:8000. Is the backend server running?")
