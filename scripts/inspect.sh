#!/usr/bin/env bash
# Inspect how QUASAR is running (API health, pipeline, recent runs, frontend).
set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8000}"
FRONTEND_BASE="${FRONTEND_BASE:-http://127.0.0.1:5173}"

echo "QUASAR inspect"
echo "=============="
echo "API base:      ${API_BASE}"
echo "Frontend base: ${FRONTEND_BASE}"
echo

if ! curl -fsS "${API_BASE}/health" >/tmp/quasar_health.json; then
  echo "[FAIL] API /health unreachable. Start with: bash scripts/dev.sh"
  exit 1
fi

python3 - <<'PY'
import json, os, urllib.request

api = os.environ.get("API_BASE", "http://127.0.0.1:8000")
fe = os.environ.get("FRONTEND_BASE", "http://127.0.0.1:5173")

def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.load(r)

health = get(f"{api}/health")
print(f"[OK]   /health -> {health['status']} | db={health['checks']['database']} | quantum={health['checks']['quantum_backend']} | env={health['checks']['environment']}")

inspect = get(f"{api}/api/v1/inspect")
print(f"[OK]   /api/v1/inspect -> {inspect['service']} v{inspect['version']}")
print()
print("How a request runs:")
for stage in inspect["pipeline"]:
    print(f"  {stage['step']}. {stage['name']}")
    print(f"     module: {stage['module']}")
    print(f"     {stage['description']}")
print()
print("Endpoints:")
for ep in inspect["endpoints"]:
    print(f"  - {ep}")
print()
runs = inspect.get("recent_runs") or []
if not runs:
    print("Recent runs: (none yet)")
else:
    print("Recent runs:")
    for run in runs:
        print(f"  - {run['run_id'][:8]}  {run['status']}  depot={run['depot_name']}  stops={run['stops_count']}")
print()
print("Notes:")
for n in inspect.get("notes") or []:
    print(f"  - {n}")
print()
try:
    urllib.request.urlopen(fe, timeout=5)
    print(f"[OK]   Frontend reachable at {fe}")
except Exception:
    print(f"[WARN] Frontend not reachable at {fe} (API-only is fine).")
print()
print(f"Docs: {api}/docs")
print(f"Inspect JSON: {api}/api/v1/inspect")
PY
