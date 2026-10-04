"""Fetch a bounded candidate audit area. No source tag becomes field evidence."""
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingest import import_osm, safe_fetch

parser = argparse.ArgumentParser()
parser.add_argument('--bbox', default='50.063,19.920,50.071,19.938', help='south,west,north,east WGS84')
parser.add_argument('--output', default='artifacts/osm-candidate.json')
args = parser.parse_args()
south, west, north, east = map(float, args.bbox.split(','))
if not (-90 <= south < north <= 90 and -180 <= west < east <= 180 and north-south <= .05 and east-west <= .05):
    raise SystemExit('Request one bounded candidate area (maximum0.05 degrees).')
query = f'[out:json][timeout:25];(way["highway"]({south},{west},{north},{east});node["entrance"]({south},{west},{north},{east}););(._;>;);out body;'
source = safe_fetch('https://overpass-api.de/api/interpreter', method='POST', body=urlencode({'data': query}), max_bytes=10_000_000, timeout=35)
payload = json.loads(source['text'])
graph = import_osm(payload, source['resolved_url'])
graph['source'].update(sha256=source['sha256'], fetched_at=source['fetched_at'], query=query)
target = Path(args.output)
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'path': str(target), 'nodes': len(graph['nodes']), 'edges': len(graph['edges']), 'entrances': len(graph['entrances']), 'warnings': len(graph['quality']['warnings']), 'confirmed_evidence': len(graph['evidence']), 'status': graph['status']}))
