from __future__ import annotations
import hashlib
import os
import secrets
import time
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from .db import Session, User, get_db

hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
COOKIE = "smart_city_session"

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def local_demo_enabled(request: Request):
    return os.getenv("SMART_CITY_LOCAL_DEMO_AUTH", "false").lower() == "true" and os.getenv("SMART_CITY_PUBLIC_MODE", "false").lower() != "true" and request.client and request.client.host in {"127.0.0.1", "::1", "localhost", "testclient"}

def current_user(db, request, required=False, roles=None):
    token = request.cookies.get(COOKIE)
    session = db.get(Session, digest(token)) if token else None
    user = db.get(User, session.user_id) if session and session.expires_at > time.time() else None
    if user and not user.active:
        user = None
    if required and not user:
        raise HTTPException(401, "Zaloguj się, aby wykonać tę czynność.")
    if user and roles and user.role not in roles:
        raise HTTPException(403, "Ta rola nie może wykonać tej czynności.")
    if user and request.method not in {"GET", "HEAD", "OPTIONS"}:
        token = request.headers.get("x-csrf-token", "")
        if not token or not secrets.compare_digest(session.csrf_hash, digest(token)):
            raise HTTPException(403, "Brak poprawnego tokenu ochrony sesji.")
        origin = request.headers.get("origin")
        allowed = os.getenv("SMART_CITY_ORIGIN")
        if origin and allowed and origin.rstrip("/") != allowed.rstrip("/"):
            raise HTTPException(403, "Nieprawidłowe pochodzenie żądania.")
    return user


def read_layer(db, request, layer):
    """Resident endpoints expose only published resident namespaces."""
    if layer not in {"fixture", "observed", "planned", "scenario"}:
        raise HTTPException(422, "Nieznana warstwa danych.")
    if layer not in {"fixture", "observed"}:
        return current_user(db, request, True, {"operator", "admin", "verifier"})
    return current_user(db, request)


def require_operator(request: Request, db=Depends(get_db, scope="function")):
    return current_user(db, request, True, {"operator", "admin"})


def require_verifier(request: Request, db=Depends(get_db, scope="function")):
    return current_user(db, request, True, {"operator", "admin", "verifier"})


def require_admin(request: Request, db=Depends(get_db, scope="function")):
    return current_user(db, request, True, {"admin"})

def establish_session(db, user, response: Response):
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    db.add(Session(token_hash=digest(token), user_id=user.id, csrf_hash=digest(csrf), csrf_token=csrf, expires_at=time.time()+8*3600))
    response.set_cookie(COOKIE, token, httponly=True, secure=os.getenv("SMART_CITY_PUBLIC_MODE", "false").lower() == "true", samesite="strict", max_age=8*3600, path="/")
    return {"user": {"username": user.username, "role": user.role}, "csrf_token": csrf}

def verify_password(encoded, password):
    try:
        return hasher.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
