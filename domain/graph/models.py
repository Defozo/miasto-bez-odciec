"""JSON contracts shared by persistence, workers and importers.

All times are timezone-aware. Core algorithms have no I/O and never mutate input.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Any, TypedDict, NotRequired


class MobilityProfile(TypedDict):
    id: str
    name: str
    allow_steps: bool
    min_width_m: float
    max_kerb_cm: float
    max_uphill_pct: float
    max_downhill_pct: float
    allowed_surfaces: list[str]
    max_distance_m: float
    max_duration_s: float


class Edge(TypedDict):
    id: str
    u: str
    v: str
    asset_id: str
    length_m: float
    duration_s: float
    geometry: NotRequired[list[list[float]]]
    preference_cost: NotRequired[float]


class Evidence(TypedDict):
    id: str
    asset_id: str
    feature: str
    value: Any
    valid_from: str
    valid_until: str
    layer: str
    status: str


def instant(value: str | datetime | float | int) -> float:
    if isinstance(value, (float, int)):
        return float(value)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Czas musi zawierać strefę czasową.")
    return value.timestamp()


def iso(value: float | datetime | str) -> str:
    return datetime.fromtimestamp(instant(value), timezone.utc).isoformat().replace("+00:00", "Z")


def content_hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def records(graph: dict, key: str) -> list[dict]:
    value = graph.get(key, [])
    return list(value.values()) if isinstance(value, dict) else value


def profile_for(graph: dict, profile: str | dict | None) -> dict:
    profiles = records(graph, "profiles")
    if isinstance(profile, str):
        found = next((p for p in profiles if p["id"] == profile), None)
        if found is None:
            raise ValueError(f"Nieznany profil: {profile}")
        profile = dict(found)
    if profile is None:
        if not profiles:
            raise ValueError("Wymagany jest profil dojścia.")
        profile = dict(profiles[0])
    base = next((p for p in profiles if p["id"] == profile.get("id")), {})
    result = {**base, **profile}
    for name in ("max_distance_m", "max_duration_s"):
        value = result.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value) or value <= 0:
            raise ValueError("Limity dystansu i czasu muszą być skończonymi liczbami dodatnimi.")
    for name in ("min_width_m", "max_kerb_cm", "max_uphill_pct", "max_downhill_pct"):
        value = result.get(name)
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value) or value < 0):
            raise ValueError(f"Wymaganie {name} musi być skończoną liczbą nieujemną.")
    if "allow_steps" in result and not isinstance(result["allow_steps"], bool):
        raise ValueError("Zgoda na schody wymaga wartości logicznej.")
    if "allowed_surfaces" in result and (not isinstance(result["allowed_surfaces"], list) or any(not isinstance(s, str) for s in result["allowed_surfaces"])):
        raise ValueError("Dozwolone nawierzchnie muszą być listą nazw.")
    return result
