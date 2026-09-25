"""Live-server verification script — run after `uvicorn bot:app` is up."""
import urllib.request, json, time

BASE = "http://127.0.0.1:8080"

def do(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

time.sleep(1)  # let uvicorn warm up

PUSH_V1 = {
    "scope": "category",
    "context_id": "dentists",
    "version": 1,
    "payload": {"slug": "dentists"},
}
PUSH_V2 = {
    "scope": "category",
    "context_id": "dentists",
    "version": 2,
    "payload": {"slug": "dentists", "updated": True},
}

print("=== 1. healthz before any push ===")
s, r = do("GET", "/v1/healthz")
counts = r["contexts_loaded"]
print(f"  HTTP {s}  status={r['status']}  counts={counts}")
assert s == 200
assert counts == {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}

print()
print("=== 2. push category v1 (first time) ===")
s, r = do("POST", "/v1/context", PUSH_V1)
print(f"  HTTP {s}  accepted={r['accepted']}  ack_id={r['ack_id']}")
assert s == 200 and r["accepted"] is True

print()
print("=== 3. push category v1 AGAIN (idempotent) ===")
s, r = do("POST", "/v1/context", PUSH_V1)
print(f"  HTTP {s}  accepted={r['accepted']}  (no-op, same version)")
assert s == 200 and r["accepted"] is True

print()
print("=== 4. push category v2 (replaces v1) ===")
s, r = do("POST", "/v1/context", PUSH_V2)
print(f"  HTTP {s}  accepted={r['accepted']}  ack_id={r['ack_id']}")
assert s == 200 and r["accepted"] is True

print()
print("=== 5. push category v1 AFTER v2 (stale -> 409) ===")
s, r = do("POST", "/v1/context", PUSH_V1)
print(f"  HTTP {s}  accepted={r['accepted']}  reason={r['reason']}  current_version={r['current_version']}")
assert s == 409
assert r["accepted"] is False
assert r["reason"] == "stale_version"
assert r["current_version"] == 2

print()
print("=== 6. healthz after pushes (category count = 1) ===")
s, r = do("GET", "/v1/healthz")
counts = r["contexts_loaded"]
print(f"  HTTP {s}  counts={counts}")
assert counts["category"] == 1

print()
print("=== 7. metadata check ===")
s, r = do("GET", "/v1/metadata")
print(f"  HTTP {s}  team={r['team_name']}  model={r['model']}")
assert s == 200
for key in ("team_name", "team_members", "model", "approach", "contact_email", "version"):
    assert key in r, f"Missing key: {key}"

print()
print("ALL CHECKS PASSED")
