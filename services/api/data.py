from __future__ import annotations
from . import schemas
from .security import require_operator, require_verifier, require_admin
import hashlib
import copy
import time
import json
from sqlalchemy import select, text
from fastapi import APIRouter, Depends, HTTPException, Request
from .db import State, get_db, utcnow
from .security import current_user, read_layer
from .reports import STAFF, allowed_layer
from .store import add_entity, audit, begin_write, ensure_asset, finish_write, get_entity, graph_snapshot, instant, items, mutate, public_payload, publish_change, require_text, serial, state, validate_interval
from services.settings import load_settings

router = APIRouter()

@router.get("/sources")
def sources(request: Request, layer: str = "fixture", db=Depends(get_db, scope="function")):
    read_layer(db, request, layer)
    return [public_payload(serial(x)) for x in items(db, "source", layer)]

@router.get("/sources/{source_id}")
def source_detail(source_id: str, request: Request, db=Depends(get_db, scope="function")) -> schemas.RecordReply:
    current_user(db, request, True, STAFF | {"verifier"})
    source = get_entity(db, source_id, "source")
    return {**serial(source), "snapshots": [serial(x) for x in items(db, "source_snapshot", source.layer) if x.data["source_id"] == source.id]}

@router.post("/sources", status_code=201)
def create_source(body: schemas.SourceCreate, request: Request, db=Depends(get_db, scope="function"), authorized=Depends(require_operator)) -> schemas.RecordReply:
    user = current_user(db, request, True, STAFF)
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    layer = body.get("layer", "fixture")
    allowed_layer(user, layer)
    raw = body.get("raw_text", "")
    fetched = None
    if body.get("fetch"):
        from ingest import safe_fetch, fetch_firecrawl
        try:
            fetched = (fetch_firecrawl if body.get("provider") == "firecrawl" else safe_fetch)(body.get("url", ""))
            raw = fetched["text"]
        except Exception as exc:
            raise HTTPException(422, f"Nie udało się pobrać źródła: {str(exc)[:200]}")
    if len(raw) > 2_000_000:
        raise HTTPException(413, "Zbyt duży dokument źródłowy.")
    original = fetched.get("raw", raw) if fetched else raw
    raw_hash = fetched.get("sha256") if fetched else hashlib.sha256(original.encode()).hexdigest()
    default_interval = max(60, int(load_settings().get("source_refresh_minutes", 30))*60)
    try:
        interval = max(default_interval, int(body.get("refresh_interval_s", default_interval)))
    except (ValueError, TypeError):
        raise HTTPException(422, "Częstotliwość odświeżania wymaga liczby sekund.")
    source = add_entity(db, "source", layer, {"title": require_text(body, "title", 3, 300), "url": body.get("url"), "publisher": require_text(body, "publisher", 2, 300), "published_at": body.get("published_at"), "observed_at": body.get("observed_at"), "fetched_at": fetched.get("fetched_at") if fetched else None, "license": body.get("license", "unknown"), "raw_text": raw, "sha256": raw_hash, "text_sha256": hashlib.sha256(raw.encode()).hexdigest(), "status": "needs_review", "provider": body.get("provider", "direct"), "refresh_enabled": bool(body.get("refresh_enabled") and body.get("url")), "refresh_interval_s": interval, "next_refresh_at": time.time()+interval})
    add_entity(db, "source_snapshot", layer, {"source_id": source.id, "raw": original, "text": raw, "sha256": raw_hash, "text_sha256": source.data["text_sha256"], "fetched_at": source.data["fetched_at"], "published_at": source.data["published_at"], "observed_at": source.data["observed_at"]})
    audit(db, user, "source_created", source)
    return finish_write(db, ctx, serial(source))

@router.post("/sources/{source_id}/extract")
def extract(source_id: str, body: schemas.SourceExtract, request: Request, db=Depends(get_db, scope="function"), authorized=Depends(require_operator)) -> schemas.RecordReply:
    user = current_user(db, request, True, STAFF)
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    source = get_entity(db, source_id, "source")
    allowed_layer(user, source.layer)
    from ingest import extract_candidate
    try:
        candidate = extract_candidate(source.data.get("raw_text", ""), use_ai=bool(body.get("use_ai", False)))
    except Exception as exc:
        raise HTTPException(422, f"Nie udało się przygotować kandydatury: {str(exc)[:200]}")
    entity = add_entity(db, "candidate", source.layer, {**candidate, "source_id": source.id})
    audit(db, user, "source_extracted", entity)
    return finish_write(db, ctx, serial(entity))

@router.get("/restrictions")
def restrictions(request: Request, layer: str = "fixture", db=Depends(get_db, scope="function")):
    read_layer(db, request, layer)
    return public_payload(graph_snapshot(db, layer).get("restrictions", []))

@router.post("/restrictions", status_code=201)
def create_restriction(body: schemas.RestrictionCreate, request: Request, db=Depends(get_db, scope="function"), authorized=Depends(require_operator)) -> schemas.RecordReply:
    user = current_user(db, request, True, STAFF)
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    layer = body.get("layer", "fixture")
    allowed_layer(user, layer)
    ensure_asset(db, layer, body.get("asset_id"))
    source = get_entity(db, body.get("source_id", ""), "source")
    if source.layer != layer:
        raise HTTPException(422, "Źródło i ograniczenie muszą być w tej samej warstwie.")
    start, end = validate_interval(body, "start", "end")
    if body.get("pedestrian_impact") not in {True, False, None}:
        raise HTTPException(422, "Wpływ na pieszych wymaga true, false lub null.")
    confirmed = body.get("pedestrian_impact") is True and body.get("geometry_reviewed") is True
    from domain.graph.routing import INVALIDATABLE_FEATURES
    invalidated = body.get("invalidated_features")
    if invalidated is not None and (not isinstance(invalidated, list) or any(not isinstance(feature, str) or feature not in INVALIDATABLE_FEATURES for feature in invalidated)):
        raise HTTPException(422, "Wskaż listę cech wymagających nowego pomiaru albo null dla nieznanego zakresu zmiany.")
    data = {"asset_id": body["asset_id"], "source_id": source.id, "start": start, "end": end, "kind": "closure" if confirmed else "warning", "status": "confirmed" if confirmed else "unverified", "side": body.get("side"), "level": body.get("level"), "pedestrian_impact": body.get("pedestrian_impact"), "reason": require_text(body, "reason", 3, 4000), "reviewer": user.id, "verified_open_at": None, "invalidated_features": sorted(set(invalidated)) if invalidated is not None else None}
    if body.get("pedestrian_impact") is False:
        data["status"] = "no_pedestrian_impact"
    restriction = add_entity(db, "restriction", layer, data)
    version = publish_change(db, layer, "restriction_published") if data["status"] != "no_pedestrian_impact" else state(db, layer)["data_version"]
    audit(db, user, "restriction_published", restriction)
    return finish_write(db, ctx, {**serial(restriction), "data_version": version})

@router.post("/restrictions/{restriction_id}/open")
def open_restriction(restriction_id: str, body: schemas.RestrictionOpen, request: Request, db=Depends(get_db, scope="function"), authorized=Depends(require_operator)) -> schemas.RecordReply:
    user = current_user(db, request, True, STAFF)
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    layer = body.get("layer", "fixture")
    allowed_layer(user, layer)
    evidence = get_entity(db, body.get("evidence_id", ""), "evidence")
    ensure_asset(db, layer, evidence.data.get("asset_id"))
    existing = next((r for r in graph_snapshot(db, layer).get("restrictions", []) if r["id"] == restriction_id), None)
    if not existing:
        raise HTTPException(404, "Nie znaleziono ograniczenia.")
    if evidence.layer != layer or evidence.data.get("asset_id") != existing.get("asset_id") or evidence.data.get("status") != "confirmed" or evidence.data.get("feature") != "open" or evidence.data.get("value") is not True or evidence.data.get("method") in {"fixture", "controlled_fixture"}:
        raise HTTPException(422, "Wymagana nowa opublikowana obserwacja otwarcia tego obiektu.")
    opened_at = body.get("observed_at", evidence.data.get("observed_at"))
    if instant(opened_at) != instant(evidence.data.get("observed_at")):
        raise HTTPException(422, "Czas otwarcia musi być czasem zapisanej obserwacji. Nie można przesunąć daty dowodu.")
    if instant(opened_at) < instant(existing["start"]) or not instant(evidence.data["valid_from"]) <= instant(opened_at) < instant(evidence.data["valid_until"]):
        raise HTTPException(422, "Czas otwarcia musi należeć do okresu dowodu i następować po rozpoczęciu ograniczenia.")
    from .db import Entity
    restriction = db.get(Entity, restriction_id)
    if restriction and restriction.layer != layer:
        raise HTTPException(409, "Identyfikator ograniczenia należy do innej warstwy.")
    if not restriction:
        restriction = add_entity(db, "restriction", layer, existing, restriction_id)
    before = serial(restriction)
    mutate(db, restriction, body, {**restriction.data, "verified_open_at": instant(opened_at).isoformat(), "opening_evidence_id": evidence.id, "opening_reason": require_text(body, "reason", 3, 4000)})
    version = publish_change(db, layer, "opening_observed")
    audit(db, user, "restriction_opening_observed", restriction, before)
    return finish_write(db, ctx, {**serial(restriction), "data_version": version})

@router.get("/imports")
def imports(request: Request, layer: str = "fixture", db=Depends(get_db, scope="function")):
    current_user(db, request, True, STAFF)
    return [serial(x) for x in items(db, "import", layer)]

@router.post("/imports", status_code=201)
def import_data(body: schemas.ImportCreate, request: Request, db=Depends(get_db, scope="function"), authorized=Depends(require_operator)) -> schemas.RecordReply:
    user = current_user(db, request, True, STAFF)
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    layer = body.get("layer", "observed")
    allowed_layer(user, layer)
    content = body.get("content")
    if len(json.dumps(content)) > 20_000_000:
        raise HTTPException(413, "Import przekracza 20 MB.")
    from ingest import import_csv, import_geojson, import_osm
    fmt = body.get("format")
    try:
        parsed = json.loads(content) if fmt in {"osm", "geojson"} and isinstance(content, str) else content
        if fmt == "csv":
            result = import_csv(content)
        elif fmt == "geojson":
            result = import_geojson(parsed)
        elif fmt == "osm":
            result = import_osm(parsed)
        else:
            raise ValueError("Dostępne formaty: osm, geojson, csv")
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc))
    imported = add_entity(db, "import", layer, {"format": fmt, "status": "staged", "result": result, "source_id": body.get("source_id"), "sha256": hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()})
    if fmt != "csv":
        graph = result.get("graph", result)
        graph["layer"] = layer
        staged = add_entity(db, "graph", layer, {"graph": graph, "status": "staged", "import_id": imported.id, "bindings": body.get("bindings", {})})
        imported.data = {**imported.data, "graph_id": staged.id}
    audit(db, user, "data_imported", imported)
    return finish_write(db, ctx, serial(imported))

@router.get("/graphs")
def graphs(request: Request, layer: str = "fixture", db=Depends(get_db, scope="function")):
    current_user(db, request, True, STAFF)
    return [serial(x) for x in items(db, "graph", layer)]

@router.post("/graphs/staging", status_code=201)
def stage_graph(body: schemas.GraphStage, request: Request, db=Depends(get_db, scope="function"), authorized=Depends(require_operator)) -> schemas.RecordReply:
    user = current_user(db, request, True, STAFF)
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    layer = body.get("layer", "observed")
    allowed_layer(user, layer)
    if not isinstance(body.get("graph"), dict):
        raise HTTPException(422, "Wymagany graf JSON.")
    graph = {**body["graph"], "layer": layer}
    entity = add_entity(db, "graph", layer, {"graph": graph, "status": "staged", "bindings": body.get("bindings", {})})
    audit(db, user, "graph_staged", entity)
    return finish_write(db, ctx, serial(entity))


@router.post("/graphs/{graph_id}/edit")
def edit_staged_graph(graph_id: str, body: schemas.GraphEdit, request: Request, db=Depends(get_db, scope="function"), authorized=Depends(require_operator)) -> schemas.RecordReply:
    user = current_user(db, request, True, STAFF)
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    entity = get_entity(db, graph_id, "graph")
    allowed_layer(user, entity.layer)
    if entity.data.get("status") == "published":
        raise HTTPException(409, "Opublikowany graf jest niezmienny. Utwórz nową wersję w stagingu.")
    if "graph" in body and not isinstance(body["graph"], dict) or "graph_patch" in body and not isinstance(body["graph_patch"], dict):
        raise HTTPException(422, "Graf i poprawki wymagają obiektu JSON.")
    graph = copy.deepcopy(body.get("graph", entity.data["graph"]))
    graph.update(copy.deepcopy(body.get("graph_patch", {})))
    graph["layer"] = entity.layer
    if len(json.dumps(graph)) > 20_000_000:
        raise HTTPException(413, "Graf przekracza 20 MB.")
    before = serial(entity)
    data = {k: v for k, v in entity.data.items() if k not in {"quality", "published_at"}}
    data.update(graph=graph, status="staged", bindings=body.get("bindings", entity.data.get("bindings", {})))
    mutate(db, entity, body, data)
    audit(db, user, "staged_graph_edited", entity, before)
    return finish_write(db, ctx, serial(entity))

def validate_graph(db, entity):
    from domain.graph import validate_graph as domain_validate, rebind_assets
    graph = copy.deepcopy(entity.data["graph"])
    graph["version"] = entity.id
    preliminary = domain_validate(graph)
    if not preliminary["valid"] and any(e["code"] not in {"missing_asset", "evidence_unknown_asset"} for e in preliminary["errors"]):
        return {"valid": False, "errors": preliminary["errors"], "warnings": preliminary["warnings"], "nodes": preliminary["node_count"], "edges": preliminary["edge_count"], "bindings": {}, "restrictions": [], "validated_graph": graph, "validated_at": utcnow()}
    active = state(db, entity.layer)
    old = graph_snapshot(db, entity.layer) if active["graph_id"] else graph
    old_assets = {a["id"]: a for a in old.get("assets", [])}
    for asset_id, edge_ids in entity.data.get("bindings", {}).items():
        if asset_id not in {a["id"] for a in graph.get("assets", [])} and asset_id in old_assets:
            graph.setdefault("assets", []).append(old_assets[asset_id])
        for edge in graph.get("edges", []):
            if edge["id"] in edge_ids:
                edge["asset_id"] = asset_id
    result = rebind_assets(old, graph, old.get("restrictions", []))
    if not graph.get("nodes") or not graph.get("edges"):
        result["publication_allowed"] = False
        result["validation"]["errors"].append({"code": "empty_graph"})
    return {"valid": result["publication_allowed"], "errors": result["validation"]["errors"]+result["unresolved"], "warnings": result["validation"]["warnings"], "nodes": len(graph.get("nodes", [])), "edges": len(graph.get("edges", [])), "bindings": {b["asset_id"]: b["edge_ids"] for b in result["bindings"]}, "restrictions": result["restrictions"], "validated_graph": graph, "unknown_attributes_remain_unknown": True, "validated_at": utcnow()}

@router.post("/graphs/{graph_id}/validate")
def check_graph(graph_id: str, body: schemas.GraphValidate, request: Request, db=Depends(get_db, scope="function"), authorized=Depends(require_operator)) -> schemas.RecordReply:
    user = current_user(db, request, True, STAFF)
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    entity = get_entity(db, graph_id, "graph")
    allowed_layer(user, entity.layer)
    if body.get("bindings") is not None:
        entity.data = {**entity.data, "bindings": body["bindings"]}
    quality = validate_graph(db, entity)
    mutate(db, entity, body, {**entity.data, "quality": quality, "status": "validated" if quality["valid"] else "blocked"})
    return finish_write(db, ctx, {**serial(entity), "quality": quality})

@router.post("/graphs/{graph_id}/publish")
def publish_graph(graph_id: str, body: schemas.VersionPayload, request: Request, db=Depends(get_db, scope="function"), authorized=Depends(require_admin)) -> schemas.RecordReply:
    user = current_user(db, request, True, {"admin"})
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    entity = get_entity(db, graph_id, "graph")
    allowed_layer(user, entity.layer)
    db.scalar(select(State).where(State.key == f"layer:{entity.layer}").with_for_update())
    quality = validate_graph(db, entity)
    if not quality["valid"]:
        raise HTTPException(409, quality)
    graph = quality.pop("validated_graph")
    graph["restrictions"] = quality["restrictions"]
    graph["bindings"] = [{"asset_id": asset, "edge_ids": edges, "graph_version": entity.id} for asset, edges in quality["bindings"].items()]
    for asset_id, edge_ids in quality["bindings"].items():
        if asset_id not in {x["id"] for x in graph.get("assets", [])}:
            graph.setdefault("assets", []).append({"id": asset_id, "name": "Powiązany obiekt", "type": "retained_restriction_asset"})
        for edge in graph.get("edges", []):
            if edge["id"] in edge_ids:
                edge["asset_id"] = asset_id
    mutate(db, entity, body, {**entity.data, "graph": graph, "status": "published", "quality": quality, "published_at": utcnow()})
    active = db.get(State, f"layer:{entity.layer}")
    if active:
        active.value = {**active.value, "graph_id": entity.id}
    else:
        db.add(State(key=f"layer:{entity.layer}", value={"graph_id": entity.id, "data_version": 0}))
        db.flush()
    version = publish_change(db, entity.layer, "graph_published")
    if db.bind.dialect.name == "postgresql":
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        for edge in graph.get("edges", []):
            a, b = nodes[edge["u"]], nodes[edge["v"]]
            coordinates = edge.get("geometry") or [[a["lon"], a["lat"]], [b["lon"], b["lat"]]]
            if isinstance(coordinates, dict):
                coordinates = coordinates.get("coordinates", [])
            geometry = json.dumps({"type": "LineString", "coordinates": coordinates})
            db.execute(text("INSERT INTO graph_geometries(graph_id,edge_id,asset_id,geom) VALUES (:graph,:edge,:asset,ST_SetSRID(ST_GeomFromGeoJSON(:geometry),4326)) ON CONFLICT(graph_id,edge_id) DO UPDATE SET geom=EXCLUDED.geom,asset_id=EXCLUDED.asset_id"), {"graph": entity.id, "edge": edge["id"], "asset": edge.get("asset_id"), "geometry": geometry})
    audit(db, user, "graph_published", entity)
    return finish_write(db, ctx, {"id": entity.id, "version": entity.version, "data_version": version, "status": "published"})
