"""One origin local demo with persistent SQLite and independent durable worker.

Run in foreground, Ctrl+C stops only these children. Windows windows stay hidden.
"""
from pathlib import Path
import os
import json
import signal
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ.setdefault('SMART_CITY_LOCAL_DEMO_AUTH', 'true')
os.environ.setdefault('SMART_CITY_ORIGIN', 'http://127.0.0.1:8000')
os.environ.setdefault('SMART_CITY_PUBLIC_MODE', 'false')
os.environ.setdefault('SMART_CITY_WEB_DIST', str(ROOT/'apps/web/dist'))
worker_owner = 'worker-' + uuid.uuid4().hex
os.environ['SMART_CITY_WORKER_OWNER'] = worker_owner
from alembic.config import Config
from alembic import command
command.upgrade(Config('alembic.ini'), 'head')
from services.api.init_db import initialize
initialize(seed=True)
flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
processes = []
try:
    for args in ([sys.executable, '-m', 'uvicorn', 'services.api.main:app', '--host', '127.0.0.1', '--port', '8000', '--no-proxy-headers'], [sys.executable, '-m', 'services.worker.main']):
        processes.append(subprocess.Popen(args, creationflags=flags))
    deadline = time.monotonic()+600
    while time.monotonic() < deadline:
        if any(p.poll() is not None for p in processes):
            raise RuntimeError('A child process failed during startup')
        try:
            with urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2) as response:
                health = json.load(response)
                if response.status == 200 and health.get('worker', {}).get('status') == 'active' and health['worker'].get('owner') == worker_owner:
                    break
        except OSError:
            pass
        time.sleep(.5)
    else:
        raise RuntimeError('Readiness check failed')
    subprocess.run([sys.executable, 'scripts/smoke.py', '--output', 'artifacts/startup-acceptance.json'], check=True)
    print('Miasto bez odcięć: http://127.0.0.1:8000', flush=True)
    print('Controlled synthetic data. Local demo role login is enabled on loopback only.', flush=True)
    while all(p.poll() is None for p in processes):
        time.sleep(1)
    raise RuntimeError('Application process stopped unexpectedly')
except KeyboardInterrupt:
    pass
finally:
    for p in processes:
        if p.poll() is None:
            p.terminate()
    for p in processes:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
