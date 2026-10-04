"""Verify persistence across a restart of this Compose project's API and worker."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import httpx

parser = argparse.ArgumentParser()
parser.add_argument('--base', default='http://localhost:8087')
parser.add_argument('--flow', default='artifacts/live-flow-compose.json')
args = parser.parse_args()
flow = json.loads(Path(args.flow).read_text(encoding='utf-8'))
client = httpx.Client(base_url=args.base, timeout=10)
login = client.post('/api/v1/auth/login', json={'username': 'operator', 'password': os.environ['SMART_CITY_OPERATOR_PASSWORD']})
login.raise_for_status()
before = client.get('/api/v1/bootstrap').json()
previous_owner = client.get('/health/ready').json().get('worker', {}).get('owner')
subprocess.run(['docker', 'compose', 'restart', 'api', 'worker'], check=True)
deadline = time.monotonic()+600
while time.monotonic() < deadline:
    try:
        ready = client.get('/health/ready')
        worker = ready.json().get('worker', {}) if ready.status_code == 200 else {}
        if (worker.get('status') == 'active' and worker.get('owner')
                and worker['owner'] != previous_owner
                and worker.get('solver', {}).get('status') == 'ready'):
            break
    except httpx.HTTPError:
        pass
    time.sleep(1)
else:
    raise RuntimeError('API or worker did not recover')
after = client.get('/api/v1/bootstrap')
after.raise_for_status()
after = after.json()
checks = {'session_survives': after.get('user', {}).get('role') == 'operator',
          'new_worker_heartbeat': worker['owner'] != previous_owner,
          'solver_ready_before_acceptance': worker.get('solver', {}).get('status') == 'ready',
          'same_graph': before['graph']['version'] == after['graph']['version'],
          'versions_never_rewind': after['data_version'] >= before['data_version']}
for field in ('reports', 'tasks', 'scenarios', 'decisions'):
    checks[f'{field}_preserved'] = {r['id'] for r in before.get(field, [])} <= {r['id'] for r in after.get(field, [])}
if not all(checks.values()):
    raise AssertionError(checks)
result = {'success': True, 'checks': checks, 'tested_base': args.base, 'data_version_before': before['data_version'], 'data_version_after': after['data_version'], 'worker_status': ready.json()['worker']['status']}
Path('artifacts/restart-verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
