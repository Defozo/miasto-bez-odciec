from __future__ import annotations
from . import schemas
from .security import require_operator, require_verifier, require_admin
import hashlib
import io
import os
import secrets
import math
from pathlib import Path
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from services.settings import load_settings
from .db import Entity, get_db, utcnow
from .security import current_user, digest, read_layer
from .store import add_entity, audit, begin_write, ensure_asset, finish_write, get_entity, graph_snapshot, instant, items, mutate, public_payload, publish_change, require_text, serial, uid, validate_interval

router = APIRouter()
STAFF = {"operator", "admin"}

def allowed_layer(user, layer):
    if user and user.id.startswith("demo-") and layer != "fixture":
        raise HTTPException(403, "Lokalna sesja demonstracyjna może zmieniać wyłącznie dane fixture.")

def public_report(entity):
    return {k: v for k, v in serial(entity).items() if k not in {"token_hash", "contact"}}

@router.post("/reports", status_code=201)
def create_report(body: schemas.ReportCreate, request: Request, db=Depends(get_db, scope="function")) -> schemas.ReportReply:
    user = current_user(db, request)
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    layer = body.get("layer", "fixture")
    if layer not in {"fixture", "observed"}:
        raise HTTPException(403, "Zgłoszenie musi dotyczyć publicznej warstwy fixture lub observed.")
    if layer != "fixture" and os.getenv("SMART_CITY_ALLOW_PILOT_REPORTS", "false") != "true":
        raise HTTPException(403, "Przyjmowanie zgłoszeń pilota wymaga uruchomionego programu retencji i opiekuna danych.")
    allowed_layer(user, layer)
    description = require_text(body, "description", 5, 4000)
    ensure_asset(db, layer, body.get("asset_id"))
    if body.get("kind", "barrier") not in {"barrier", "opening", "measurement", "other"}:
        raise HTTPException(422, "Nieznany rodzaj zgłoszenia.")
    token = secrets.token_urlsafe(32)
    report = add_entity(db, "report", layer, {"description": description, "asset_id": body["asset_id"], "kind": body.get("kind", "barrier"), "feature": body.get("feature"), "status": "submitted", "physical_status": "unknown", "token_hash": digest(token), "history": [{"status": "submitted", "at": utcnow(), "reason": "Oczekuje na moderację. Zgłoszenie nie zmienia tras."}], "photo_ids": [], "submitted_at": utcnow()})
    audit(db, user, "report_submitted", report)
    return finish_write(db, ctx, {**public_report(report), "token": token})

@router.get("/reports")
def list_reports(request: Request, layer: str = "fixture", db=Depends(get_db, scope="function")) -> list[schemas.ReportReply]:
    current_user(db, request, True, STAFF)
    return [public_report(x) for x in items(db, "report", layer)]

@router.get("/reports/{report_id}")
def report_status(report_id: str, request: Request, token: str | None = None, db=Depends(get_db, scope="function")) -> schemas.ReportReply:
    report = get_entity(db, report_id, "report")
    user = current_user(db, request)
    token = request.headers.get("x-report-token", token)
    if not user and (not token or not secrets.compare_digest(digest(token), report.data["token_hash"])):
        raise HTTPException(404, "Nie znaleziono sprawy lub prywatny token jest nieprawidłowy.")
    return public_report(report)

@router.post("/reports/{report_id}/review")
def review_report(report_id: str, body: schemas.ReportReview, request: Request, db=Depends(get_db, scope="function"), authorized=Depends(require_operator)) -> schemas.ReportReply:
    user = current_user(db, request, True, STAFF)
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    report = get_entity(db, report_id, "report")
    allowed_layer(user, report.layer)
    reason = require_text(body, "reason", 3, 4000)
    action = body.get("action")
    statuses = {"locate_warning": "located_unverified", "confirm": "confirmed", "reject": "rejected", "resolve": "resolved", "needs_recheck": "needs_recheck"}
    if action not in statuses:
        raise HTTPException(422, "Nieznana decyzja moderacji.")
    allowed_actions = {"submitted": {"locate_warning", "confirm", "reject", "needs_recheck"}, "needs_review": {"locate_warning", "confirm", "reject"}, "located_unverified": {"locate_warning", "confirm", "reject", "needs_recheck", "resolve"}, "confirmed": {"resolve", "needs_recheck"}, "needs_recheck": {"locate_warning", "confirm", "resolve", "reject"}, "resolved": {"needs_recheck"}, "rejected": {"needs_recheck"}}
    if action not in allowed_actions.get(report.data["status"], set()):
        raise HTTPException(409, "Ta decyzja nie jest dozwolona w bieżącym stanie sprawy.")
    asset_id = body.get("asset_id", report.data["asset_id"])
    graph = ensure_asset(db, report.layer, asset_id)
    before = serial(report)
    data = {**report.data, "status": statuses[action], "asset_id": asset_id, "reviewer": user.id, "history": report.data.get("history", []) + [{"status": statuses[action], "at": utcnow(), "reason": reason, "actor": user.id}]}
    restriction_id = report.data.get("restriction_id")
    if action == "locate_warning":
        start = body.get("start", graph.get("clock", utcnow()))
        end = body.get("end", (instant(start)+timedelta(hours=4)).isoformat())
        start, end = validate_interval({"start": start, "end": end}, "start", "end")
        restriction_data = {"asset_id": asset_id, "kind": "warning", "status": "unverified", "start": start, "end": end, "report_id": report.id, "reason": reason}
        if restriction_id:
            restriction = get_entity(db, restriction_id, "restriction")
            mutate(db, restriction, {"expected_version": restriction.version}, restriction_data)
        else:
            restriction = add_entity(db, "restriction", report.layer, restriction_data)
        data["restriction_id"] = restriction.id
        publish_change(db, report.layer, "moderated_warning")
    if action in {"confirm", "resolve"}:
        evidence = get_entity(db, body.get("evidence_id", ""), "evidence")
        if evidence.layer != report.layer or evidence.data.get("asset_id") != asset_id or evidence.data.get("status") != "confirmed":
            raise HTTPException(422, "Wymagany opublikowany dowód dla tego obiektu i warstwy.")
        clock = instant(graph.get("clock", utcnow())) if report.layer == "fixture" else datetime.now(timezone.utc)
        if evidence.data.get("method") in {"fixture", "controlled_fixture"} or evidence.created_at < report.created_at or not instant(evidence.data["valid_from"]) <= clock < instant(evidence.data["valid_until"]):
            raise HTTPException(422, "Rozstrzygnięcie wymaga nowej obserwacji po zgłoszeniu, ważnej w chwili sprawdzenia.")
        if report.data["kind"] in {"barrier", "opening"}:
            desired_value = action == "resolve" or report.data["kind"] == "opening"
            if evidence.data.get("feature") != "open" or evidence.data.get("value") is not desired_value:
                raise HTTPException(422, "Potwierdzenie stanu fizycznego wymaga obserwacji otwarcia albo zamknięcia. Pomiar innej cechy jej nie zastępuje.")
        elif report.data["kind"] == "measurement" and report.data.get("feature") and evidence.data.get("feature") != report.data["feature"]:
            raise HTTPException(422, "Dowód musi dotyczyć cechy wskazanej w zgłoszeniu.")
        if action == "resolve" and not (evidence.data.get("feature") == "open" and evidence.data.get("value") is True):
            raise HTTPException(422, "Otwarcie wymaga nowej obserwacji otwarcia obiektu.")
        data["evidence_id"] = evidence.id
        data["physical_status"] = "open" if action == "resolve" else "observed"
        if restriction_id:
            restriction = get_entity(db, restriction_id, "restriction")
            mutate(db, restriction, {"expected_version": restriction.version}, {**restriction.data, "status": "retired", "resolved_by": evidence.id})
        publish_change(db, report.layer, "review_evidence")
    if action == "reject" and restriction_id:
        restriction = get_entity(db, restriction_id, "restriction")
        mutate(db, restriction, {"expected_version": restriction.version}, {**restriction.data, "status": "retired", "rejection_reason": reason})
        publish_change(db, report.layer, "warning_rejected")
    mutate(db, report, body, data)
    audit(db, user, "report_review", report, before)
    return finish_write(db, ctx, public_report(report))

@router.get("/tasks")
def list_tasks(request: Request, layer: str = "fixture", db=Depends(get_db, scope="function")) -> list[schemas.RecordReply]:
    current_user(db, request, True, STAFF | {"verifier"})
    return [serial(x) for x in items(db, "task", layer)]

@router.post("/tasks", status_code=201)
def create_task(body: schemas.TaskCreate, request: Request, db=Depends(get_db, scope="function"), authorized=Depends(require_operator)) -> schemas.RecordReply:
    user = current_user(db, request, True, STAFF)
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    layer = body.get("layer", "fixture")
    allowed_layer(user, layer)
    ensure_asset(db, layer, body.get("asset_id"))
    feature = body.get("property", body.get("feature"))
    if feature not in {"width_cm", "width_m", "slope_pct", "kerb_cm", "surface", "steps", "open", "lit", "entrance_open", "elevator_operational"}:
        raise HTTPException(422, "Wskaż konkretną cechę do sprawdzenia.")
    if body.get("report_id"):
        report = get_entity(db, body["report_id"], "report")
        if report.layer != layer:
            raise HTTPException(422, "Sprawa musi należeć do tej samej warstwy.")
        if report.data.get("asset_id") != body.get("asset_id"):
            raise HTTPException(422, "Kontrola powiązana ze sprawą musi dotyczyć tego samego obiektu.")
    data = {k: body.get(k) for k in ("asset_id", "unit", "report_id", "positive_effect", "negative_effect", "assignee", "due_at")}
    data.update({"title": require_text(body, "title", 3, 300), "feature": feature, "property": feature, "method": require_text(body, "method", 3, 2000), "status": "assigned", "created_by": user.id})
    task = add_entity(db, "task", layer, data)
    audit(db, user, "task_created", task)
    return finish_write(db, ctx, serial(task))

@router.post("/tasks/{task_id}/observe")
def observe(task_id: str, body: schemas.ObservationCreate, request: Request, db=Depends(get_db, scope="function"), authorized=Depends(require_verifier)) -> schemas.ObservationReply:
    user = current_user(db, request, True, STAFF | {"verifier"})
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    task = get_entity(db, task_id, "task")
    allowed_layer(user, task.layer)
    if task.data.get("status") not in {"assigned", "needs_recheck"}:
        raise HTTPException(409, "Zadanie ma już obserwację. Utwórz ponowną kontrolę zamiast nadpisywać protokół.")
    photo_id = body.get("photo_id")
    if photo_id is not None:
        if not isinstance(photo_id, str) or not photo_id or len(photo_id) > 80:
            raise HTTPException(422, "Wskaż identyfikator zdjęcia przypisanego do zadania.")
        photo = db.get(Entity, photo_id)
        if not photo or photo.kind != "photo":
            raise HTTPException(422, "Nie znaleziono zdjęcia pomiaru.")
        if photo.layer != task.layer:
            raise HTTPException(422, "Zdjęcie musi należeć do tej samej warstwy co zadanie.")
        direct = photo.data.get("task_id") == task.id
        related_report = task.data.get("report_id")
        from_report = bool(related_report and not photo.data.get("task_id") and photo.data.get("report_id") == related_report)
        if from_report:
            report = db.get(Entity, related_report)
            from_report = bool(report and report.kind == "report" and report.layer == task.layer and photo.id in report.data.get("photo_ids", []))
        if not direct and not from_report:
            raise HTTPException(422, "Zdjęcie musi być przypisane do tego zadania albo jego zgłoszenia.")
        if not (Path(os.getenv("STORAGE_PATH", ".data/storage")) / f"{photo.id}.jpg").is_file():
            raise HTTPException(422, "Plik zdjęcia jest niedostępny. Dodaj zdjęcie ponownie.")
    if "value" not in body:
        raise HTTPException(422, "Wpisz wynik obserwacji; zdjęcie nie zastępuje pomiaru.")
    start, end = validate_interval({"valid_from": body.get("observed_at"), "valid_until": body.get("valid_until")})
    if task.layer == "observed":
        settings = load_settings()
        maximum_skew = max(0, float(settings.get("observation_clock_skew_seconds", 60)))
        if instant(start) > datetime.now(timezone.utc)+timedelta(seconds=maximum_skew):
            raise HTTPException(422, "Obserwacja terenowa nie może pochodzić z przyszłości. Sprawdź datę i strefę czasową.")
        dynamic = task.data["feature"] in {"open", "entrance_open", "elevator_operational", "lit"}
        maximum_seconds = float(settings.get("dynamic_evidence_ttl_hours", 4))*3600 if dynamic else float(settings.get("geometry_evidence_ttl_days", 30))*86400
        if (instant(end)-instant(start)).total_seconds() > maximum_seconds:
            raise HTTPException(422, f"Okres ważności przekracza skonfigurowany limit tej cechy: {maximum_seconds/3600:g} godzin. Ustaw wcześniejszą ponowną kontrolę.")
    method = require_text(body, "method", 3, 2000)
    feature, value, unit = task.data["feature"], body["value"], body.get("unit", task.data.get("unit"))
    if feature in {"width_cm", "width_m", "slope_pct", "kerb_cm"} and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise HTTPException(422, "Ta cecha wymaga liczbowego pomiaru i jednostki.")
    expected_units = {"width_cm": "cm", "width_m": "m", "slope_pct": "%", "kerb_cm": "cm"}
    if feature in expected_units and (unit != expected_units[feature] or not math.isfinite(value) or (feature != "slope_pct" and value < 0)):
        raise HTTPException(422, f"Wymagana jednostka {expected_units[feature]} i poprawny skończony pomiar.")
    if feature in {"open", "steps", "lit", "entrance_open", "elevator_operational"} and not isinstance(value, bool):
        raise HTTPException(422, "Ta obserwacja wymaga wartości true albo false.")
    if feature == "surface" and (not isinstance(value, str) or not value.strip() or len(value) > 100):
        raise HTTPException(422, "Wskaż nazwę zaobserwowanej nawierzchni.")
    try:
        work_minutes = float(body.get("work_minutes", 0))
        if not math.isfinite(work_minutes) or work_minutes < 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise HTTPException(422, "Czas kontroli musi być skończoną nieujemną liczbą minut.")
    if feature == "width_cm":
        feature, value, unit = "width_m", value / 100, "m"
    if feature in {"entrance_open", "elevator_operational"}:
        feature = "open"
    evidence = add_entity(db, "evidence", task.layer, {"asset_id": task.data["asset_id"], "feature": feature, "value": value, "unit": unit, "method": method, "observed_at": start, "valid_from": start, "valid_until": end, "author": user.id, "task_id": task.id, "status": "pending_review", "notes": body.get("notes", ""), "photo_id": body.get("photo_id")})
    before = serial(task)
    mutate(db, task, body, {**task.data, "status": "observed", "evidence_id": evidence.id, "observed_at": start, "work_minutes": work_minutes})
    audit(db, user, "field_observation", evidence)
    audit(db, user, "task_observed", task, before)
    return finish_write(db, ctx, {"task": serial(task), "evidence": serial(evidence)})

@router.get("/evidence")
def evidence_list(request: Request, layer: str = "fixture", include_pending: bool = False, db=Depends(get_db, scope="function")):
    read_layer(db, request, layer)
    if include_pending:
        current_user(db, request, True, STAFF | {"verifier"})
        return [serial(x) for x in items(db, "evidence", layer)]
    return [public_payload(serial(x)) for x in items(db, "evidence", layer) if x.data.get("status") in {"confirmed", "conflicted", "expired", "superseded"}]

@router.get("/evidence/{evidence_id}/history")
def evidence_history(evidence_id: str, request: Request, db=Depends(get_db, scope="function")):
    current_user(db, request, True, STAFF | {"verifier"})
    evidence = get_entity(db, evidence_id, "evidence")
    return [serial(x) for x in items(db, "evidence", evidence.layer) if x.data.get("asset_id") == evidence.data.get("asset_id") and x.data.get("feature") == evidence.data.get("feature")]

@router.post("/evidence/{evidence_id}/publish")
def publish_evidence(evidence_id: str, body: schemas.EvidencePublish, request: Request, db=Depends(get_db, scope="function"), authorized=Depends(require_operator)) -> schemas.RecordReply:
    user = current_user(db, request, True, STAFF)
    ctx = begin_write(db, request, body, user)
    if ctx[2]:
        return ctx[2]
    evidence = get_entity(db, evidence_id, "evidence")
    allowed_layer(user, evidence.layer)
    ensure_asset(db, evidence.layer, evidence.data.get("asset_id"))
    reason = require_text(body, "reason", 3, 4000)
    before = serial(evidence)
    if evidence.data["status"] not in {"pending_review", "conflicted"}:
        raise HTTPException(409, "Ten dowód został już rozpatrzony.")
    supersede = set(body.get("supersedes", []))
    conflicts = []
    for previous in items(db, "evidence", evidence.layer):
        if previous.id == evidence.id or previous.data.get("asset_id") != evidence.data["asset_id"] or previous.data.get("feature") != evidence.data["feature"] or previous.data.get("status") not in {"confirmed", "conflicted"}:
            continue
        overlaps = instant(previous.data["valid_from"]) < instant(evidence.data["valid_until"]) and instant(evidence.data["valid_from"]) < instant(previous.data["valid_until"])
        if previous.id in supersede:
            mutate(db, previous, {"expected_version": previous.version}, {**previous.data, "status": "superseded", "superseded_by": evidence.id, "review_reason": reason})
            audit(db, user, "evidence_superseded", previous)
        elif overlaps and previous.data["value"] != evidence.data["value"]:
            conflicts.append(previous.id)
            mutate(db, previous, {"expected_version": previous.version}, {**previous.data, "status": "conflicted"})
            audit(db, user, "evidence_conflict", previous)
    status = "conflicted" if conflicts else "confirmed"
    mutate(db, evidence, body, {**evidence.data, "status": status, "reviewer": user.id, "review_reason": reason, "conflicts": conflicts, "published_at": utcnow()})
    if evidence.data.get("task_id"):
        task = get_entity(db, evidence.data["task_id"], "task")
        mutate(db, task, {"expected_version": task.version}, {**task.data, "status": "completed" if status == "confirmed" else "needs_recheck"})
    version = publish_change(db, evidence.layer, "evidence_published")
    audit(db, user, "evidence_published", evidence, before)
    return finish_write(db, ctx, {**serial(evidence), "data_version": version})

async def read_photo_upload(file):
    settings = load_settings()
    upload_limit = int(os.getenv("SMART_CITY_UPLOAD_MAX_BYTES", settings.get("upload_max_bytes", 5_000_000)))
    raw = await file.read(upload_limit + 1)
    if len(raw) > upload_limit:
        raise HTTPException(413, f"Zdjęcie przekracza limit {upload_limit} bajtów.")
    return raw


def save_private_photo(db, layer, raw, relation):
    """Shared size, pixel and metadata policy for report and field-task images."""
    try:
        picture = Image.open(io.BytesIO(raw))
        if picture.format not in {"JPEG", "PNG", "WEBP"} or picture.width*picture.height > 24_000_000:
            raise ValueError()
        picture.load()
        picture = picture.convert("RGB")
        picture.thumbnail((2000, 2000))
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
        raise HTTPException(422, "Nieprawidłowy lub zbyt duży obraz.")
    identifier = uid("photo")
    storage = Path(os.getenv("STORAGE_PATH", ".data/storage"))
    storage.mkdir(parents=True, exist_ok=True)
    picture.save(storage / f"{identifier}.jpg", "JPEG", quality=85, exif=b"")
    return add_entity(db, "photo", layer, {**relation, "status": "private", "width": picture.width, "height": picture.height, "metadata_removed": True}, identifier)


@router.post("/reports/{report_id}/photos", status_code=201)
async def upload_photo(report_id: str, request: Request, file: UploadFile = File(...), token: str | None = None, db=Depends(get_db, scope="function")) -> schemas.RecordReply:
    report = get_entity(db, report_id, "report")
    user = current_user(db, request)
    token = request.headers.get("x-report-token", token)
    if not user and (not token or not secrets.compare_digest(digest(token), report.data["token_hash"])):
        raise HTTPException(404, "Nie znaleziono sprawy.")
    raw = await read_photo_upload(file)
    ctx = begin_write(db, request, {"report_id": report_id, "sha256": hashlib.sha256(raw).hexdigest()}, user)
    if ctx[2]:
        return ctx[2]
    photo = save_private_photo(db, report.layer, raw, {"report_id": report.id})
    identifier = photo.id
    mutate(db, report, {"expected_version": report.version}, {**report.data, "photo_ids": report.data.get("photo_ids", [])+[identifier]})
    return finish_write(db, ctx, serial(photo))


@router.post("/tasks/{task_id}/photos", status_code=201)
async def upload_task_photo(task_id: str, request: Request, file: UploadFile = File(...), db=Depends(get_db, scope="function")) -> schemas.RecordReply:
    user = current_user(db, request, True, STAFF | {"verifier"})
    task = get_entity(db, task_id, "task")
    allowed_layer(user, task.layer)
    raw = await read_photo_upload(file)
    ctx = begin_write(db, request, {"task_id": task.id, "sha256": hashlib.sha256(raw).hexdigest()}, user)
    if ctx[2]:
        return ctx[2]
    if task.data.get("status") not in {"assigned", "needs_recheck"}:
        raise HTTPException(409, "Zadanie ma już obserwację. Zdjęcie dodaj do nowej kontroli.")
    photo = save_private_photo(db, task.layer, raw, {"task_id": task.id, "uploaded_by": user.id})
    audit(db, user, "task_photo_uploaded", photo)
    return finish_write(db, ctx, serial(photo))


@router.get("/photos/{photo_id}")
def read_photo(photo_id: str, request: Request, db=Depends(get_db, scope="function")):
    current_user(db, request, True, STAFF | {"verifier"})
    get_entity(db, photo_id, "photo")
    return FileResponse(Path(os.getenv("STORAGE_PATH", ".data/storage")) / f"{photo_id}.jpg", media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})
