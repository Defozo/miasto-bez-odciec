import copy
import io
import time
import uuid
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

@pytest.fixture
def client(tmp_path, monkeypatch):
    from services.api import db, init_db
    from services.worker import main as worker
    engine = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", factory)
    monkeypatch.setattr(init_db, "engine", engine)
    monkeypatch.setattr(init_db, "SessionLocal", factory)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setenv("SMART_CITY_LOCAL_DEMO_AUTH", "true")
    monkeypatch.setenv("SMART_CITY_PUBLIC_MODE", "false")
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.delenv("SMART_CITY_OPERATOR_PASSWORD", raising=False)
    monkeypatch.delenv("SMART_CITY_VERIFIER_PASSWORD", raising=False)
    monkeypatch.delenv("SMART_CITY_ADMIN_PASSWORD", raising=False)
    from services.api.main import app
    with TestClient(app) as c:
        c.test_db = factory
        c.csrf = None
        yield c
    engine.dispose()

def post(client, path, body, key=None, expected=200):
    headers = {"Idempotency-Key": key or str(uuid.uuid4())}
    if client.csrf:
        headers["X-CSRF-Token"] = client.csrf
    response = client.post("/api/v1"+path, json=body, headers=headers)
    assert response.status_code == expected, response.text
    return response.json()

def login(client, role="operator"):
    result = client.post("/api/v1/auth/demo", json={"role": role})
    assert result.status_code == 200, result.text
    client.csrf = result.json()["csrf_token"]

def route(client):
    return post(client, "/routes", {"origin": "origin-west", "destination": "clinic", "profile": "wheelchair", "departure": "2026-10-03T09:00:00+02:00"})

def task_observation(client, feature="width_m", value=1.8, observed_at="2026-10-03T08:00:00+02:00"):
    task = post(client, "/tasks", {"title": "Kontrola jedynego obejścia", "asset_id": "crossing-y", "property": feature, "unit": "m" if feature == "width_m" else None, "method": "Pomiar taśmą" if feature == "width_m" else "Obserwacja otwarcia w terenie", "positive_effect": "Potwierdzenie obejścia", "negative_effect": "Bariera"}, expected=201)
    observed = post(client, f"/tasks/{task['id']}/observe", {"expected_version": task["version"], "value": value, "unit": task["unit"], "method": task["method"], "observed_at": observed_at, "valid_until": "2026-10-03T23:00:00+02:00"})
    return observed["evidence"]

def test_report_moderation_field_evidence_and_private_tracking(client):
    assert route(client)["status"] == "confirmed"
    key = str(uuid.uuid4())
    body = {"description": "Przejście jest węższe niż pokazuje aplikacja.", "asset_id": "crossing-y", "kind": "measurement", "feature": "width_m"}
    report = post(client, "/reports", body, key=key, expected=201)
    duplicate = post(client, "/reports", body, key=key, expected=201)
    assert duplicate["id"] == report["id"] and duplicate["token"] == report["token"]
    assert route(client)["status"] == "confirmed"
    assert client.get(f"/api/v1/reports/{report['id']}").status_code == 404
    assert client.get(f"/api/v1/reports/{report['id']}?token={report['token']}").json()["status"] == "submitted"
    login(client)
    reviewed = post(client, f"/reports/{report['id']}/review", {"expected_version": 1, "action": "locate_warning", "reason": "Sprawdzono położenie zgłoszonego przejścia"})
    assert route(client)["status"] == "possible"
    assert reviewed["status"] == "located_unverified"
    evidence = task_observation(client)
    assert evidence["status"] == "pending_review"
    published = post(client, f"/evidence/{evidence['id']}/publish", {"expected_version": evidence["version"], "reason": "Sprawdzono protokół i jednostkę pomiaru"})
    assert published["status"] == "confirmed"
    report = post(client, f"/reports/{report['id']}/review", {"expected_version": reviewed["version"], "action": "confirm", "evidence_id": evidence["id"], "reason": "Pomiar potwierdza szerokość obejścia"})
    assert report["status"] == "confirmed"
    assert route(client)["status"] == "confirmed"

def test_auth_version_csrf_and_layer_isolation(client):
    assert client.post("/api/v1/scenarios", json={"name": "Unauthorized"}).status_code == 401
    login(client, "verifier")
    post(client, "/scenarios", {"name": "Unauthorized"}, expected=403)
    login(client)
    assert client.post("/api/v1/scenarios", json={"name": "No CSRF"}).status_code == 403
    assert client.post("/api/v1/scenarios", json={"name": "No idempotency"}, headers={"X-CSRF-Token": client.csrf}).status_code == 428
    post(client, "/scenarios", {"name": "Real world write", "layer": "observed"}, expected=403)
    scenario = post(client, "/scenarios", {"name": "Wariant bez utraty dostępu"}, expected=201)
    post(client, f"/scenarios/{scenario['id']}/evaluate", {"expected_version": 99}, expected=409)
    job = post(client, f"/scenarios/{scenario['id']}/evaluate", {"expected_version": 1}, expected=202)
    assert job["version"] == 2
    post(client, f"/scenarios/{scenario['id']}/decision", {"expected_version": 2, "status": "performed", "evidence_ids": []}, expected=409)

def test_evaluation_durable_decision_and_effect(client):
    from services.worker.main import process_one
    login(client)
    before = client.get("/api/v1/versions").json()
    scenario = post(client, "/scenarios", {"name": "=Bezpieczna kolejność"}, expected=201)
    job = post(client, f"/scenarios/{scenario['id']}/evaluate", {"expected_version": 1}, expected=202)
    assert process_one("test-worker")
    completed = client.get(f"/api/v1/jobs/{job['job_id']}").json()
    assert completed["status"] == "completed", completed
    result = completed["result"]
    safe = next(x for x in result["variants"] if x["id"] == "safe")
    assert safe["recovered_relation_hours"] == 9
    scenario = client.get(f"/api/v1/scenarios/{scenario['id']}").json()
    assert scenario["status"] == "evaluated"
    assert client.get("/api/v1/versions").json() == before
    for status in ["approved_plan", "in_progress"]:
        scenario = post(client, f"/scenarios/{scenario['id']}/decision", {"expected_version": scenario["version"], "status": status, "variant_id": "safe", "owner": "Koordynator", "executor": "Zespół terenowy", "conditions": "Otwarcie X potwierdzone przed rozpoczęciem Y"})
    post(client, f"/scenarios/{scenario['id']}/decision", {"expected_version": scenario["version"], "status": "performed", "variant_id": "touching", "evidence_ids": []}, expected=409)
    post(client, f"/scenarios/{scenario['id']}/decision", {"expected_version": scenario["version"], "status": "performed", "evidence_ids": ["e-crossing-y-open"]}, expected=422)
    evidence = task_observation(client, feature="open", value=True)
    post(client, f"/evidence/{evidence['id']}/publish", {"expected_version": 1, "reason": "Sprawdzono wykonanie i protokół"})
    for status in ["performed", "effect_reviewed"]:
        scenario = post(client, f"/scenarios/{scenario['id']}/decision", {"expected_version": scenario["version"], "status": status, "evidence_ids": [evidence["id"]]})
    effect = client.get(f"/api/v1/scenarios/{scenario['id']}/effects").json()
    assert effect["after_data_version"] > effect["before_data_version"]
    assert effect["attribution"] and effect["simulated"]
    assert effect["selected_variant_id"] == effect["planned_variant"]["id"] == "safe"
    for fmt in ["json", "csv", "geojson"]:
        exported = client.get(f"/api/v1/exports/{scenario['id']}?format={fmt}")
        assert exported.status_code == 200
        assert "token_hash" not in exported.text
        if fmt == "json":
            snapshot = exported.json()
            assert snapshot["graph_snapshot"]["version"] == scenario["snapshot_versions"]["graph"]
            assert snapshot["algorithm_version"]
            from services.version import code_version
            assert snapshot["versions"]["code"] == scenario["snapshot_versions"]["code"] == code_version()
            assert snapshot["versions"]["code"].startswith("sha256:") and len(snapshot["versions"]["code"]) == 71
            assert "author" not in snapshot["graph_snapshot"]["evidence"][0]
            assert "request" in snapshot
        if fmt == "csv":
            assert "'=Bezpieczna" in exported.text

def test_conflict_requires_explicit_supersession(client):
    login(client)
    evidence = task_observation(client, value=0.6)
    published = post(client, f"/evidence/{evidence['id']}/publish", {"expected_version": 1, "reason": "Rzeczywisty pomiar różni się od poprzedniego"})
    assert published["status"] == "conflicted"
    assert route(client)["status"] == "possible"
    resolved = post(client, f"/evidence/{evidence['id']}/publish", {"expected_version": published["version"], "reason": "Nowy pomiar zastępuje początkowy dowód syntetyczny", "supersedes": ["e-crossing-y-width_m"]})
    assert resolved["status"] == "confirmed"
    assert route(client)["status"] == "barrier"

def test_worker_lease_recovery_and_stale_result(client):
    from services.api.db import Job, Entity
    from services.worker.main import process_one
    login(client)
    scenario = post(client, "/scenarios", {"name": "Odtworzenie pracy po restarcie"}, expected=201)
    first = post(client, f"/scenarios/{scenario['id']}/evaluate", {"expected_version": 1}, expected=202)
    second = post(client, f"/scenarios/{scenario['id']}/evaluate", {"expected_version": 2}, expected=202)
    with client.test_db.begin() as db:
        job = db.get(Job, first["job_id"])
        job.status, job.owner, job.lease_until = "running", "dead-worker", time.time()-1
    assert process_one("recovered")
    assert client.get(f"/api/v1/jobs/{first['job_id']}").json()["status"] == "stale"
    assert process_one("recovered")
    assert client.get(f"/api/v1/jobs/{second['job_id']}").json()["status"] == "completed"

def test_graph_rebinding_blocks_lost_closure_and_photo_metadata(client):
    from domain.graph import fixture_graph
    login(client, "admin")
    graph = fixture_graph()
    graph["assets"] = [a for a in graph["assets"] if a["id"] != "crossing-x"]
    for edge in graph["edges"]:
        if edge["asset_id"] == "crossing-x":
            edge["asset_id"] = "new-unbound-asset"
    graph["assets"].append({"id": "new-unbound-asset"})
    staged = post(client, "/graphs/staging", {"layer": "fixture", "graph": graph}, expected=201)
    checked = post(client, f"/graphs/{staged['id']}/validate", {"expected_version": 1})
    assert not checked["quality"]["valid"]
    post(client, f"/graphs/{staged['id']}/publish", {"expected_version": checked["version"]}, expected=409)
    report = post(client, "/reports", {"asset_id": "crossing-y", "description": "Zdjęcie wymagające sprawdzenia"}, expected=201)
    data = io.BytesIO()
    Image.new("RGB", (20, 20)).save(data, format="JPEG", exif=b"Exif\x00\x00private-metadata")
    uploaded = client.post(f"/api/v1/reports/{report['id']}/photos", files={"file": ("photo.jpg", data.getvalue(), "image/jpeg")}, headers={"X-CSRF-Token": client.csrf, "Idempotency-Key": str(uuid.uuid4())})
    assert uploaded.status_code == 201, uploaded.text
    photo = client.get(f"/api/v1/photos/{uploaded.json()['id']}")
    assert b"private-metadata" not in photo.content
    assert not Image.open(io.BytesIO(photo.content)).getexif()
