"""Wait for this deployment's worker initialization without exposing secrets."""
import argparse
from datetime import datetime
import json
import time
import urllib.error
import urllib.request


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--base", default="http://localhost:8000")
parser.add_argument("--started-after", help="Worker container StartedAt (ISO timestamp).")
parser.add_argument("--timeout", type=float, default=600)
args = parser.parse_args()
threshold = datetime.fromisoformat(args.started_after.replace("Z", "+00:00")).timestamp() if args.started_after else 0
deadline = time.monotonic()+args.timeout
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(args.base.rstrip("/")+"/health/ready", timeout=3) as response:
            health = json.load(response)
        worker = health.get("worker", {})
        solver = worker.get("solver", {})
        if health.get("status") == "ready" and worker.get("status") == "active" and worker.get("timestamp", 0) >= threshold and solver.get("status") in {"ready", "unavailable"}:
            print(json.dumps({"worker": worker["owner"], "solver": solver, "ready": True}))
            break
    except (OSError, ValueError):
        pass
    time.sleep(1)
else:
    raise SystemExit("Worker initialization timed out; inspect project worker logs.")
