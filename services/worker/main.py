"""Durable workers with atomic claim, renewable leases and version-checked results."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from services.api.db import Entity, Job, OutboxEvent, SessionLocal, State, utcnow
from services.api.store import add_entity, graph_snapshot, instant, items, publish_change, serial, uid
from services.settings import analysis_time_limit, load_settings
from services.version import code_version

logger = logging.getLogger("smart_city.worker")
LEASE_SECONDS = 60
SOLVER_STATE = {"status": "not_initialized", "setup_s": None}

def claim_job(owner):
    now = time.time()
    with SessionLocal.begin() as db:
        candidates = list(db.scalars(select(Job).where(or_(Job.status == "queued", (Job.status == "running") & (Job.lease_until < now))).order_by(Job.created_at).limit(10)))
        for job in candidates:
            if job.attempts >= 5:
                exhausted = db.execute(update(Job).where(Job.id == job.id, Job.attempts >= 5, or_(Job.status == "queued", (Job.status == "running") & (Job.lease_until < now))).values(status="failed", error="Przekroczono limit bezpiecznych wznowień zadania.", finished_at=utcnow(), lease_until=None), execution_options={"synchronize_session": False}).rowcount
                if exhausted != 1:
                    continue
                next_refresh = now+max(60, float(load_settings().get("source_refresh_minutes", 30))*60)
                if job.kind == "source_refresh":
                    source = db.get(Entity, job.payload.get("source_id"))
                    if source and source.data.get("pending_refresh_job") == job.id:
                        db.execute(update(Entity).where(Entity.id == source.id, Entity.version == source.version).values(data={**source.data, "pending_refresh_job": None, "next_refresh_at": next_refresh, "last_refresh_error": "Przerwane odświeżanie przekroczyło limit wznowień. Poprzedni zapis pozostaje aktywny; kolejna próba po okresie oczekiwania."}, version=source.version+1, updated_at=utcnow()), execution_options={"synchronize_session": False})
                elif job.kind == "graph_refresh":
                    tracked = db.scalar(select(State).where(State.key == f"graph_refresh:{job.layer}").with_for_update())
                    if tracked and tracked.value.get("pending_job_id") == job.id:
                        tracked.value = {**tracked.value, "pending_job_id": None, "next_refresh_at": next_refresh, "last_failure_at": utcnow(), "last_error": "Przerwany import przekroczył limit wznowień. Poprzedni graf pozostaje aktywny; kolejna próba po okresie oczekiwania."}
                continue
            changed = db.execute(update(Job).where(Job.id == job.id, or_(Job.status == "queued", (Job.status == "running") & (Job.lease_until < now))).values(status="running", owner=owner, lease_until=now+LEASE_SECONDS, heartbeat=now, attempts=Job.attempts+1, progress=5), execution_options={"synchronize_session": False}).rowcount
            if changed == 1:
                return job.id
    return None

def heartbeat(owner, job_id=None, status="active"):
    with SessionLocal.begin() as db:
        now = time.time()
        value = {"owner": owner, "at": utcnow(), "timestamp": now, "status": status, "job_id": job_id, "solver": SOLVER_STATE}
        changed = db.execute(update(State).where(State.key == "worker_heartbeat").values(value=value)).rowcount
        if not changed:
            try:
                with db.begin_nested():
                    db.add(State(key="worker_heartbeat", value=value))
                    db.flush()
            except IntegrityError:
                db.execute(update(State).where(State.key == "worker_heartbeat").values(value=value))
        if job_id:
            db.execute(update(Job).where(Job.id == job_id, Job.owner == owner, Job.status == "running", Job.lease_until >= now).values(heartbeat=now, lease_until=now+LEASE_SECONDS))

def initialize_solver(owner):
    """Publish initialization explicitly; manual calculations need no adapter."""
    global SOLVER_STATE
    from domain.graph.catalog import load_cp_model
    SOLVER_STATE = {"status": "initializing", "setup_s": None}
    heartbeat(owner, status="initializing")
    started = time.monotonic()
    try:
        load_cp_model()
        status = "ready"
    except (ImportError, OSError):
        status = "unavailable"
        logger.warning("Optional CP-SAT adapter unavailable; manual evaluation remains available.")
    SOLVER_STATE = {"status": status, "setup_s": round(time.monotonic()-started, 3)}
    heartbeat(owner)


def keep_lease(stop, owner, job_id):
    while not stop.wait(10):
        try:
            heartbeat(owner, job_id)
        except Exception:
            # A failed renewal does not authorize finishing on an expired lease.
            logger.warning("Worker lease renewal failed for %s", job_id)

def process_one(owner=None):
    owner = owner or "worker-"+secrets.token_hex(6)
    heartbeat(owner)
    identifier = claim_job(owner)
    if not identifier:
        return False
    stop = threading.Event()
    thread = threading.Thread(target=keep_lease, args=(stop, owner, identifier), daemon=True)
    thread.start()
    try:
        with SessionLocal() as db:
            job = db.get(Job, identifier)
            kind, payload, layer = job.kind, copy.deepcopy(job.payload), job.layer
        if kind == "evaluation":
            from domain.graph import evaluate
            calculation = {**{k: v for k, v in payload["request"].items() if not k.startswith("_")}, "time_limit_s": analysis_time_limit(payload["request"])}
            if calculation.get("catalog"):
                from domain.graph import optimize_catalog
                result = optimize_catalog(payload["graph"], calculation)
            else:
                result = evaluate(payload["graph"], calculation)
            result["evaluated_code_version"] = code_version()
        elif kind == "refresh":
            with SessionLocal() as db:
                graph = graph_snapshot(db, layer)
                result = {"data_version": graph["data_version"], "graph_version": graph["version"], "published": True}
        elif kind == "source_refresh":
            from ingest import safe_fetch, fetch_firecrawl
            fetched = (fetch_firecrawl if payload.get("provider") == "firecrawl" else safe_fetch)(payload["url"])
            result = {"source_id": payload["source_id"], "sha256": fetched["sha256"], "fetched_at": fetched["fetched_at"], "published": False}
        elif kind == "graph_refresh":
            from ingest import safe_fetch, import_osm, import_geojson
            fetched = safe_fetch(payload["url"], method=payload.get("method", "GET"), body=payload.get("body"), max_bytes=20_000_000, timeout=30)
            source_payload = json.loads(fetched.get("raw", fetched["text"]))
            imported_graph = (import_geojson if payload.get("format") == "geojson" else import_osm)(source_payload)
            imported_graph = imported_graph.get("graph", imported_graph)
            imported_graph["layer"] = layer
            result = {"sha256": fetched["sha256"], "fetched_at": fetched["fetched_at"], "published": False, "status": "staged"}
        else:
            raise ValueError("Unsupported durable job")
        with SessionLocal.begin() as db:
            # This conditional write locks the job until all resulting changes
            # commit. A superseded or expired worker cannot publish results.
            fence = db.execute(update(Job).where(Job.id == identifier, Job.owner == owner, Job.status == "running", Job.lease_until >= time.time()).values(heartbeat=time.time()), execution_options={"synchronize_session": False}).rowcount
            if fence != 1:
                return True
            job = db.get(Job, identifier)
            stale = False
            if kind == "graph_refresh":
                refresh_state = db.scalar(select(State).where(State.key == f"graph_refresh:{layer}").with_for_update())
                if not refresh_state or refresh_state.value.get("pending_job_id") != identifier:
                    stale = True
                source = add_entity(db, "source", layer, {"title": "Okresowy import mapy do kontroli", "publisher": "OpenStreetMap" if payload.get("format", "osm") == "osm" else "Skonfigurowane źródło grafu", "url": payload["url"], "sha256": fetched["sha256"], "fetched_at": fetched["fetched_at"], "published_at": None, "observed_at": None, "status": "staged", "license": imported_graph.get("source", {}).get("licence", "unknown"), "raw_text": "", "refresh_enabled": False})
                add_entity(db, "source_snapshot", layer, {"source_id": source.id, "raw": fetched.get("raw", fetched["text"]), "text": fetched["text"], "sha256": fetched["sha256"], "fetched_at": fetched["fetched_at"], "published_at": None, "observed_at": None, "stale": stale})
                imported = add_entity(db, "import", layer, {"format": payload.get("format", "osm"), "status": "staged", "source_id": source.id, "sha256": fetched["sha256"], "result": {"automatic_refresh": True, "requires_review": True}})
                staged = add_entity(db, "graph", layer, {"graph": imported_graph, "status": "staged", "import_id": imported.id, "source_id": source.id, "bindings": {}, "refresh_job_id": identifier, "stale": stale})
                imported.data = {**imported.data, "graph_id": staged.id}
                result["graph_id"] = staged.id
                if not stale:
                    refresh_state.value = {**refresh_state.value, "pending_job_id": None, "last_staged_graph_id": staged.id, "last_success_at": utcnow(), "last_error": None}
            if kind == "source_refresh":
                source = db.get(Entity, payload["source_id"])
                stale = source.version != payload["expected_version"]
                source_snapshot = add_entity(db, "source_snapshot", layer, {"source_id": source.id, "raw": fetched.get("raw", fetched["text"]), "text": fetched["text"], "sha256": fetched["sha256"], "fetched_at": fetched["fetched_at"], "published_at": fetched.get("published_at"), "observed_at": fetched.get("observed_at"), "stale": stale})
                if not stale:
                    source_data = {**source.data, "raw_text": fetched["text"], "sha256": fetched["sha256"], "text_sha256": hashlib.sha256(fetched["text"].encode()).hexdigest(), "fetched_at": fetched["fetched_at"], "last_refresh_error": None, "status": "needs_review", "pending_refresh_job": None}
                    changed = db.execute(update(Entity).where(Entity.id == source.id, Entity.version == payload["expected_version"]).values(data=source_data, version=source.version+1, updated_at=utcnow()), execution_options={"synchronize_session": False}).rowcount
                    stale = changed != 1
                if stale:
                    source_snapshot.data = {**source_snapshot.data, "stale": True}
                    db.refresh(source)
                    if source.data.get("pending_refresh_job") == identifier:
                        db.execute(update(Entity).where(Entity.id == source.id, Entity.version == source.version).values(data={**source.data, "pending_refresh_job": None}, version=source.version+1, updated_at=utcnow()), execution_options={"synchronize_session": False})
            if kind == "evaluation":
                scenario = db.get(Entity, payload["scenario_id"])
                stale = scenario.version != payload["expected_version"] or scenario.data.get("pending_job_id") != identifier
                evaluation = add_entity(db, "evaluation", layer, {"scenario_id": scenario.id, "job_id": identifier, "result": result, "snapshot": {**scenario.data.get("snapshot_versions", {}), "evaluated_code_version": result["evaluated_code_version"]}, "stale": stale})
                if not stale:
                    data = {**scenario.data, "status": "evaluated", "latest_result": result, "latest_evaluation_id": evaluation.id, "evaluations": scenario.data.get("evaluations", [])+[evaluation.id], "pending_job_id": None}
                    changed = db.execute(update(Entity).where(Entity.id == scenario.id, Entity.version == payload["expected_version"]).values(data=data, version=scenario.version+1, updated_at=utcnow()), execution_options={"synchronize_session": False}).rowcount
                    stale = changed != 1
                    if stale:
                        evaluation.data = {**evaluation.data, "stale": True}
                db.add(OutboxEvent(layer=layer, event="evaluation_finished", version=payload["expected_version"], data={"job_id": identifier, "scenario_id": scenario.id, "stale": stale}))
            job.status, job.progress, job.result, job.finished_at = "stale" if stale else "completed", 100, result, utcnow()
            job.lease_until = None
        return True
    except Exception as exc:
        logger.exception("Worker job failed: %s", identifier)
        with SessionLocal.begin() as db:
            job = db.get(Job, identifier)
            fenced = db.execute(update(Job).where(Job.id == identifier, Job.owner == owner, Job.status == "running", Job.lease_until >= time.time()).values(status="failed", error=f"{type(exc).__name__}: {str(exc)[:400]}", finished_at=utcnow()), execution_options={"synchronize_session": False}).rowcount
            if job and fenced == 1:
                if job.kind == "graph_refresh":
                    refresh_state = db.scalar(select(State).where(State.key == f"graph_refresh:{job.layer}").with_for_update())
                    if refresh_state and refresh_state.value.get("pending_job_id") == identifier:
                        retry_delay = max(60, float(load_settings().get("source_refresh_minutes", 30))*60)
                        refresh_state.value = {**refresh_state.value, "pending_job_id": None, "last_error": "Nie udało się pobrać lub sprawdzić mapy. Poprzedni opublikowany graf pozostaje aktywny.", "last_failure_at": utcnow(), "next_refresh_at": time.time()+retry_delay}
                if job.kind == "source_refresh":
                    source = db.get(Entity, job.payload["source_id"])
                    if source and source.data.get("pending_refresh_job") == identifier:
                        db.execute(update(Entity).where(Entity.id == source.id, Entity.version == source.version).values(data={**source.data, "last_refresh_error": "Źródło niedostępne. Zachowano poprzedni zapis i jego daty.", "pending_refresh_job": None}, version=source.version+1, updated_at=utcnow()), execution_options={"synchronize_session": False})
        return True
    finally:
        stop.set()
        thread.join(timeout=1)

def maintenance():
    """Expiry never extends an observation; fixture uses its controlled clock."""
    settings = load_settings()
    source_interval = max(60, float(settings.get("source_refresh_minutes", 30))*60)
    with SessionLocal.begin() as db:
        for layer in ("fixture", "observed"):
            try:
                graph = graph_snapshot(db, layer)
            except Exception:
                continue
            clock = instant(graph.get("clock", utcnow())) if layer == "fixture" else datetime.now(timezone.utc)
            changed = False
            for evidence in items(db, "evidence", layer):
                if evidence.data.get("status") != "confirmed" or not evidence.data.get("valid_until") or instant(evidence.data["valid_until"]) > clock:
                    continue
                expired = db.execute(update(Entity).where(Entity.id == evidence.id, Entity.version == evidence.version).values(data={**evidence.data, "status": "expired", "expired_at": utcnow()}, version=evidence.version+1, updated_at=utcnow()), execution_options={"synchronize_session": False}).rowcount
                if expired != 1:
                    continue
                add_entity(db, "task", layer, {"title": "Ponowna kontrola wygasłego dowodu", "asset_id": evidence.data["asset_id"], "feature": evidence.data["feature"], "property": evidence.data["feature"], "unit": evidence.data.get("unit"), "method": evidence.data.get("method", "Pomiar terenowy"), "status": "assigned", "due_at": utcnow(), "previous_evidence_id": evidence.id, "positive_effect": "Możliwość potwierdzenia cechy", "negative_effect": "Utrzymanie ograniczenia lub niewiadomej"})
                changed = True
            if changed:
                publish_change(db, layer, "evidence_expired")
            for restriction in items(db, "restriction", layer):
                if restriction.data.get("status") in {"retired", "no_pedestrian_impact"} or restriction.data.get("verified_open_at") or restriction.data.get("recheck_task_id"):
                    continue
                due = restriction.data.get("end")
                if not due or instant(due) > clock:
                    continue
                task_id = uid("task")
                claimed = db.execute(update(Entity).where(Entity.id == restriction.id, Entity.version == restriction.version).values(data={**restriction.data, "recheck_task_id": task_id}, version=restriction.version+1, updated_at=utcnow()), execution_options={"synchronize_session": False}).rowcount
                if claimed != 1:
                    continue
                add_entity(db, "task", layer, {"title": "Kontrola po planowanym końcu utrudnienia", "asset_id": restriction.data["asset_id"], "feature": "open", "property": "open", "unit": None, "method": "Obserwacja drożności w terenie po zakończeniu robót", "status": "assigned", "due_at": due, "previous_restriction_id": restriction.id, "positive_effect": "Nowa obserwacja może potwierdzić otwarcie", "negative_effect": "Ograniczenie lub ostrzeżenie pozostaje aktywne"}, task_id)
        sources = list(db.scalars(select(Entity).where(Entity.kind == "source")))
        for source in sources:
            if source.data.get("refresh_enabled") and source.data.get("next_refresh_at", 0) <= time.time() and not source.data.get("pending_refresh_job"):
                identifier = uid("job")
                next_version = source.version+1
                changed = db.execute(update(Entity).where(Entity.id == source.id, Entity.version == source.version).values(data={**source.data, "pending_refresh_job": identifier, "next_refresh_at": time.time()+max(source_interval, source.data.get("refresh_interval_s", source_interval))}, version=next_version, updated_at=utcnow()), execution_options={"synchronize_session": False}).rowcount
                if changed == 1:
                    db.add(Job(id=identifier, kind="source_refresh", layer=source.layer, payload={"source_id": source.id, "expected_version": next_version, "provider": source.data.get("provider"), "url": source.data["url"]}))
        schedule_graph_refresh(db, settings)


def schedule_graph_refresh(db, settings):
    configured = settings.get("graph_source") or {}
    if isinstance(configured, str):
        configured = {"url": configured}
    if os.getenv("SMART_CITY_GRAPH_SOURCE_URL"):
        configured = {**configured, "url": os.environ["SMART_CITY_GRAPH_SOURCE_URL"]}
    for layer in {"observed", configured.get("layer", "observed")}:
        if layer not in {"observed", "fixture"}:
            continue
        specification = configured if configured.get("layer", "observed") == layer else {}
        active = db.get(State, f"layer:{layer}")
        published = db.get(Entity, active.value.get("graph_id")) if active and active.value.get("graph_id") else None
        if not specification.get("url") and published:
            previous_source = published.data.get("graph", {}).get("source", {})
            previous_url = previous_source.get("url")
            if previous_url and urlsplit(previous_url).hostname == "overpass-api.de" and "data=" in urlsplit(previous_url).query:
                specification = {"url": previous_url, "format": "osm"}
        if not specification.get("url") or specification.get("enabled", True) is False:
            continue
        tracked = db.scalar(select(State).where(State.key == f"graph_refresh:{layer}").with_for_update())
        if not tracked:
            fetched_at = (published.data.get("graph", {}).get("source", {}).get("fetched_at") if published else None)
            due = instant(fetched_at).timestamp()+float(settings.get("graph_refresh_days", 7))*86400 if fetched_at else time.time()
            tracked = State(key=f"graph_refresh:{layer}", value={"next_refresh_at": due, "pending_job_id": None})
            db.add(tracked)
            db.flush()
        if tracked.value.get("pending_job_id") or tracked.value.get("next_refresh_at", 0) > time.time():
            continue
        identifier = uid("job")
        tracked.value = {**tracked.value, "pending_job_id": identifier, "next_refresh_at": time.time()+max(1, float(settings.get("graph_refresh_days", 7)))*86400}
        db.add(Job(id=identifier, kind="graph_refresh", layer=layer, payload={key: value for key, value in specification.items() if key in {"url", "method", "body", "format"}}))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    owner = os.getenv("SMART_CITY_WORKER_OWNER") or "worker-"+secrets.token_hex(8)
    initialize_solver(owner)
    last_maintenance = 0
    while True:
        if time.time()-last_maintenance >= max(1, float(load_settings().get("expiry_check_seconds", 60))):
            maintenance()
            last_maintenance = time.time()
        worked = process_one(owner)
        if args.once:
            return
        if not worked:
            time.sleep(1)

if __name__ == "__main__":
    main()
