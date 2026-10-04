from __future__ import annotations
from . import schemas
from .security import require_operator, require_verifier, require_admin
import csv
import io
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from domain.graph.routing import ALGORITHM_VERSION
from services.version import code_version
from services.settings import analysis_time_limit
from .db import Job, get_db, utcnow
from .security import current_user
from .store import add_entity, audit, begin_write, finish_write, get_entity, graph_snapshot, instant, items, mutate, public_payload, require_text, serial, state, uid
from .reports import STAFF, allowed_layer

router = APIRouter()

@router.get("/scenarios")
def scenarios(request: Request, layer: str = "fixture", db=Depends(get_db, scope="function")) -> list[schemas.RecordReply]:
    current_user(db, request, True, STAFF)
    return [serial(x) for x in items(db, "scenario", layer)]

@router.post("/scenarios", status_code=201)
def create_scenario(body: schemas.ScenarioCreate, request: Request, db=Depends(get_db, scope="function"), authorized=Depends(require_operator)) -> schemas.RecordReply:
    user = current_user(db, request, True, STAFF)
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    layer = body.get("layer", "fixture")
    allowed_layer(user, layer)
    graph = graph_snapshot(db, layer)
    scenario = add_entity(db, "scenario", layer, {"name": require_text(body, "name", 3, 300), "status": "draft", "request": body.get("request", {}), "graph_snapshot": graph, "snapshot_versions": {"graph": graph["version"], "data": graph["data_version"], "profiles": 1, "places": 1, "algorithm": ALGORITHM_VERSION, "code": code_version()}, "owner": user.id, "assumptions": body.get("assumptions", []), "evaluations": [], "decision_history": []})
    audit(db, user, "scenario_created", scenario)
    return finish_write(db, ctx, serial(scenario))

@router.get("/scenarios/{scenario_id}")
def scenario_detail(scenario_id: str, request: Request, db=Depends(get_db, scope="function")) -> schemas.RecordReply:
    current_user(db, request, True, STAFF)
    return serial(get_entity(db, scenario_id, "scenario"))

@router.post("/scenarios/{scenario_id}/evaluate", status_code=202)
def evaluate_scenario(scenario_id: str, body: schemas.ScenarioEvaluate, request: Request, db=Depends(get_db, scope="function"), authorized=Depends(require_operator)) -> schemas.JobReply:
    user = current_user(db, request, True, STAFF)
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    scenario = get_entity(db, scenario_id, "scenario")
    allowed_layer(user, scenario.layer)
    if scenario.data["status"] not in {"draft", "evaluated"}:
        raise HTTPException(409, "Przyjęty plan wymaga nowego scenariusza, aby zmienić analizę.")
    job_id = uid("job")
    before = serial(scenario)
    data = {**scenario.data, "pending_job_id": job_id, "request": body.get("request", scenario.data["request"])}
    mutate(db, scenario, body, data)
    job = Job(id=job_id, kind="evaluation", layer=scenario.layer, payload={"scenario_id": scenario.id, "expected_version": scenario.version, "graph": scenario.data["graph_snapshot"], "request": data["request"], "requested_by": user.id})
    db.add(job)
    audit(db, user, "evaluation_requested", scenario, before)
    return finish_write(db, ctx, {"job_id": job_id, "scenario_id": scenario.id, "version": scenario.version, "status": "queued"})

@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request, db=Depends(get_db, scope="function")) -> schemas.JobReply:
    current_user(db, request, True, STAFF | {"verifier"})
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Nie znaleziono zadania.")
    return {"id": job.id, "job_id": job.id, "status": job.status, "progress": job.progress, "result": job.result, "error": job.error, "attempts": job.attempts, "created_at": job.created_at, "finished_at": job.finished_at}

@router.post("/scenarios/{scenario_id}/decision")
def decision(scenario_id: str, body: schemas.ScenarioDecision, request: Request, db=Depends(get_db, scope="function"), authorized=Depends(require_operator)) -> schemas.RecordReply:
    user = current_user(db, request, True, STAFF)
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    scenario = get_entity(db, scenario_id, "scenario")
    allowed_layer(user, scenario.layer)
    status = body.get("status")
    transitions = {"evaluated": "approved_plan", "approved_plan": "in_progress", "in_progress": "performed", "performed": "effect_reviewed"}
    if transitions.get(scenario.data["status"]) != status:
        raise HTTPException(409, {"message": "Niedozwolony krok procesu.", "current_status": scenario.data["status"], "next_status": transitions.get(scenario.data["status"])})
    if status != "approved_plan" and body.get("variant_id") not in {None, scenario.data.get("decision", {}).get("variant_id")}:
        raise HTTPException(409, "Zatwierdzony wariant jest niezmienny. Zmiana wymaga nowego scenariusza i decyzji.")
    if status == "approved_plan":
        require_text(body, "owner", 2, 300)
        require_text(body, "conditions", 3, 4000)
        if not scenario.data.get("latest_result"):
            raise HTTPException(422, "Zatwierdzenie wymaga ukończonej oceny wariantu.")
        if state(db, scenario.layer)["data_version"] != scenario.data["snapshot_versions"]["data"]:
            raise HTTPException(409, "Dane zmieniły się od zamrożenia scenariusza. Utwórz analizę na aktualnych danych.")
        variant_id = body.get("variant_id", scenario.data["latest_result"].get("recommended_id"))
        variants = scenario.data["latest_result"].get("variants", [])
        variant = next((x for x in variants if x.get("id") == variant_id), None)
        if not variant or not variant.get("feasible") or not variant.get("critical_satisfied") or not variant.get("complete"):
            raise HTTPException(422, "Wybierz wykonalny wariant oceniony w tym scenariuszu.")
    evidence_ids = body.get("evidence_ids", [])
    if status in {"performed", "effect_reviewed"}:
        if not evidence_ids:
            raise HTTPException(422, "Wykonanie i ocena efektu wymagają nowych dowodów.")
        execution_started = next((entry["at"] for entry in reversed(scenario.data["decision_history"]) if entry["status"] == "in_progress"), scenario.created_at)
        chosen_id = scenario.data.get("decision", {}).get("variant_id")
        variant = next((v for v in scenario.data.get("latest_result", {}).get("variants", []) if v.get("id") == chosen_id), {})
        original = {r["id"]: r for r in scenario.data["graph_snapshot"].get("restrictions", [])}
        required = {(r["asset_id"], "open") for r in variant.get("restrictions", []) if r.get("asset_id") and (r["id"] not in original or any(r.get(k) != original[r["id"]].get(k) for k in ("start", "end", "verified_open_at")))}
        for action in variant.get("actions", []):
            for feature in action.get("features", [action]):
                asset_id = feature.get("asset_id", action.get("asset_id"))
                if asset_id:
                    required.add((asset_id, feature.get("feature", "open")))
        proven = set()
        for identifier in evidence_ids:
            evidence = get_entity(db, identifier, "evidence")
            if evidence.layer != scenario.layer or evidence.data.get("status") != "confirmed" or evidence.data.get("method") in {"controlled_fixture", "fixture"} or evidence.created_at < execution_started:
                raise HTTPException(422, "Wymagany nowy opublikowany dowód; początkowy fixture nie jest dowodem wykonania.")
            if scenario.layer == "observed" and (instant(evidence.data.get("observed_at")) < instant(execution_started) or not instant(evidence.data["valid_from"]) <= datetime.now(timezone.utc) < instant(evidence.data["valid_until"])):
                raise HTTPException(422, "Obserwacja wykonania musi nastąpić po rozpoczęciu realizacji i nadal być aktualna.")
            proven.add((evidence.data.get("asset_id"), evidence.data.get("feature")))
        if required and not required.issubset(proven):
            raise HTTPException(422, {"message": "Dowody muszą dotyczyć wykonanych działań i ich cech.", "required": sorted(required), "proven": sorted(proven)})
    before = serial(scenario)
    entry = {"status": status, "at": utcnow(), "actor": user.id, **{k:body[k] for k in ("owner", "executor", "conditions", "variant_id", "evidence_ids", "notes", "due_at") if k in body}}
    if status == "approved_plan":
        entry["variant_id"] = variant_id
    data = {**scenario.data, "status": status, "decision_history": scenario.data["decision_history"]+[entry], "decision": {**scenario.data.get("decision", {}), **entry}}
    if status == "effect_reviewed":
        data["effect_review"] = compute_effect(db, scenario, evidence_ids)
    mutate(db, scenario, body, data)
    record = add_entity(db, "decision", scenario.layer, {**entry, "scenario_id": scenario.id})
    audit(db, user, "decision_transition", scenario, before)
    return finish_write(db, ctx, serial(scenario))

def compute_effect(db, scenario, evidence_ids=None):
    from domain.graph import evaluate
    from domain.graph.planning import normalize_request
    graph = graph_snapshot(db, scenario.layer)
    baseline_request = {k: v for k, v in scenario.data["request"].items() if k not in {"restrictions", "actions", "variants"}}
    baseline_request["variants"] = []
    baseline_request["time_limit_s"] = analysis_time_limit(baseline_request)
    # Resolve defaults and named profiles against the original snapshot once.
    # A newly published graph must not change this comparison's denominator,
    # mobility limits, destinations or departure horizon.
    baseline_request = normalize_request(scenario.data["graph_snapshot"], baseline_request)
    before = evaluate(scenario.data["graph_snapshot"], baseline_request)
    # A partial profile also freezes the absence of optional requirements. Keep
    # its original profile definitions as the base, so later profile settings
    # cannot introduce a new constraint through profile_for's override merging.
    comparison_graph = {**graph, "profiles": scenario.data["graph_snapshot"].get("profiles", [])}
    after = evaluate(comparison_graph, baseline_request)
    selected_variant_id = scenario.data.get("decision", {}).get("variant_id")
    planned_variant = next((variant for variant in scenario.data.get("latest_result", {}).get("variants", []) if variant.get("id") == selected_variant_id), None)
    return {"layer": scenario.layer, "simulated": scenario.layer == "fixture", "before": before.get("baseline", before), "after": after.get("baseline", after), "planned": scenario.data.get("latest_result"), "selected_variant_id": selected_variant_id, "planned_variant": planned_variant, "evidence_ids": evidence_ids or scenario.data.get("decision", {}).get("evidence_ids", []), "before_data_version": scenario.data["snapshot_versions"]["data"], "after_data_version": graph["data_version"], "reviewed_at": utcnow(), "attribution": "Porównanie przed i po nie dowodzi przyczynowości. Inne roboty i zmiany danych mogą wpływać na wynik.", "unresolved": [e["id"] for e in graph.get("evidence", []) if e.get("status") in {"conflicted", "expired"}], "other_changes": graph["data_version"] - scenario.data["snapshot_versions"]["data"]}

@router.get("/scenarios/{scenario_id}/effects")
def effects(scenario_id: str, request: Request, db=Depends(get_db, scope="function")):
    current_user(db, request, True, STAFF)
    scenario = get_entity(db, scenario_id, "scenario")
    if scenario.data["status"] not in {"performed", "effect_reviewed"}:
        raise HTTPException(409, "Porównanie efektu jest dostępne po wykonaniu z dowodami.")
    return scenario.data.get("effect_review") or compute_effect(db, scenario)

def safe_cell(value):
    text = str(value if value is not None else "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text

@router.get("/exports/{scenario_id}")
def export(scenario_id: str, request: Request, format: str = "json", db=Depends(get_db, scope="function")):
    current_user(db, request, True, STAFF)
    scenario = get_entity(db, scenario_id, "scenario")
    exported = public_payload({"id": scenario.id, "name": scenario.data["name"], "layer": scenario.layer, "simulated": True, "status": scenario.data["status"], "versions": scenario.data["snapshot_versions"], "algorithm_version": scenario.data["snapshot_versions"].get("algorithm", ALGORITHM_VERSION), "evaluated_code_version": scenario.data.get("latest_result", {}).get("evaluated_code_version"), "graph_snapshot": scenario.data["graph_snapshot"], "request": scenario.data["request"], "result": scenario.data.get("latest_result"), "effect_review": scenario.data.get("effect_review"), "assumptions": scenario.data.get("assumptions", []), "notice": "Wynik scenariusza jest warunkową prognozą; dane fixture są syntetyczne."})
    headers = {"Content-Disposition": f'attachment; filename="{scenario.id}.{format}"'}
    if format == "json":
        return Response(json.dumps(exported, ensure_ascii=False, indent=2), media_type="application/json", headers=headers)
    if format == "csv":
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["scenario", "layer", "simulation", "variant", "metric", "value"])
        result = scenario.data.get("latest_result", {})
        for variant in [result.get("baseline", {})]+result.get("variants", []):
            for metric, value in variant.get("metrics", variant).items():
                if isinstance(value, (str, int, float, bool)):
                    writer.writerow([safe_cell(scenario.data["name"]), scenario.layer, "true", safe_cell(variant.get("id", "baseline")), safe_cell(metric), safe_cell(value)])
        return Response("\ufeff"+stream.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)
    if format == "geojson":
        graph = scenario.data["graph_snapshot"]
        nodes = {x["id"]: x for x in graph.get("nodes", [])}
        features = []
        for edge in graph.get("edges", []):
            a, b = nodes.get(edge["u"]), nodes.get(edge["v"])
            if a and b:
                geometry = edge.get("geometry") or {"type": "LineString", "coordinates": edge.get("coordinates", [[a["lon"], a["lat"]], [b["lon"], b["lat"]]])}
                if isinstance(geometry, list):
                    geometry = {"type": "LineString", "coordinates": geometry}
                features.append({"type": "Feature", "geometry": geometry, "properties": {"edge_id": edge["id"], "asset_id": edge.get("asset_id"), "layer": scenario.layer, "simulated": True}})
        return Response(json.dumps({"type": "FeatureCollection", "features": features, "metadata": exported}, ensure_ascii=False), media_type="application/geo+json", headers=headers)
    raise HTTPException(422, "Dostępne formaty: json, csv, geojson.")
