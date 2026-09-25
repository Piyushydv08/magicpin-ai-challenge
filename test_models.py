import urllib.request
import json
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get("GEMINI_API_KEY")

def test_model(model):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = json.dumps({
        "contents": [{"parts": [{"text": "Hello"}]}],
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req)
        print(f"{model}: OK")
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        print(f"{model}: HTTP {e.code}\n{body}")

test_model("gemini-2.5-flash")
