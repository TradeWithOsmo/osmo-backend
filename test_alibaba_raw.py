import requests
import json

api_key = 'sk-2114952a71b349ce894e645496fab105'
url = 'https://dashscope-intl.ap-southeast-1.aliyuncs.com/compatible-mode/v1/chat/completions'

headers = {
    'Authorization': f'Bearer {api_key}',
    'Content-Type': 'application/json'
}

data = {
    'model': 'qwen-plus',
    'messages': [{'role': 'user', 'content': 'Halo ini test API alibaba dari VPS.'}],
    'max_tokens': 10
}

print(f"Connecting to: {url}")
try:
    response = requests.post(url, headers=headers, json=data, timeout=30)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"Request failed: {e}")
