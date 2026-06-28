"""快速 QA 端对端测试。"""
import json
import subprocess
import urllib.error
import urllib.request

# Get token using the existing script
result = subprocess.run(
    [r".venv\Scripts\python.exe", "scripts/create_dev_token.py", "--user-id", "demo", "--roles", "user,admin"],
    capture_output=True, text=True, encoding="utf-8"
)
token = next(line.strip() for line in result.stdout.splitlines() if line.strip().startswith("ey"))

question = "龙族里的主角叫什么名字？他有什么特别的能力？"
body = json.dumps({"question": question, "session_id": "test-qa-direct-002"}).encode("utf-8")

req = urllib.request.Request(
    "http://127.0.0.1:8765/qa/ask",
    data=body,
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print(f"Answer:\n{data['answer'][:600]}")
        print(f"\nSources: {len(data['sources'])}")
        for s in data['sources'][:3]:
            print(f"  - {s['source']} (distance={s['distance']:.4f})")
        print(f"Refused: {data['refused']}")
except urllib.error.HTTPError as e:
    err_body = e.read().decode("utf-8", errors="replace")
    print(f"HTTP {e.code}: {err_body[:300]}")
