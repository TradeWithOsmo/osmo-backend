
import os
import requests
import json
import traceback

def test_direct_key():
    url = "https://openrouter.ai/api/v1/chat/completions"
    
    # Manually trying with the key from your .env file to be absolutely sure
    # This is from d:/WorkingSpace/backend/websocket/.env
    api_key = "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"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://tradewithosmo.com",
        "X-Title": "Osmo Debugger",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "google/gemini-2.0-flash-exp:free",
        "messages": [
            {"role": "user", "content": "Say hello"}
        ]
    }
    
    try:
        print(f"Sending direct request to {url}...")
        response = requests.post(url, headers=headers, json=data)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.text}")
        
        if response.status_code == 200:
            print("SUCCESS: Key is valid and working directly.")
        else:
            print("FAILURE: Key rejected by API directly.")
            
    except Exception as e:
        print(f"Request Exception: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    test_direct_key()
