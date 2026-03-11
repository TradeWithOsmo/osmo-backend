import requests
import os

key = "sk-2114952a71b349ce894e645496fab105"

def test_url(url):
    print(f"Testing {url}...")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}"
    }
    payload = {
        "model": "qwen-plus",
        "messages": [{"role": "user", "content": "hi"}]
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_url("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    test_url("https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions")
