"""Live, persistent fixture acceptance flow. Uses psst-injected operator credentials.

Creates clearly identified synthetic records and leaves them for inspection.
No private tokens, passwords or session cookies are saved in the report.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import io
import os
from pathlib import Path
import time
import uuid
import httpx
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument('--base', default='http://127.0.0.1:8000')
parser.add_argument('--output', default='artifacts/live-flow.json')
parser.add_argument('--import-osm', action='store_true')
args = parser.parse_args()
checks, ids = [], {}
operator = httpx.Client(base_url=args.base, timeout=40)
resident = httpx.Client(base_url=args.base, timeout=40)
csrf = ''

def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def post(path, body, *, client=None, expected=200, key=None):
    client = client or operator
    response = client.post('/api/v1'+path, json=body, headers={'Idempotency-Key': key or str(uuid.uuid4()), **({'X-CSRF-Token': csrf} if client is operator and csrf else {})})
    if response.status_code != expected:
        detail = response.json().get('detail', 'Unexpected response')
        raise AssertionError(f'{path}: HTTP {response.status_code} expected {expected}: {detail}')
    return response.json()


def login(role='operator'):
    global csrf
    password = os.getenv(f'SMART_CITY_{role.upper()}_PASSWORD')
    if password:
        answer = post('/auth/login', {'username': role, 'password': password})
    else:
        answer = post('/auth/demo', {'role': role})
    csrf = answer['csrf_token']
    check(f'login_{role}', answer['user']['role'] == role)


route_body = {'origin': 'origin-west', 'destination': 'clinic', 'profile': 'wheelchair', 'departure': '2026-10-03T09:00:00+02:00', 'layer': 'fixture'}
def route():
    return post('/routes', route_body, client=resident)

def observation(feature, value, unit, with_photo=False):
    task = post('/tasks', {'title': f'Test odbiorowy: {feature}', 'asset_id': 'crossing-y', 'property': feature, 'unit': unit,
                          'method': 'Kontrolowany protokół syntetyczny', 'assignee': 'Weryfikator demonstracji',
                          'positive_effect': 'Potwierdzenie wyłącznie wskazanej cechy', 'negative_effect': 'Brak potwierdzenia tej cechy'}, expected=201)
    photo_id = None
    if with_photo:
        upload_key = str(uuid.uuid4())
        upload_path = '/api/v1/tasks/'+task['id']+'/photos'
        headers = {'X-CSRF-Token': csrf, 'Idempotency-Key': upload_key}
        files = {'file': ('synthetic-field-test.jpg', photo_bytes.getvalue(), 'image/jpeg')}
        uploaded = operator.post(upload_path, files=files, headers=headers)
        check('field_photo_upload', uploaded.status_code == 201)
        saved_photo = uploaded.json()
        photo_id = saved_photo['id']
        ids['field_photo'], ids['field_task'] = photo_id, task['id']
        check('field_photo_bound_to_task', saved_photo['task_id'] == task['id'] and saved_photo['layer'] == task['layer'])
        repeated = operator.post(upload_path, files=files, headers=headers)
        check('field_photo_idempotent', repeated.status_code == 201 and repeated.json()['id'] == photo_id)
        check('field_photo_is_not_public', resident.get('/api/v1/photos/'+photo_id).status_code == 401)
        restored_photo = operator.get('/api/v1/photos/'+photo_id)
        check('field_photo_metadata_removed', restored_photo.status_code == 200 and not Image.open(io.BytesIO(restored_photo.content)).getexif())
    observed_at = datetime.now(timezone.utc)
    result = post(f'/tasks/{task["id"]}/observe', {'expected_version': task['version'], 'value': value, 'unit': unit,
        'method': 'Kontrolowany protokół syntetyczny', 'observed_at': observed_at.isoformat(), 'valid_until': (observed_at+timedelta(hours=4)).isoformat(), 'work_minutes': 4,
        **({'photo_id': photo_id} if photo_id else {})})
    evidence = result['evidence']
    if photo_id:
        check('field_photo_preserved_in_evidence', evidence['photo_id'] == photo_id)
    published = post(f'/evidence/{evidence["id"]}/publish', {'expected_version': evidence['version'], 'reason': 'Zgodność protokołu i zakresu cechy sprawdzona w teście.'})
    check(f'evidence_{feature}_published', published['status'] == 'confirmed')
    return published

try:
    check('live_ready', operator.get('/health/ready').status_code == 200)
    check('resident_route_confirmed', route()['status'] == 'confirmed')
    check('unauthorized_mutation_rejected', resident.post('/api/v1/tasks', json={}).status_code == 401)
    idem = str(uuid.uuid4())
    body = {'asset_id': 'crossing-y', 'description': 'Test odbiorowy: podejrzenie przeszkody na przejściu.', 'kind': 'barrier'}
    report = post('/reports', body, client=resident, expected=201, key=idem)
    private_report_token = report['token']
    repeat = post('/reports', body, client=resident, expected=201, key=idem)
    ids['report'] = report['id']
    check('idempotent_report', report['id'] == repeat['id'])
    check('private_report_token_required', resident.get('/api/v1/reports/'+report['id']).status_code == 404)
    status = resident.get('/api/v1/reports/'+report['id'], headers={'X-Report-Token': report['token']})
    check('private_report_tracking', status.status_code == 200)
    photo_bytes = io.BytesIO()
    photo = Image.new('RGB', (12, 12), color=(50, 90, 130))
    exif = Image.Exif()
    exif[315] = 'Synthetic metadata that must be removed'
    photo.save(photo_bytes, format='JPEG', exif=exif)
    uploaded = resident.post('/api/v1/reports/'+report['id']+'/photos', files={'file': ('synthetic-test.jpg', photo_bytes.getvalue(), 'image/jpeg')},
        headers={'X-Report-Token': private_report_token, 'Idempotency-Key': str(uuid.uuid4())})
    check('private_photo_upload', uploaded.status_code == 201)
    ids['photo'] = uploaded.json()['id']
    check('photo_is_not_public', resident.get('/api/v1/photos/'+ids['photo']).status_code == 401)
    report = resident.get('/api/v1/reports/'+report['id'], headers={'X-Report-Token': private_report_token}).json()
    check('anonymous_report_does_not_change_route', route()['status'] == 'confirmed')
    login()
    private_photo = operator.get('/api/v1/photos/'+ids['photo'])
    check('private_photo_metadata_removed', private_photo.status_code == 200 and not Image.open(io.BytesIO(private_photo.content)).getexif())
    before = resident.get('/api/v1/versions').json()['data_version']
    published_at = time.perf_counter()
    report = post('/reports/'+report['id']+'/review', {'expected_version': report['version'], 'action': 'locate_warning',
        'reason': 'Położenie potwierdzone, stan wymaga oględzin.', 'start': '2026-10-03T09:00:00+02:00', 'end': '2026-10-03T13:00:00+02:00'})
    check('moderated_warning_invalidates_route', route()['status'] == 'possible')
    check('second_session_sees_version', resident.get('/api/v1/versions').json()['data_version'] > before)
    propagation_ms = round((time.perf_counter()-published_at)*1000, 2)
    check('version_visible_under_5_seconds', propagation_ms < 5000)
    post('/reports/'+report['id']+'/review', {'expected_version': 1, 'action': 'reject', 'reason': 'Test konfliktu wersji.'}, expected=409)
    check('stale_version_rejected', True)
    report = post('/reports/'+report['id']+'/review', {'expected_version': report['version'], 'action': 'reject',
        'reason': 'W teście potwierdzono błędne przypisanie podejrzenia. Zachowano historię.'})
    check('rejected_warning_restores_original_evidence', route()['status'] == 'confirmed')
    observation('width_m', 1.8, 'm', with_photo=True)
    scenario = post('/scenarios', {'name': 'Test odbiorowy: porównanie i zerowy efekt pomiaru', 'request': {}, 'assumptions': ['Dane syntetyczne. Ta próba nie wykonuje rzeczywistych robót.']}, expected=201)
    ids['scenario'] = scenario['id']
    versions = resident.get('/api/v1/versions').json()
    job = post(f'/scenarios/{scenario["id"]}/evaluate', {'expected_version': scenario['version']}, expected=202)
    deadline = time.monotonic()+60
    while time.monotonic() < deadline:
        completed = operator.get('/api/v1/jobs/'+job['job_id']).json()
        if completed['status'] in ('completed','failed','stale'):
            break
        time.sleep(.2)
    check('durable_worker_evaluation_complete', completed['status'] == 'completed')
    result = completed['result']
    baseline = result['baseline']['metrics']
    safe = next(v for v in result['variants'] if v['id'] == 'safe')
    check('baseline_whole_window_9_hours', baseline['unavailable_relation_hours'] == 9)
    check('instantaneous_8_hours_separate', baseline['instantaneous_lost_relation_hours'] == 8)
    check('safe_variant_recovers_9_hours', safe['recovered_relation_hours'] == 9 and safe['critical_satisfied'])
    check('touching_variant_violates_continuity', not next(v for v in result['variants'] if v['id'] == 'touching')['critical_satisfied'])
    check('evaluation_does_not_publish_facts', resident.get('/api/v1/versions').json() == versions)
    scenario = operator.get('/api/v1/scenarios/'+scenario['id']).json()
    for state in ('approved_plan', 'in_progress'):
        scenario = post(f'/scenarios/{scenario["id"]}/decision', {'expected_version': scenario['version'], 'status': state, 'variant_id': 'safe',
            'owner': 'DEFOZO SOFTWARE HOUSE', 'executor': 'Michał Kiełtyka', 'conditions': 'Potwierdzenie otwarcia X i pół godziny wspólnej drożności.'})
    post(f'/scenarios/{scenario["id"]}/decision', {'expected_version': scenario['version'], 'status': 'performed', 'evidence_ids': []}, expected=422)
    check('performance_requires_new_evidence', True)
    proof = observation('open', True, None)
    ids['proof'] = proof['id']
    for state in ('performed', 'effect_reviewed'):
        scenario = post(f'/scenarios/{scenario["id"]}/decision', {'expected_version': scenario['version'], 'status': state, 'evidence_ids': [proof['id']]})
    effect = operator.get('/api/v1/scenarios/'+scenario['id']+'/effects').json()
    actual = effect['after']['metrics']['available_relation_hours'] - effect['before']['metrics']['available_relation_hours']
    check('unchanged_infrastructure_reports_zero_effect', actual == 0)
    for fmt in ('json', 'csv', 'geojson'):
        exported = operator.get('/api/v1/exports/'+scenario['id'], params={'format': fmt})
        check('export_'+fmt, exported.status_code == 200 and private_report_token not in exported.text)
    check('audit_history_present', len(operator.get('/api/v1/audit').json()) > 0)
    login('verifier')
    post('/scenarios', {'name': 'Unauthorized role test'}, expected=403)
    check('verifier_cannot_plan_or_publish', True)
    if args.import_osm:
        login('admin')
        graph = json.loads(Path('artifacts/osm-candidate.json').read_text(encoding='utf-8'))
        staged = post('/graphs/staging', {'layer': 'observed', 'graph': graph}, expected=201)
        checked = post(f'/graphs/{staged["id"]}/validate', {'expected_version': staged['version']})
        ids['staged_osm_graph'] = staged['id']
        check('real_osm_graph_staged', checked['quality']['valid'])
        check('osm_has_no_confirmed_accessibility', not graph['evidence'])
    report = {'base_url': args.base, 'data_layer': 'fixture', 'completed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'checks': checks,
              'passed': len(checks), 'records': ids, 'version_propagation_ms': propagation_ms, 'observed_change_relation_hours': actual,
              'planned_recovered_relation_hours': safe['recovered_relation_hours'], 'public_network_verified': False}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
finally:
    operator.close()
    resident.close()
