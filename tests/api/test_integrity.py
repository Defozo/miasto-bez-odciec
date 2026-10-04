import copy
import time
import uuid
from tests.api.test_flow import client, login, post, route, task_observation


def test_worker_initializes_solver_before_ready(client, monkeypatch):
    from services.worker import main as worker
    from domain.graph import catalog
    monkeypatch.setattr(worker, "SOLVER_STATE", {"status": "not_initialized", "setup_s": None})
    observed = []

    def check_initializing():
        state = client.get("/health/ready").json()["worker"]
        observed.append(state)
        assert state["status"] == "initializing"
        assert state["solver"]["status"] == "initializing"

    monkeypatch.setattr(catalog, "load_cp_model", check_initializing)
    worker.initialize_solver("new-worker")
    active = client.get("/health/ready").json()["worker"]
    assert active["status"] == "active" and active["solver"]["status"] == "ready"
    assert active["owner"] == "new-worker"

    def missing_adapter():
        check_initializing()
        raise ImportError("Optional adapter absent")

    monkeypatch.setattr(catalog, "load_cp_model", missing_adapter)
    worker.initialize_solver("manual-worker")
    active = client.get("/health/ready").json()["worker"]
    assert active["status"] == "active" and active["solver"]["status"] == "unavailable"
    assert active["owner"] == "manual-worker"
    assert len(observed) == 2


def test_effect_keeps_frozen_relations_profile_limits_and_horizon(client, monkeypatch):
    from services.api import planning
    from services.api.db import Entity
    login(client)
    created = post(client, "/scenarios", {"name": "Stały przedmiot porównania efektu", "request": {}}, expected=201)
    with client.test_db() as db:
        scenario = db.get(Entity, created["id"])
        current = copy.deepcopy(scenario.data["graph_snapshot"])
        current["profiles"][0]["max_distance_m"] = 1
        current["origins"] = current["origins"][:1]
        current["horizon"] = {"start": "2026-10-03T10:00:00+02:00", "end": "2026-10-03T11:00:00+02:00"}
        current["data_version"] += 1
        monkeypatch.setattr(planning, "graph_snapshot", lambda db, layer: current)
        effect = planning.compute_effect(db, scenario)
    assert effect["before"]["metrics"]["total_relation_hours"] == effect["after"]["metrics"]["total_relation_hours"] == 25
    assert effect["before"]["metrics"]["available_relation_hours"] == effect["after"]["metrics"]["available_relation_hours"] == 16
    assert [r["id"] for r in effect["before"]["relations"]] == [r["id"] for r in effect["after"]["relations"]]
    assert effect["other_changes"] == 1


def test_evaluation_records_executing_code_separately_from_draft(client, monkeypatch):
    from services.worker import main as worker
    from services.api.db import Entity
    login(client)
    created = post(client, "/scenarios", {"name": "Draft przeliczony po aktualizacji kodu"}, expected=201)
    original_code = created["snapshot_versions"]["code"]
    executing_code = "sha256:" + "e"*64
    monkeypatch.setattr(worker, "code_version", lambda: executing_code)
    queued = post(client, f"/scenarios/{created['id']}/evaluate", {"expected_version": 1}, expected=202)
    assert worker.process_one("upgraded-worker")
    completed = client.get(f"/api/v1/jobs/{queued['job_id']}").json()
    assert completed["status"] == "completed"
    assert completed["result"]["evaluated_code_version"] == executing_code != original_code
    exported = client.get(f"/api/v1/exports/{created['id']}").json()
    assert exported["versions"]["code"] == original_code
    assert exported["evaluated_code_version"] == executing_code
    current = client.get(f"/api/v1/scenarios/{created['id']}").json()
    with client.test_db() as db:
        snapshot = db.get(Entity, current["latest_evaluation_id"]).data["snapshot"]
    assert snapshot["code"] == original_code
    assert snapshot["evaluated_code_version"] == executing_code


def test_barrier_requires_new_open_evidence_not_width(client):
    report = post(client, "/reports", {"asset_id": "crossing-y", "description": "Zamknięte przejście wymaga kontroli"}, expected=201)
    login(client)
    reviewed = post(client, f"/reports/{report['id']}/review", {"expected_version": 1, "action": "locate_warning", "reason": "Położenie zostało potwierdzone"})
    again = post(client, f"/reports/{report['id']}/review", {"expected_version": reviewed["version"], "action": "locate_warning", "reason": "Uściślono lokalizację"})
    assert reviewed["restriction_id"] == again["restriction_id"]
    width = task_observation(client)
    post(client, f"/evidence/{width['id']}/publish", {"expected_version": 1, "reason": "Sprawdzono pomiar"})
    post(client, f"/reports/{report['id']}/review", {"expected_version": again["version"], "action": "confirm", "reason": "Ten pomiar nie dotyczy otwarcia", "evidence_id": width["id"]}, expected=422)
    post(client, f"/reports/{report['id']}/review", {"expected_version": again["version"], "action": "resolve", "reason": "Stary dowód nie rozstrzyga nowego zdarzenia", "evidence_id": "e-crossing-y-open"}, expected=422)
    assert route(client)["status"] == "possible"

def test_units_privacy_and_unaffected_pedestrians(client):
    login(client)
    task = post(client, "/tasks", {"title": "Pomiar szerokości", "asset_id": "crossing-y", "property": "width_m", "unit": "m", "method": "Pomiar taśmą"}, expected=201)
    post(client, f"/tasks/{task['id']}/observe", {"expected_version": 1, "value": 100, "unit": "cm", "method": "Pomiar taśmą", "observed_at": "2026-10-03T08:00:00+02:00", "valid_until": "2026-10-03T23:00:00+02:00"}, expected=422)
    evidence = task_observation(client)
    assert evidence["id"] not in {e["id"] for e in client.get("/api/v1/evidence").json()}
    before = client.get("/api/v1/versions").json()
    record = post(client, "/restrictions", {"asset_id": "crossing-y", "source_id": "source-fixture", "start": "2026-10-03T08:00:00+02:00", "end": "2026-10-03T21:00:00+02:00", "pedestrian_impact": False, "reason": "Zamknięcie jezdni, chodnik bez zmian"}, expected=201)
    assert record["status"] == "no_pedestrian_impact"
    assert client.get("/api/v1/versions").json() == before
    assert route(client)["status"] == "confirmed"
    login(client, "verifier")
    bootstrap = client.get("/api/v1/bootstrap").json()
    assert not bootstrap["scenarios"] and not bootstrap["reports"]
    assert "author" not in bootstrap["graph"]["evidence"][0]
    post(client, "/analysis/evaluate", {"layer": "scenario"}, expected=403)

def test_opening_observation_and_atomic_graph_publication(client):
    from domain.graph import fixture_graph
    login(client, "admin")
    evidence = task_observation(client, "open", True, observed_at="2026-10-03T11:00:00+02:00")
    post(client, f"/evidence/{evidence['id']}/publish", {"expected_version": 1, "reason": "Nowa obserwacja otwarcia"})
    opened = post(client, "/restrictions/Y/open", {"expected_version": 1, "evidence_id": evidence["id"], "observed_at": "2026-10-03T11:00:00+02:00", "reason": "Roboty zakończono i sprawdzono otwarcie"})
    assert opened["verified_open_at"] == "2026-10-03T09:00:00+00:00"
    graph = fixture_graph()
    for edge in graph["edges"]:
        previous = edge["id"]
        edge["id"] = "new-"+previous
        edge["source_edge_ids"] = [previous]
    staged = post(client, "/graphs/staging", {"layer": "fixture", "graph": graph}, expected=201)
    checked = post(client, f"/graphs/{staged['id']}/validate", {"expected_version": 1})
    assert checked["quality"]["valid"]
    published = post(client, f"/graphs/{staged['id']}/publish", {"expected_version": 2})
    assert published["status"] == "published"
    assert next(r for r in client.get("/api/v1/restrictions").json() if r["id"] == "Y")["verified_open_at"] == opened["verified_open_at"]

def test_empty_and_wrong_level_graph_not_publishable(client):
    from domain.graph import fixture_graph
    login(client, "admin")
    graph = fixture_graph()
    graph["nodes"][0]["level"] = 1
    staged = post(client, "/graphs/staging", {"layer": "fixture", "graph": graph}, expected=201)
    post(client, f"/graphs/{staged['id']}/publish", {"expected_version": 1}, expected=409)

def test_maintenance_expires_evidence_and_schedules_rechecks(client):
    from services.api.db import Entity
    from services.worker.main import maintenance
    with client.test_db.begin() as db:
        evidence = db.get(Entity, "e-crossing-y-width_m")
        evidence.data = {**evidence.data, "valid_until": "2026-10-03T08:30:00+02:00"}
    maintenance()
    login(client)
    tasks = client.get("/api/v1/tasks").json()
    assert any(t.get("previous_evidence_id") == "e-crossing-y-width_m" for t in tasks)
    assert route(client)["status"] == "possible"

def test_source_original_snapshot_and_replay(client, monkeypatch):
    import ingest
    monkeypatch.setattr(ingest, "safe_fetch", lambda url: {"text": "Plain public text", "raw": "<p>Plain public text</p>", "sha256": "original-hash", "fetched_at": "2026-10-03T07:00:00Z"})
    login(client)
    source = post(client, "/sources", {"title": "Komunikat zarządcy", "publisher": "Zarządca", "url": "https://krakow.pl/test", "fetch": True, "refresh_enabled": True}, expected=201)
    detail = client.get(f"/api/v1/sources/{source['id']}").json()
    assert detail["sha256"] == "original-hash"
    assert detail["snapshots"][0]["raw"] == "<p>Plain public text</p>"
    assert detail["observed_at"] is None and detail["published_at"] is None


def test_pending_evidence_is_staff_only_and_private_layers_require_auth(client):
    for endpoint in ("bootstrap", "coverage", "places", "profiles", "evidence", "sources", "restrictions", "versions"):
        assert client.get(f"/api/v1/{endpoint}?layer=scenario").status_code == 401
    assert client.get("/api/v1/evidence?include_pending=true").status_code == 401
    login(client)
    evidence = task_observation(client)
    pending = client.get("/api/v1/evidence?include_pending=true").json()
    assert any(e["id"] == evidence["id"] for e in pending)
    assert any(e["id"] == evidence["id"] for e in client.get("/api/v1/bootstrap").json()["staff_evidence"])
    assert evidence["id"] not in {e["id"] for e in client.get("/api/v1/evidence").json()}


def test_opening_time_cannot_be_rewritten(client):
    login(client)
    evidence = task_observation(client, "open", True)
    post(client, f"/evidence/{evidence['id']}/publish", {"expected_version": 1, "reason": "Sprawdzono zapis obserwacji"})
    post(client, "/restrictions/Y/open", {"expected_version": 1, "evidence_id": evidence["id"], "observed_at": "2026-10-03T11:00:00+02:00", "reason": "Nie wolno przesunąć obserwacji sprzed zamknięcia"}, expected=422)


def test_malformed_graph_publication_returns_quality_errors(client):
    login(client, "admin")
    staged = post(client, "/graphs/staging", {"layer": "fixture", "graph": {"nodes": [{"lat": 50, "lon": 19}], "edges": []}}, expected=201)
    result = post(client, f"/graphs/{staged['id']}/validate", {"expected_version": 1})
    assert not result["quality"]["valid"]
    assert result["quality"]["errors"][0]["code"] == "invalid_collection_or_id"


def test_expired_worker_cannot_reanimate_lease(client):
    from services.api.db import Job
    from services.worker.main import heartbeat
    with client.test_db.begin() as db:
        db.add(Job(id="lease-test", kind="refresh", layer="fixture", payload={}, status="running", owner="old", lease_until=time.time()-1))
    heartbeat("old", "lease-test")
    with client.test_db() as db:
        assert db.get(Job, "lease-test").lease_until < time.time()


def test_source_refresh_preserves_observation_and_schedules_once(client, monkeypatch):
    import ingest
    from services.api.db import Entity, Job
    from services.worker.main import maintenance, process_one
    from sqlalchemy import select
    login(client)
    source = post(client, "/sources", {"title": "Źródło okresowe", "publisher": "Zarządca", "url": "https://krakow.pl/test", "raw_text": "Pierwszy komunikat", "refresh_enabled": True, "observed_at": "2026-10-03T06:00:00Z"}, expected=201)
    with client.test_db.begin() as db:
        entity = db.get(Entity, source["id"])
        entity.data = {**entity.data, "next_refresh_at": 0}
    maintenance()
    maintenance()
    with client.test_db() as db:
        jobs = list(db.scalars(select(Job).where(Job.kind == "source_refresh")))
        assert len(jobs) == 1
    monkeypatch.setattr(ingest, "safe_fetch", lambda url: {"text": "Nowy komunikat", "raw": "<p>Nowy komunikat</p>", "sha256": "new-hash", "fetched_at": "2026-10-03T09:00:00Z"})
    assert process_one("source-test")
    detail = client.get(f"/api/v1/sources/{source['id']}").json()
    assert detail["observed_at"] == "2026-10-03T06:00:00Z"
    assert detail["sha256"] == "new-hash"
    assert detail["pending_refresh_job"] is None
    assert len(detail["snapshots"]) == 2


def test_past_warning_creates_recheck_and_never_reopens(client):
    from services.worker.main import maintenance
    report = post(client, "/reports", {"asset_id": "crossing-y", "description": "Przeszkoda na jedynym obejściu"}, expected=201)
    login(client)
    reviewed = post(client, f"/reports/{report['id']}/review", {"expected_version": 1, "action": "locate_warning", "start": "2026-10-03T07:00:00+02:00", "end": "2026-10-03T08:00:00+02:00", "reason": "Położenie ostrzeżenia potwierdzone"})
    maintenance()
    maintenance()
    tasks = client.get("/api/v1/tasks").json()
    assert len([task for task in tasks if task.get("previous_restriction_id") == reviewed["restriction_id"]]) == 1
    assert route(client)["status"] == "possible"


def test_transaction_failure_is_reported_before_success_response(client, monkeypatch):
    from services.api import db as database
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session, sessionmaker
    class FailedCommit(Session):
        def commit(self):
            raise IntegrityError("test unique conflict", {}, Exception("concurrent mutation"))
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=client.test_db.kw["bind"], class_=FailedCommit, expire_on_commit=False))
    result = client.post("/api/v1/reports", json={"asset_id": "crossing-y", "description": "Transakcja nie została zatwierdzona"}, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert result.status_code == 409


def test_weekly_graph_refresh_stages_snapshot_without_publication(client, monkeypatch):
    import ingest
    from services.worker import main as worker
    from services.api.db import Entity, Job, State
    from sqlalchemy import select
    config = {"graph_refresh_days": 7, "graph_source": {"layer": "fixture", "url": "https://overpass-api.de/api/interpreter?data=fixture", "format": "osm"}}
    monkeypatch.setattr(worker, "load_settings", lambda: config)
    source_payload = {"elements": [{"type": "node", "id": 1, "lat": 50.0, "lon": 19.0}, {"type": "node", "id": 2, "lat": 50.001, "lon": 19.001}, {"type": "way", "id": 3, "nodes": [1, 2], "tags": {"highway": "footway"}}]}
    import json
    monkeypatch.setattr(ingest, "safe_fetch", lambda url, **kwargs: {"text": json.dumps(source_payload), "raw": json.dumps(source_payload), "sha256": "fresh-map", "fetched_at": "2026-10-03T09:00:00Z"})
    before = client.get("/api/v1/versions").json()
    worker.maintenance()
    worker.maintenance()
    with client.test_db() as db:
        jobs = list(db.scalars(select(Job).where(Job.kind == "graph_refresh")))
        assert len(jobs) == 1
    assert worker.process_one("weekly-map")
    assert client.get("/api/v1/versions").json() == before
    with client.test_db() as db:
        tracked = db.get(State, "graph_refresh:fixture")
        assert tracked.value["pending_job_id"] is None
        assert db.get(Entity, tracked.value["last_staged_graph_id"]).data["status"] == "staged"
        assert tracked.value["next_refresh_at"] > time.time()+6*86400


def test_source_failure_keeps_snapshot_and_clears_pending_refresh(client, monkeypatch):
    import ingest
    from services.api.db import Entity
    from services.worker.main import maintenance, process_one
    login(client)
    source = post(client, "/sources", {"title": "Niedostępne źródło", "publisher": "Zarządca", "url": "https://krakow.pl/test", "raw_text": "Ostatni dostępny komunikat", "refresh_enabled": True, "observed_at": "2026-10-03T06:00:00Z"}, expected=201)
    with client.test_db.begin() as db:
        entity = db.get(Entity, source["id"])
        entity.data = {**entity.data, "next_refresh_at": 0}
    monkeypatch.setattr(ingest, "safe_fetch", lambda url: (_ for _ in ()).throw(ValueError("Źródło niedostępne")))
    maintenance()
    assert process_one("source-failure")
    detail = client.get(f"/api/v1/sources/{source['id']}").json()
    assert detail["pending_refresh_job"] is None and detail["last_refresh_error"]
    assert detail["raw_text"] == source["raw_text"]
    assert detail["observed_at"] == source["observed_at"]
    assert detail["next_refresh_at"] > time.time()


def test_staged_graph_editor_is_versioned_and_published_graph_immutable(client):
    from domain.graph import fixture_graph
    login(client, "admin")
    graph = fixture_graph()
    staged = post(client, "/graphs/staging", {"layer": "fixture", "graph": {**graph, "origins": [], "profiles": []}}, expected=201)
    edited = post(client, f"/graphs/{staged['id']}/edit", {"expected_version": 1, "graph_patch": {"origins": graph["origins"], "profiles": graph["profiles"]}})
    assert edited["status"] == "staged" and edited["graph"]["profiles"]
    post(client, f"/graphs/{staged['id']}/edit", {"expected_version": 1, "graph_patch": {}}, expected=409)
    published = post(client, f"/graphs/{staged['id']}/publish", {"expected_version": edited["version"]})
    assert published["status"] == "published"
    post(client, f"/graphs/{staged['id']}/edit", {"expected_version": published["version"], "graph_patch": {"profiles": []}}, expected=409)


def test_observed_evidence_rejects_future_and_excessive_validity(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from domain.graph import fixture_graph
    from services.api import reports
    from services.api.db import Entity, State, User
    from services.api.security import hasher
    with client.test_db.begin() as db:
        graph = fixture_graph()
        graph["layer"] = "observed"
        db.add(Entity(id="graph-observed-test", kind="graph", layer="observed", data={"graph": graph, "status": "published"}))
        db.add(State(key="layer:observed", value={"graph_id": "graph-observed-test", "data_version": 1}))
        db.add(User(id="real-operator", username="test-operator", role="operator", password_hash=hasher.hash("only-local-test-password")))
    authenticated = client.post("/api/v1/auth/login", json={"username": "test-operator", "password": "only-local-test-password"})
    client.csrf = authenticated.json()["csrf_token"]
    monkeypatch.setattr(reports, "load_settings", lambda: {"dynamic_evidence_ttl_hours": 2, "geometry_evidence_ttl_days": 2})
    task = post(client, "/tasks", {"layer": "observed", "title": "Kontrola otwarcia", "asset_id": "crossing-y", "property": "open", "method": "Obserwacja terenowa"}, expected=201)
    now = datetime.now(timezone.utc)
    payload = {"expected_version": 1, "value": True, "method": "Obserwacja terenowa", "observed_at": (now+timedelta(hours=1)).isoformat(), "valid_until": (now+timedelta(hours=2)).isoformat()}
    post(client, f"/tasks/{task['id']}/observe", payload, expected=422)
    payload.update(observed_at=now.isoformat(), valid_until=(now+timedelta(hours=3)).isoformat())
    post(client, f"/tasks/{task['id']}/observe", payload, expected=422)
    payload["valid_until"] = (now+timedelta(hours=2)).isoformat()
    assert post(client, f"/tasks/{task['id']}/observe", payload)["evidence"]["status"] == "pending_review"
    geometry = post(client, "/tasks", {"layer": "observed", "title": "Kontrola geometrii", "asset_id": "crossing-y", "property": "width_m", "unit": "m", "method": "Pomiar taśmą"}, expected=201)
    payload.update(value=1.8, unit="m", valid_until=(now+timedelta(days=3)).isoformat())
    post(client, f"/tasks/{geometry['id']}/observe", payload, expected=422)


def test_exhausted_refresh_leases_clear_pending_and_retry_after_backoff(client, monkeypatch):
    from services.worker import main as worker
    from services.api.db import Entity, Job, State
    from sqlalchemy import select
    monkeypatch.setattr(worker, "load_settings", lambda: {"source_refresh_minutes": 30, "graph_refresh_days": 7, "graph_source": {"layer": "fixture", "url": "https://overpass-api.de/api/interpreter?data=fixture"}})
    login(client)
    source = post(client, "/sources", {"title": "Odnawiane źródło", "publisher": "Zarządca", "url": "https://krakow.pl/test", "raw_text": "Zachowany komunikat", "refresh_enabled": True}, expected=201)
    with client.test_db.begin() as db:
        entity = db.get(Entity, source["id"])
        entity.data = {**entity.data, "next_refresh_at": 0}
    worker.maintenance()
    with client.test_db.begin() as db:
        for job in db.scalars(select(Job)):
            job.status, job.owner, job.lease_until, job.attempts = "running", "crashed", time.time()-1, 5
    assert worker.claim_job("replacement") is None
    with client.test_db() as db:
        entity = db.get(Entity, source["id"])
        tracked = db.get(State, "graph_refresh:fixture")
        assert entity.data["pending_refresh_job"] is None and entity.data["last_refresh_error"]
        assert tracked.value["pending_job_id"] is None and tracked.value["last_error"]
        assert entity.data["raw_text"] == "Zachowany komunikat"
        assert entity.data["next_refresh_at"] > time.time()+1700
        assert tracked.value["next_refresh_at"] > time.time()+1700
        assert all(job.status == "failed" for job in db.scalars(select(Job)))
    worker.maintenance()
    with client.test_db.begin() as db:
        assert not list(db.scalars(select(Job).where(Job.status == "queued")))
        entity = db.get(Entity, source["id"])
        entity.data = {**entity.data, "next_refresh_at": 0}
        tracked = db.get(State, "graph_refresh:fixture")
        tracked.value = {**tracked.value, "next_refresh_at": 0}
    worker.maintenance()
    with client.test_db() as db:
        assert len(list(db.scalars(select(Job).where(Job.status == "queued")))) == 2
