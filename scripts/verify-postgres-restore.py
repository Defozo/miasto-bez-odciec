"""Restore a snapshot into a new isolated database, test integrity, drop only it."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess

def run(*args):
    result = subprocess.run(['docker', 'compose', 'exec', '-T', 'db', *args], capture_output=True, check=True, text=True)
    return result.stdout.strip()


def verify_application(database, evidence_archive):
    # The child receives only an isolated database name as an argument; existing
    # container credentials remain in its environment and never appear in output.
    code = '''
import hashlib, json, os, pathlib, tarfile, tempfile
from urllib.parse import quote
os.environ['DATABASE_URL']='postgresql+psycopg://smartcity:'+quote(os.environ['SMART_CITY_DB_PASSWORD'],safe='')+'@db:5432/'+os.environ['SMART_CITY_RESTORE_DB']
with tempfile.TemporaryDirectory(prefix='smartcity-restore-') as temporary:
    directory=pathlib.Path(temporary)
    restored=directory/'restored'
    restored.mkdir()
    with tarfile.open(os.environ['SMART_CITY_RESTORE_ARCHIVE']) as archive:
        originals={pathlib.Path(member.name).name:hashlib.sha256(archive.extractfile(member).read()).hexdigest() for member in archive.getmembers() if member.isfile() and member.name.endswith('.jpg')}
        archive.extractall(restored,filter='data')
    storage=restored/'evidence'
    copies={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in storage.glob('*.jpg')}
    assert originals==copies,'Restored evidence hashes differ'
    os.environ['STORAGE_PATH']=str(storage)
    from fastapi.testclient import TestClient
    from services.api.main import app
    from services.api.db import SessionLocal, Entity
    from sqlalchemy import select
    with TestClient(app) as client:
        assert client.get('/health/ready').status_code==200
        login=client.post('/api/v1/auth/login',json={'username':'operator','password':os.environ['SMART_CITY_OPERATOR_PASSWORD']})
        assert login.status_code==200,'Restored authentication failed'
        assert client.get('/api/v1/audit').status_code==200
        route=client.post('/api/v1/routes',json={'origin':'origin-west','destination':'clinic','profile':'wheelchair','departure':'2026-10-03T07:00:00+02:00','layer':'fixture'})
        assert route.status_code==200 and route.json()['status']=='confirmed','Restored route failed'
        with SessionLocal() as db:
            photos=list(db.scalars(select(Entity).where(Entity.kind=='photo')))
            scenarios=list(db.scalars(select(Entity).where(Entity.kind=='scenario')))
        for photo in photos:
            response=client.get('/api/v1/photos/'+photo.id)
            assert response.status_code==200,'Restored private photo missing'
            assert hashlib.sha256(response.content).hexdigest()==originals[photo.id+'.jpg']
        for scenario in scenarios:
            assert client.get('/api/v1/scenarios/'+scenario.id).status_code==200
    print(json.dumps({'ready':True,'authenticated':True,'route_confirmed':True,'audit_readable':True,'photos_restored_and_read':len(photos),'task_photos_restored_and_read':sum(bool(photo.data.get('task_id')) for photo in photos),'photo_hashes_match':True,'scenarios_read':len(scenarios)}))
'''
    result = subprocess.run(['docker', 'compose', 'exec', '-T', '-e', 'SMART_CITY_RESTORE_DB='+database, '-e', 'SMART_CITY_RESTORE_ARCHIVE='+evidence_archive, 'api', 'python', '-c', code], capture_output=True, check=True, text=True)
    return json.loads(result.stdout.strip().splitlines()[-1])

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--backup', type=Path, help='Directory created by backup-compose.ps1; defaults to its newest complete snapshot.')
args = parser.parse_args()
backup = args.backup
if backup is None:
    candidates = [path for path in Path('artifacts/private/backups').glob('*') if (path/'database.dump').is_file() and (path/'evidence.tar.gz').is_file()]
    if not candidates:
        parser.error('Run backup-compose.ps1 first, or pass --backup.')
    backup = max(candidates, key=lambda path: path.stat().st_mtime)
backup = backup.resolve()
archives = {name: backup/name for name in ('database.dump', 'evidence.tar.gz')}
for archive in archives.values():
    if not archive.is_file():
        parser.error(f'Missing backup archive: {archive.name}')
hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in archives.items()}
target = 'smartcity_restore_' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
assert target.startswith('smartcity_restore_') and target.replace('_', '').isalnum()
dump_path = '/tmp/'+target+'.dump'
evidence_path = '/tmp/'+target+'.tar.gz'
subprocess.run(['docker', 'compose', 'cp', str(archives['database.dump']), 'db:'+dump_path], check=True, capture_output=True)
subprocess.run(['docker', 'compose', 'cp', str(archives['evidence.tar.gz']), 'api:'+evidence_path], check=True, capture_output=True)
run('createdb', '-U', 'smartcity', target)
try:
    run('pg_restore', '-U', 'smartcity', '--no-owner', '--dbname', target, dump_path)
    query = "SELECT json_build_object('entities',(SELECT count(*) FROM entities),'audit',(SELECT count(*) FROM audit_events),'jobs',(SELECT count(*) FROM jobs),'postgis',postgis_version())"
    restored = json.loads(run('psql', '-U', 'smartcity', '-d', target, '-Atc', query))
    application = verify_application(target, evidence_path)
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'backup_snapshot': backup.name, 'archive_sha256': hashes, 'restored_database': target, 'counts': restored, 'application': application, 'success': True, 'original_database_modified': False}
    Path('artifacts/postgres-restore.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
finally:
    run('dropdb', '-U', 'smartcity', target)
