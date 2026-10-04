from __future__ import annotations
import copy
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select, update
from .db import AuditEvent, Entity, Idempotency, Job, OutboxEvent, State, utcnow

LAYERS = {"fixture", "observed", "planned", "scenario"}

def uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:20]}"

def serial(entity):
    return {**entity.data, "id": entity.id, "layer": entity.layer, "version": entity.version, "created_at": entity.created_at, "updated_at": entity.updated_at}

def items(db, kind, layer="fixture"):
    return list(db.scalars(select(Entity).where(Entity.kind == kind, Entity.layer == layer).order_by(Entity.created_at)))

def get_entity(db, identifier, kind=None):
    entity = db.get(Entity, identifier)
    if not entity or kind and entity.kind != kind:
        raise HTTPException(404, "Nie znaleziono wpisu.")
    return entity

def add_entity(db, kind, layer, data, identifier=None):
    if layer not in LAYERS:
        raise HTTPException(422, "Nieznana warstwa danych.")
    entity = Entity(id=identifier or uid(kind), kind=kind, layer=layer, data=copy.deepcopy(data))
    db.add(entity)
    db.flush()
    return entity

def mutate(db, entity, body, data):
    expected = body.get("expected_version")
    if expected is None:
        raise HTTPException(428, "Podaj expected_version, aby uniknąć nadpisania innej zmiany.")
    count = db.execute(update(Entity).where(Entity.id == entity.id, Entity.version == expected).values(data=copy.deepcopy(data), version=expected+1, updated_at=utcnow()), execution_options={"synchronize_session": False}).rowcount
    if count != 1:
        raise HTTPException(409, {"message": "Wpis został zmieniony. Pobierz bieżącą wersję.", "current_version": entity.version})
    db.expire(entity)
    db.refresh(entity)
    return entity

def audit(db, user, action, entity, before=None):
    db.add(AuditEvent(actor=user.id if user else "anonymous", action=action, entity_id=entity.id, layer=entity.layer, before=before, after=serial(entity)))

def begin_write(db, request, body, user):
    key = request.headers.get("idempotency-key")
    if not key or not 8 <= len(key) <= 120:
        raise HTTPException(428, "Wymagany Idempotency-Key (8-120 znaków).")
    key = hashlib.sha256(f"{user.id if user else 'anonymous'}:{key}".encode()).hexdigest()
    signature = hashlib.sha256(json.dumps({"method": request.method, "path": request.url.path, "body": body}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    prior = db.get(Idempotency, key)
    if prior:
        if prior.request_hash != signature:
            raise HTTPException(409, "Ten klucz został użyty dla innego żądania.")
        return key, signature, prior.response
    return key, signature, None

def finish_write(db, context, response):
    db.add(Idempotency(key=context[0], request_hash=context[1], response=response))
    db.flush()
    return response

def state(db, layer="fixture"):
    found = db.get(State, f"layer:{layer}")
    return copy.deepcopy(found.value) if found else {"data_version": 0, "graph_id": None}

def publish_change(db, layer, reason):
    entry = db.scalar(select(State).where(State.key == f"layer:{layer}").with_for_update())
    if not entry:
        entry = State(key=f"layer:{layer}", value={"data_version": 0, "graph_id": None})
        db.add(entry)
    entry.value = {**entry.value, "data_version": entry.value["data_version"]+1, "updated_at": utcnow()}
    version = entry.value["data_version"]
    db.add(OutboxEvent(layer=layer, event="data_published", version=version, data={"reason": reason}))
    db.add(Job(id=uid("job"), kind="refresh", layer=layer, payload={"data_version": version}))
    return version

def public_payload(value):
    """Internal provenance keeps authors; public travel responses do not."""
    private = {"author", "photo_id", "photo_ids", "notes", "token_hash", "contact", "raw_text", "storage_path", "reviewer", "requested_by"}
    if isinstance(value, list):
        return [public_payload(v) for v in value]
    if isinstance(value, dict):
        return {k: public_payload(v) for k, v in value.items() if k not in private}
    return value

def graph_snapshot(db, layer="fixture"):
    active = state(db, layer)
    if not active["graph_id"]:
        raise HTTPException(404, "Warstwa nie ma opublikowanego grafu. Importuj i sprawdź dane.")
    graph = copy.deepcopy(get_entity(db, active["graph_id"], "graph").data["graph"])
    graph["layer"] = layer
    graph["version"] = active["graph_id"]
    evidence = {x["id"]: x for x in graph.get("evidence", [])}
    for entity in items(db, "evidence", layer):
        if entity.data.get("status") in {"confirmed", "conflicted", "expired", "superseded"}:
            evidence[entity.id] = {**entity.data, "id": entity.id, "layer": layer}
    graph["evidence"] = list(evidence.values())
    restrictions = {x["id"]: x for x in graph.get("restrictions", [])}
    for entity in items(db, "restriction", layer):
        if entity.data.get("status") not in {"retired", "no_pedestrian_impact"}:
            restrictions[entity.id] = {**entity.data, "id": entity.id, "layer": layer}
        else:
            restrictions.pop(entity.id, None)
    graph["restrictions"] = list(restrictions.values())
    graph["data_version"] = active["data_version"]
    return graph

def require_text(body, key, minimum=1, maximum=10000):
    value = body.get(key)
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise HTTPException(422, f"Pole {key}: wymagany tekst ({minimum}-{maximum} znaków).")
    return value.strip()

def instant(value, field="time"):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise HTTPException(422, f"Pole {field} wymaga pełnej daty i strefy czasowej.")

def validate_interval(body, start="valid_from", end="valid_until"):
    a, b = instant(body.get(start), start), instant(body.get(end), end)
    if b <= a:
        raise HTTPException(422, "Koniec okresu musi następować po początku.")
    return a.isoformat(), b.isoformat()

def ensure_asset(db, layer, asset_id):
    # Serialize asset-dependent writes with graph publication. Checking an old
    # graph and then publishing a restriction onto a new graph is not atomic.
    db.scalar(select(State).where(State.key == f"layer:{layer}").with_for_update())
    graph = graph_snapshot(db, layer)
    if asset_id not in {x["id"] for x in graph.get("assets", [])}:
        raise HTTPException(422, "Obiekt nie należy do aktywnego grafu tej warstwy.")
    return graph
