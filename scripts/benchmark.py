"""Measured fixture performance with explicit graph, request, and platform context."""
import argparse
from copy import deepcopy
import json
import platform
import os
import subprocess
from pathlib import Path
import statistics
import sys
from time import perf_counter
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain.graph import build_fixture, evaluate

def hardware():
    info = {'logical_processors': os.cpu_count(), 'processor': platform.processor(), 'dedicated_host': False}
    if os.name == 'nt':
        try:
            command = "@{processor=(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name);memory_bytes=(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory} | ConvertTo-Json -Compress"
            info.update(json.loads(subprocess.run(['powershell', '-NoProfile', '-Command', command], capture_output=True, text=True, timeout=30, check=True).stdout))
        except (subprocess.SubprocessError, ValueError):
            info['memory_bytes'] = None
    elif hasattr(os, 'sysconf'):
        info['memory_bytes'] = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    return info

parser = argparse.ArgumentParser()
parser.add_argument('--base', default='http://127.0.0.1:8000')
parser.add_argument('--scale', action='store_true')
args = parser.parse_args()
request = {'origin': 'origin-west', 'destination': 'clinic', 'profile': 'wheelchair', 'departure': '2026-10-03T07:00:00+02:00', 'layer': 'fixture'}
durations = []
with httpx.Client(base_url=args.base, timeout=30) as client:
    version = client.get('/api/v1/versions').json()
    for i in range(100):
        before = perf_counter()
        response = client.post('/api/v1/routes', json=request)
        response.raise_for_status()
        if response.json()['status'] != 'confirmed':
            raise RuntimeError('Fixture baseline route was not confirmed')
        durations.append((perf_counter()-before)*1000)
report = {'platform': platform.platform(), 'python': platform.python_version(), 'graph': version, 'data': 'synthetic_fixture',
          'hardware': hardware(),
          'route_requests': 100, 'route_p95_ms': round(sorted(durations)[94], 2), 'route_median_ms': round(statistics.median(durations), 2),
          'cache': 'No route-result cache; warmed process and database connection pool.', 'target_ms': 2000}
if args.scale:
    graph = build_fixture()
    base_origin = deepcopy(graph['nodes'][0])
    graph['origins'] = []
    for i in range(100):
        node = {**base_origin, 'id': f'load-origin-{i}'}
        graph['nodes'].append(node)
        graph['origins'].append(node)
        for edge in [e for e in list(graph['edges']) if e['u'] == 'origin-west']:
            graph['edges'].append({**edge, 'id': f'{edge["id"]}-load-{i}', 'u': node['id']})
    graph['places'] = [{**deepcopy(graph['places'][0]), 'id': f'load-place-{i}'} for i in range(20)]
    graph['entrances'] = [{**deepcopy(graph['entrances'][0]), 'id': f'load-entrance-{i}', 'place_id': f'load-place-{i}'} for i in range(20)]
    for i,p in enumerate(graph['places']):
        p['entrance_ids'] = [f'load-entrance-{i}']
    started = perf_counter()
    result = evaluate(graph, {'origins': [o['id'] for o in graph['origins']], 'destinations': [p['id'] for p in graph['places']], 'profiles': graph['profiles'], 'variants': [], 'include_work_impacts': False, 'time_limit_s': 25})
    report['scale'] = {'origins': 100, 'destinations': 20, 'profiles': 3, 'seconds': round(perf_counter()-started, 2), 'solver_status': result.get('solver_status'), 'metrics': result.get('baseline', {}).get('metrics'), 'target_seconds': 30, 'interpretation': 'A bounded incomplete result is not a lost route.'}
Path('artifacts/performance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False))
