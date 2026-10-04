import json
from sqlalchemy import select, func
from tests.api.test_flow import client, login, post


def event_rows(response):
    assert response.status_code == 200, response.text
    result = []
    for block in response.text.split('\n\n'):
        fields = dict(line.split(': ', 1) for line in block.splitlines() if ': ' in line)
        if 'event' in fields:
            result.append({**fields, 'data': json.loads(fields['data'])})
    return result


def test_openapi_required_mutation_fields_and_enums(client):
    schema = client.get('/openapi.json').json()
    components = schema['components']['schemas']
    assert set(components['SourceCreate']['required']) >= {'title', 'publisher'}
    assert set(components['ObservationCreate']['required']) >= {'expected_version', 'value', 'method', 'observed_at', 'valid_until'}
    assert components['ScenarioDecision']['properties']['status']['enum'] == ['approved_plan', 'in_progress', 'performed', 'effect_reviewed']
    assert components['ImportCreate']['properties']['format']['enum'] == ['osm', 'geojson', 'csv']
    assert 'invalidated_features' in components['RestrictionCreate']['properties']
    assert schema['paths']['/api/v1/reports']['post']['requestBody']['content']['application/json']['schema']['$ref'].endswith('/ReportCreate')


def test_typed_requests_keep_auth_and_reject_invalid_fields_before_writes(client):
    from services.api.db import Entity
    assert client.post('/api/v1/tasks', json={}).status_code == 401
    login(client)
    with client.test_db() as db:
        before = db.scalar(select(func.count()).select_from(Entity))
    post(client, '/sources', {'title': 'Missing publisher', 'raw_text': 'Data'}, expected=422)
    post(client, '/imports', {'format': 'executable', 'content': 'anything'}, expected=422)
    post(client, '/tasks', {'title': 'Bad type task', 'asset_id': 'crossing-y', 'property': 'unknown_parameter', 'method': 'Manual check'}, expected=422)
    post(client, '/scenarios', {'name': 'Invalid horizon', 'request': {'horizon': {'start': '2026-10-03T08:00:00+02:00'}}}, expected=422)
    with client.test_db() as db:
        assert db.scalar(select(func.count()).select_from(Entity)) == before
    created = post(client, '/scenarios', {'name': 'Typed request remains a dictionary', 'request': {'critical_relation_ids': [], 'time_limit_s': 15, 'weights': {'relation': 1.5}}}, expected=201)
    assert created['request']['weights'] == {'relation': 1.5}


def test_sse_public_versions_private_job_progress_and_reconnect(client):
    from services.api.db import Job, OutboxEvent
    with client.test_db() as db:
        job = Job(id='job-private-progress', kind='evaluation', layer='fixture', status='running', progress=33,
                  payload={'private': 'must-not-be-in-stream'}, result={'private_result': 'also-not-in-stream'})
        db.add(job)
        first = OutboxEvent(layer='fixture', event='data_published', version=41, data={'reason': 'test'})
        second = OutboxEvent(layer='fixture', event='data_published', version=42, data={'reason': 'test'})
        db.add_all([first, second]); db.commit()
        first_id, second_id = first.id, second.id
    public = client.get('/api/v1/events?once=true')
    assert any(row['event'] == 'snapshot' for row in event_rows(public))
    assert 'job-private-progress' not in public.text
    login(client, 'verifier')
    response = client.get('/api/v1/events?once=true', headers={'Last-Event-ID': str(first_id)})
    rows = event_rows(response)
    assert any(row['event'] == 'version' and row['id'] == str(second_id) and row['data']['data_version'] == 42 for row in rows)
    job = next(row['data'] for row in rows if row['event'] == 'job' and row['data']['id'] == 'job-private-progress')
    assert job['progress'] == 33 and job['status'] == 'running'
    assert 'must-not-be-in-stream' not in response.text and 'also-not-in-stream' not in response.text
    with client.test_db() as db:
        tracked = db.get(Job, 'job-private-progress'); tracked.progress = 100; tracked.status = 'completed'; db.commit()
    resumed = event_rows(client.get('/api/v1/events?once=true', headers={'Last-Event-ID': str(second_id)}))
    assert any(row['event'] == 'job' and row['data']['progress'] == 100 and row['data']['status'] == 'completed' for row in resumed)
    post(client, '/auth/logout', {})
    assert not any(row['event'] == 'job' for row in event_rows(client.get('/api/v1/events?once=true')))
    assert client.get('/api/v1/events?layer=scenario&once=true').status_code == 401
    assert client.get('/api/v1/events?once=true', headers={'Last-Event-ID': 'invalid'}).status_code == 422
