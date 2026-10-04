from __future__ import annotations
from . import schemas
from .security import require_operator, require_verifier, require_admin
import asyncio
import copy
import json
import os
import secrets
import time
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from services.settings import analysis_time_limit
from .db import AuditEvent, Entity, Job, OutboxEvent, Session, State, User, engine, get_db
from .security import COOKIE, current_user, digest, establish_session, hasher, local_demo_enabled, read_layer, verify_password
from .store import graph_snapshot, items, public_payload, serial, state

@asynccontextmanager
async def lifespan(app):
    if os.getenv("SMART_CITY_AUTO_INIT", "true").lower() == "true":
        from .init_db import initialize
        initialize(seed=os.getenv("SMART_CITY_SEED_FIXTURE", "true").lower() == "true")
    Path(os.getenv("STORAGE_PATH", ".data/storage")).mkdir(parents=True, exist_ok=True)
    yield

app = FastAPI(title="Miasto bez odcięć", version="1.0.0", lifespan=lifespan, description="Jawny demonstrator ciągłości dojść. Warstwa fixture nie opisuje sytuacji w terenie.")

@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response

@app.exception_handler(IntegrityError)
async def conflict_handler(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409, content={"detail": "Konflikt równoległych zmian. Ponów żądanie z tym samym kluczem."})

class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)

class RouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layer: schemas.Layer = "fixture"
    origin: str
    destination: str | schemas.Destination
    profile: str | schemas.MobilityProfile = "wheelchair"
    departure: schemas.Timestamp

login_attempts = {}

@app.get("/health/live")
def live():
    return {"status": "alive"}

@app.get("/health/ready")
def ready(db=Depends(get_db, scope="function")):
    db.execute(text("SELECT 1"))
    active = state(db)
    storage = Path(os.getenv("STORAGE_PATH", ".data/storage"))
    schema = db.get(State, "schema")
    ok = bool(schema and active["graph_id"] and storage.exists() and os.access(storage, os.W_OK))
    heartbeat = db.get(State, "worker_heartbeat")
    worker_status = {**heartbeat.value, "status": heartbeat.value.get("status", "active") if time.time()-heartbeat.value.get("timestamp", 0) < 120 else "stale"} if heartbeat else {"status": "not_seen"}
    info = {"status": "ready" if ok else "not_ready", "database": True, "schema": schema.value if schema else None, "storage": storage.exists(), "graph": active["graph_id"], "worker": worker_status, "adapters": {"ai_enabled": os.getenv("SMART_CITY_ENABLE_GROQ", "false") == "true", "firecrawl_enabled": os.getenv("SMART_CITY_ENABLE_FIRECRAWL", "false") == "true"}}
    if not ok:
        raise HTTPException(503, info)
    return info

@app.post("/api/v1/auth/login")
def login(body: Login, request: Request, response: Response, db=Depends(get_db, scope="function")):
    remote = request.client.host if request.client else "unknown"
    attempts = [t for t in login_attempts.get(remote, []) if t > time.time()-60]
    if len(attempts) >= 10:
        raise HTTPException(429, "Zbyt wiele prób. Spróbuj za minutę.")
    login_attempts[remote] = attempts+[time.time()]
    user = db.scalar(select(User).where(User.username == body.username, User.active == True))
    if not user or not verify_password(user.password_hash, body.password):
        raise HTTPException(401, "Nieprawidłowe dane logowania.")
    return establish_session(db, user, response)

@app.post("/api/v1/auth/demo")
def demo_login(body: schemas.DemoLogin, request: Request, response: Response, db=Depends(get_db, scope="function")):
    if not local_demo_enabled(request):
        raise HTTPException(403, "Lokalny tryb demonstracyjny jest wyłączony.")
    role = body.get("role", "operator")
    if role not in {"operator", "verifier", "admin"}:
        raise HTTPException(422, "Nieznana rola.")
    user = db.get(User, f"demo-{role}")
    if not user:
        user = User(id=f"demo-{role}", username=f"demo-{role}", role=role, password_hash=hasher.hash(secrets.token_urlsafe(48)))
        db.add(user)
        db.flush()
    return establish_session(db, user, response)

@app.get("/api/v1/auth/session")
def session(request: Request, db=Depends(get_db, scope="function")):
    user = current_user(db, request)
    if not user:
        return {"user": None, "csrf_token": None}
    found = db.get(Session, digest(request.cookies[COOKIE]))
    return {"user": {"username": user.username, "role": user.role}, "csrf_token": found.csrf_token}

@app.post("/api/v1/auth/logout")
def logout(request: Request, response: Response, db=Depends(get_db, scope="function")):
    current_user(db, request, required=True)
    db.delete(db.get(Session, digest(request.cookies[COOKIE])))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}

@app.get("/api/v1/bootstrap")
def bootstrap(request: Request, layer: str = "fixture", db=Depends(get_db, scope="function")):
    user = read_layer(db, request, layer)
    graph = graph_snapshot(db, layer)
    staff = bool(user and user.role in {"operator", "admin"})
    return {"layer": layer, **state(db, layer), "graph_version": graph["version"], "graph": graph if staff else public_payload(graph), "user": {"username": user.username, "role": user.role} if user else None, "local_demo_auth": local_demo_enabled(request), "pilot_status": "unverified", "reports": [safe_report(x) for x in items(db, "report", layer)] if staff else [], "tasks": [serial(x) for x in items(db, "task", layer)] if user else [], "staff_evidence": [serial(x) for x in items(db, "evidence", layer)] if user else [], "scenarios": [serial(x) for x in items(db, "scenario", layer)] if staff else [], "sources": [public_source(x) for x in items(db, "source", layer)], "restrictions": public_payload(graph.get("restrictions", [])), "decisions": [serial(x) for x in items(db, "decision", layer)] if staff else []}

def safe_report(entity):
    return {k: v for k, v in serial(entity).items() if k not in {"token_hash", "contact"}}

def public_source(entity):
    return {k: v for k, v in serial(entity).items() if k not in {"raw_text", "storage_path"}}

@app.get("/api/v1/coverage")
def coverage(request: Request, layer: str = "fixture", db=Depends(get_db, scope="function")):
    read_layer(db, request, layer)
    graph = graph_snapshot(db, layer)
    return {"layer": layer, "graph_version": graph["version"], "data_version": graph["data_version"], "coverage": graph.get("coverage", {}), "origins": graph.get("origins", []), "places": graph.get("places", []), "assumptions": graph.get("assumptions", []), "pilot_status": "unverified"}

@app.get("/api/v1/places")
def places(request: Request, q: str = "", layer: str = "fixture", db=Depends(get_db, scope="function")):
    read_layer(db, request, layer)
    return [p for p in graph_snapshot(db, layer).get("places", []) if q.lower() in p.get("name", "").lower()]

@app.get("/api/v1/profiles")
def profiles(request: Request, layer: str = "fixture", db=Depends(get_db, scope="function")):
    read_layer(db, request, layer)
    return graph_snapshot(db, layer).get("profiles", [])

@app.post("/api/v1/routes")
def routes(body: RouteRequest, db=Depends(get_db, scope="function")) -> schemas.RouteReply:
    from domain.graph import route
    if body.layer not in {"fixture", "observed"}:
        raise HTTPException(403, "Publiczna trasa wymaga warstwy fixture lub observed.")
    from .store import instant
    instant(body.departure, "departure")
    graph = graph_snapshot(db, body.layer)
    try:
        result = route(graph, body.model_dump(), deadline=time.monotonic()+float(os.getenv("SMART_CITY_ROUTE_TIMEOUT_S", "2")))
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc))
    return public_payload({**result, "layer": body.layer, "data_version": graph["data_version"], "graph_version": graph["version"], "conservative_window": True})

@app.get("/api/v1/demo/evaluation")
def demo_evaluation(db=Depends(get_db, scope="function")) -> schemas.AnalysisReply:
    from domain.graph import evaluate
    return public_payload(evaluate(graph_snapshot(db), {"time_limit_s": analysis_time_limit(maximum=10)}))

def public_analysis_request(body):
    if body.get("layer", "fixture") not in {"fixture", "observed"}:
        raise HTTPException(403, "Publiczne analizy wymagają fixture lub observed.")
    limits = {"origins": 100, "destinations": 20, "profiles": 3, "variants": 12, "restrictions": 100}
    if any(key in body and not isinstance(body[key], list) for key in limits):
        raise HTTPException(422, "Początki, cele, profile, warianty i ograniczenia wymagają list.")
    if len(json.dumps(body)) > 100_000 or any(len(body.get(key, [])) > limit for key, limit in limits.items()):
        raise HTTPException(413, "Zbyt duża analiza interaktywna. Zapisz scenariusz.")
    try:
        return {**{k: v for k, v in body.items() if not k.startswith("_")}, "time_limit_s": analysis_time_limit(body, maximum=10), "max_labels": min(100000, max(100, int(body.get("max_labels", 100000))))}
    except (ValueError, TypeError):
        raise HTTPException(422, "Limit czasu i liczby etykiet musi być liczbą.")

@app.post("/api/v1/analysis/evaluate")
def analysis(body: schemas.AnalysisRequest, db=Depends(get_db, scope="function")) -> schemas.AnalysisReply:
    from domain.graph import evaluate
    body = public_analysis_request(body)
    try:
        return public_payload(evaluate(graph_snapshot(db, body.get("layer", "fixture")), body))
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc))

@app.post("/api/v1/analysis/failures")
def failures(body: schemas.AnalysisRequest, db=Depends(get_db, scope="function")):
    from domain.graph import failure_analysis
    body = public_analysis_request(body)
    graph = graph_snapshot(db, body.get("layer", "fixture"))
    return public_payload({**failure_analysis(graph, body), "layer": "scenario", "simulated": True, "graph_version": graph["version"]})

@app.post("/api/v1/analysis/verification-impact")
def verification(body: schemas.AnalysisRequest, db=Depends(get_db, scope="function")):
    from domain.graph import verification_impact
    body = public_analysis_request(body)
    graph = graph_snapshot(db, body.get("layer", "fixture"))
    return public_payload(verification_impact(graph, body))

@app.get("/api/v1/diagnostics")
def diagnostics(request: Request, db=Depends(get_db, scope="function")):
    current_user(db, request, True, {"operator", "admin", "verifier"})
    heartbeat = db.get(State, "worker_heartbeat")
    jobs = list(db.scalars(select(Job).order_by(Job.created_at.desc()).limit(100)))
    worker_status = {**heartbeat.value, "status": "active" if time.time()-heartbeat.value.get("timestamp", 0) < 120 else "stale"} if heartbeat else None
    from .store import instant
    from .db import utcnow
    maintenance = {}
    import_dates = []
    for layer in ("fixture", "observed"):
        tasks = items(db, "task", layer)
        import_dates.extend(record.created_at for record in items(db, "import", layer))
        graph_clock = graph_snapshot(db, layer).get("clock", utcnow()) if layer == "fixture" and state(db, layer)["graph_id"] else utcnow()
        overdue = 0
        for task in tasks:
            try:
                overdue += bool(task.data.get("status") != "completed" and task.data.get("due_at") and instant(task.data["due_at"]) < instant(graph_clock))
            except HTTPException:
                pass
        maintenance[layer] = {"expired_evidence": sum(x.data.get("status") == "expired" for x in items(db, "evidence", layer)), "open_tasks": sum(x.data.get("status") != "completed" for x in tasks), "overdue_tasks": overdue, "recorded_field_minutes": sum(float(task.data.get("work_minutes", 0)) for task in tasks)}
    return {"worker": worker_status, "jobs": [{"id": j.id, "kind": j.kind, "status": j.status, "progress": j.progress, "attempts": j.attempts, "error": j.error} for j in jobs], "layers": {layer: state(db, layer) for layer in ("fixture", "observed", "planned")}, "pilot_status": "unverified", "maintenance": maintenance, "overdue_tasks": sum(row["overdue_tasks"] for row in maintenance.values()), "last_import_at": max(import_dates, default=None), "graph_refresh": {layer: tracked.value for layer in ("fixture", "observed") if (tracked := db.get(State, f"graph_refresh:{layer}"))}}

@app.get("/api/v1/audit")
def audit_log(request: Request, layer: str = "fixture", db=Depends(get_db, scope="function")):
    current_user(db, request, True, {"operator", "admin"})
    events = db.scalars(select(AuditEvent).where(AuditEvent.layer == layer).order_by(AuditEvent.id.desc()).limit(500))
    return [{"id": e.id, "actor": e.actor, "action": e.action, "entity_id": e.entity_id, "layer": e.layer, "created_at": e.created_at, "before": {k:v for k,v in (e.before or {}).items() if k not in {"token_hash", "contact"}}, "after": {k:v for k,v in e.after.items() if k not in {"token_hash", "contact"}}} for e in events]

@app.get("/api/v1/versions")
def versions(request: Request, layer: str = "fixture", db=Depends(get_db, scope="function")):
    read_layer(db, request, layer)
    return {"layer": layer, **state(db, layer)}

@app.get("/api/v1/events")
async def events(request: Request, layer: schemas.Layer = "fixture", after: int = 0, once: bool = False):
    """Resume publications and staff job progress; once returns one diagnostic batch."""
    from .events import event_response
    return event_response(request, layer, after, once)

from .reports import router as reports_router
from .planning import router as planning_router
from .data import router as data_router
app.include_router(reports_router, prefix="/api/v1")
app.include_router(planning_router, prefix="/api/v1")
app.include_router(data_router, prefix="/api/v1")

# One origin in local and container deployments, so sessions never require CORS.
web_dist = Path(os.getenv("SMART_CITY_WEB_DIST", "apps/web/dist"))
if web_dist.is_dir():
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    if (web_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="web-assets")
    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str):
        if path.startswith(("api/", "health/")):
            raise HTTPException(404, "Nieznany endpoint.")
        candidate = (web_dist / path).resolve()
        if candidate.is_relative_to(web_dist.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(web_dist / "index.html")
