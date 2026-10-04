"""Consistent local SQLite + private evidence backup and isolated restore check."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from datetime import datetime, timezone

parser = argparse.ArgumentParser()
parser.add_argument('--db', default='.data/smart-city.db')
parser.add_argument('--storage', default='.data/storage')
parser.add_argument('--output', default='artifacts/private/backups')
parser.add_argument('--verify', action='store_true')
args = parser.parse_args()
source = Path(args.db).resolve()
if not source.is_file():
    raise SystemExit('Database does not exist')
target = Path(args.output).resolve()/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
target.mkdir(parents=True, exist_ok=False)
with sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True) as original, sqlite3.connect(target/'database.sqlite') as backup:
    original.backup(backup)
storage = Path(args.storage).resolve()
if storage.exists():
    shutil.copytree(storage, target/'evidence')
manifest = {'created_at': datetime.now(timezone.utc).isoformat(), 'files': {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*') if p.is_file()}}
if args.verify:
    with sqlite3.connect(target/'database.sqlite') as db:
        check = db.execute('PRAGMA integrity_check').fetchone()[0]
        counts = {name: db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        manifest['restore_check'] = {'integrity': check, 'table_counts': counts}
        if check != 'ok':
            raise SystemExit('Backup integrity check failed')
(target/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print(json.dumps({'backup': str(target), 'integrity': manifest.get('restore_check', {}).get('integrity'), 'files': len(manifest['files'])}))
