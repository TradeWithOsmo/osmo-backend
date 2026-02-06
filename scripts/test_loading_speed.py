import time
import requests
import sys

BASE_URL = "http://localhost:8000/api/usage"

def test_endpoint(name, url, params=None):
    print(f"--- Testing {name} ---")
    print(f"URL: {url}")
    try:
        start = time.time()
        response = requests.get(url, params=params)
        duration = (time.time() - start) * 1000
        print(f"Status: {response.status_code}")
        print(f"Time: {duration:.2f}ms")
        if response.status_code == 200:
            data = response.json()
            count = len(data) if isinstance(data, list) else len(data.keys())
            print(f"Item Count: {count}")
            if count > 0 and isinstance(data, list):
                print(f"First Item: {data[0]}")
        else:
            print(f"Error Response: {response.text[:500]}")
    except Exception as e:
        print(f"Exception: {e}")
    print("\n")

if __name__ == "__main__":
    test_endpoint("Providers", f"{BASE_URL}/providers")
    test_endpoint("Search GPT", f"{BASE_URL}/models", {"search": "gpt"})
    
