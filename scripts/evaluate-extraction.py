"""Repeatable field-accuracy evaluation, separate from JSON schema success."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingest.sources import extract_candidate

parser = argparse.ArgumentParser()
parser.add_argument('--live', action='store_true')
parser.add_argument('--output', default='artifacts/extraction-evaluation.json')
args = parser.parse_args()
cases = json.loads(Path('fixtures/extraction-cases.json').read_text(encoding='utf-8'))
if args.live:
    os.environ['SMART_CITY_ENABLE_GROQ'] = 'true'

def evaluate(case):
    start = time.perf_counter()
    try:
        result = extract_candidate(case['text'], use_ai=args.live)
        candidate = result['candidate']
        return {'id': case['id'], 'schema_pass': True, 'impact_pass': candidate['pedestrian_impact'] == case['impact'] if args.live else None,
            'location_pass': case['location'].lower() in (candidate['location_text'] or '').lower() if args.live else None,
            'quote_pass': candidate['quote'] is None or candidate['quote'] in case['text'], 'manual_review_required': result['requires_geometry_review'],
            'flagged_for_correction': bool(result.get('review_warnings')),
            'dates_pass': (candidate['start'] == '2026-10-03T08:00:00+02:00' and candidate['end'] == '2026-10-03T14:00:00+02:00') if case['id'] == 10 and args.live else (candidate['start'] is None and candidate['end'] is None),
            'seconds': round(time.perf_counter()-start, 3), 'result': result}
    except Exception as exc:
        return {'id': case['id'], 'schema_pass': False, 'error': str(exc), 'seconds': round(time.perf_counter()-start, 3)}

with ThreadPoolExecutor(max_workers=3 if args.live else 1) as pool:
    rows = list(pool.map(evaluate, cases))
report = {'mode': 'live_groq' if args.live else 'manual_fallback', 'cases': len(rows),
    'schema_pass': sum(r.get('schema_pass') is True for r in rows),
    'impact_pass': sum(r.get('impact_pass') is True for r in rows) if args.live else None,
    'location_pass': sum(r.get('location_pass') is True for r in rows) if args.live else None,
    'flagged_for_correction': sum(r.get('flagged_for_correction') is True for r in rows),
    'manual_review_required': True, 'rows': rows}
Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k != 'rows'}))
