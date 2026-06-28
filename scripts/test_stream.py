"""测试 /qa/stream SSE 端点。"""
import json
import subprocess
import urllib.error
import urllib.request

result = subprocess.run(
    [r".venv\Scripts\python.exe", "scripts/create_dev_token.py", "--user-id", "demo", "--roles", "user,admin"],
    capture_output=True, text=True, encoding="utf-8"
)
token = next(line.strip() for line in result.stdout.splitlines() if line.strip().startswith("ey"))

body = json.dumps({"question": "龙族主角路明非有什么能力", "session_id": "stream-test-003"}).encode("utf-8")
req = urllib.request.Request(
    "http://127.0.0.1:8765/qa/stream",
    data=body,
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        print(f"Status: {resp.status}")
        print(f"Content-Type: {resp.headers.get('Content-Type')}")
        lines_read = 0
        for raw_line in resp:
            line = raw_line.decode("utf-8").rstrip()
            if line:
                print(line[:200])
                lines_read += 1
                if lines_read >= 20:
                    print("... (truncated)")
                    break
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode('utf-8')[:500]}")
