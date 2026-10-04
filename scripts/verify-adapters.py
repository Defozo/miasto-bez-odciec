"""One bounded read of a public source through each configured fetch adapter."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingest.sources import safe_fetch, fetch_firecrawl

url = 'https://www.krakow.pl/'
results = []
for name, adapter in [('direct_https', safe_fetch), ('firecrawl', fetch_firecrawl)]:
    if name == 'firecrawl' and not os.getenv('FIRECRAWL_API_KEY'):
        results.append({'adapter': name, 'status': 'disabled_no_key'})
        continue
    if name == 'firecrawl':
        os.environ['SMART_CITY_ENABLE_FIRECRAWL'] = 'true'
    try:
        document = adapter(url)
        results.append({'adapter': name, 'status': 'verified', 'url': document['url'], 'sha256': document['sha256'], 'characters': len(document['text']), 'fetched_at': document['fetched_at'], 'publishes_restriction': False})
    except Exception as error:
        results.append({'adapter': name, 'status': 'unavailable', 'error_type': type(error).__name__, 'manual_entry_available': True})
report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'source': 'Public city homepage; transport content not asserted', 'results': results}
Path('artifacts/fetch-adapters.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report))
