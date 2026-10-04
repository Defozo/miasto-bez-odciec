"""Deterministic synthetic data, never an observation of Krakow infrastructure."""
from __future__ import annotations
from copy import deepcopy
from .models import iso

DAY = "2026-10-03"


def at(clock: str) -> str:
    return iso(f"{DAY}T{clock}:00+02:00")


def build_fixture() -> dict:
    nodes = [
        {"id": "origin-west", "name": "Punkt A · Karmelicka", "lon": 19.9273, "lat": 50.0695, "level": 0},
        {"id": "origin-east", "name": "Punkt B · Łobzowska", "lon": 19.9312, "lat": 50.0710, "level": 0},
        {"id": "north", "name": "Dojście północne", "lon": 19.9298, "lat": 50.0722, "level": 0},
        {"id": "south", "name": "Dojście południowe", "lon": 19.9290, "lat": 50.0690, "level": 0},
        {"id": "clinic-door", "name": "Wejście do przychodni", "lon": 19.9335, "lat": 50.0701, "level": 0},
    ]
    assets = [
        {"id": "crossing-x", "name": "Przejście północne X", "kind": "crossing", "failure_group_id": "north-corridor"},
        {"id": "crossing-y", "name": "Przejście południowe Y", "kind": "crossing", "failure_group_id": "south-corridor"},
        {"id": "west-north", "name": "Chodnik A północ", "kind": "footway"},
        {"id": "west-south", "name": "Chodnik A południe", "kind": "footway"},
        {"id": "east-north", "name": "Chodnik B północ", "kind": "footway"},
        {"id": "east-south", "name": "Chodnik B południe", "kind": "footway"},
        {"id": "clinic-entrance", "name": "Drzwi przychodni", "kind": "entrance"},
    ]
    index = {n["id"]: n for n in nodes}
    edges = []
    for eid, u, v, aid, length, seconds in [
        ("west-north", "origin-west", "north", "west-north", 280, 300),
        ("west-south", "origin-west", "south", "west-south", 220, 260),
        ("east-north", "origin-east", "north", "east-north", 190, 230),
        ("east-south", "origin-east", "south", "east-south", 280, 330),
        ("north-clinic", "north", "clinic-door", "crossing-x", 310, 350),
        ("south-clinic", "south", "clinic-door", "crossing-y", 370, 420),
    ]:
        for reverse in (False, True):
            start, end = (v, u) if reverse else (u, v)
            edges.append({"id": eid + ("-reverse" if reverse else ""), "u": start, "v": end,
                          "asset_id": aid, "length_m": length, "duration_s": seconds,
                          "preference_cost": length, "slope_direction": -1 if reverse else 1,
                          "level": 0, "side": "synthetic", "name": next(a["name"] for a in assets if a["id"] == aid),
                          "geometry": [[index[start]["lon"], index[start]["lat"]], [index[end]["lon"], index[end]["lat"]]]})
    evidence = []
    features = {"open": True, "steps": False, "width_m": 1.8, "kerb_cm": 0.0, "slope_pct": 2.0, "surface": "asphalt"}
    for asset in assets:
        for feature, value in features.items():
            evidence.append({"id": f"e-{asset['id']}-{feature}", "asset_id": asset["id"], "feature": feature,
                             "value": value, "unit": {"width_m": "m", "kerb_cm": "cm", "slope_pct": "%"}.get(feature),
                             "valid_from": at("00:00"), "valid_until": at("23:59"), "observed_at": at("07:00"),
                             "author": "Generator danych syntetycznych", "method": "fixture", "source_id": "fixture-source",
                             "status": "confirmed", "layer": "fixture", "revision": 1})
    profiles = [
        {"id": "wheelchair", "name": "Bez schodów · wózek", "allow_steps": False, "min_width_m": 0.9,
         "max_kerb_cm": 2, "max_uphill_pct": 6, "max_downhill_pct": 8, "allowed_surfaces": ["asphalt", "paving", "concrete"],
         "max_distance_m": 1600, "max_duration_s": 1800, "settings_notice": "Edytowalne założenia demonstracyjne, nie uniwersalna norma."},
        {"id": "stroller", "name": "Z wózkiem dziecięcym", "allow_steps": False, "min_width_m": 0.8,
         "max_kerb_cm": 4, "max_uphill_pct": 10, "max_downhill_pct": 10, "allowed_surfaces": ["asphalt", "paving", "concrete", "compacted"],
         "max_distance_m": 2000, "max_duration_s": 1800},
        {"id": "walking", "name": "Pieszo", "allow_steps": True, "min_width_m": 0.6,
         "max_kerb_cm": 20, "max_uphill_pct": 20, "max_downhill_pct": 20, "allowed_surfaces": ["asphalt", "paving", "concrete", "compacted", "gravel"],
         "max_distance_m": 2500, "max_duration_s": 1800},
    ]
    works = [
        {"id": "X", "name": "Prace na dojściu północnym", "asset_id": "crossing-x", "start": at("08:00"), "end": at("14:00"),
         "duration_s": 21600, "kind": "closure", "status": "confirmed", "layer": "fixture", "invalidated_features": ["open"], "resource": "crew-x", "cost": None},
        {"id": "Y", "name": "Prace na dojściu południowym", "asset_id": "crossing-y", "start": at("10:00"), "end": at("16:00"),
         "duration_s": 21600, "kind": "closure", "status": "confirmed", "layer": "fixture", "invalidated_features": ["open"], "resource": "crew-y", "cost": None},
    ]
    return {"version": "fixture-v1", "evidence_version": 1, "layer": "fixture", "name": "Miasto bez odcięć · dane syntetyczne",
            "clock": at("09:00"), "timezone": "Europe/Warsaw", "valid_from": at("00:00"), "valid_until": at("23:59"),
            "coverage": {"bbox": [19.925, 50.067, 19.936, 50.074], "audited": False, "status": "synthetic", "buffer_m": 2500},
            "nodes": nodes, "edges": edges, "assets": assets, "evidence": evidence, "profiles": profiles,
            "places": [{"id": "clinic", "name": "Przychodnia · cel demonstracyjny", "category": "healthcare", "entrance_ids": ["clinic-main"], "lon": 19.9335, "lat": 50.0701}],
            "entrances": [{"id": "clinic-main", "node_id": "clinic-door", "asset_id": "clinic-entrance", "place_id": "clinic", "name": "Wejście główne", "level": 0}],
            "origins": [dict(n) for n in nodes[:2]], "works": works, "restrictions": deepcopy(works),
            "horizon": {"start": at("08:00"), "end": at("20:30")},
            "bindings": [{"asset_id": a["id"], "graph_version": "fixture-v1", "edge_ids": [e["id"] for e in edges if e["asset_id"] == a["id"]]} for a in assets],
            "sources": [{"id": "fixture-source", "publisher": "Miasto bez odcięć", "kind": "synthetic", "license": "CC0-1.0", "observed_at": None}],
            "notice": "Dane testowe. Lokalizacja ilustruje proponowany obszar audytu, nie stan Krakowa."}


def elevator_fixture() -> dict:
    graph = build_fixture()
    graph["restrictions"] = []
    graph["works"] = []
    for asset in graph["assets"]:
        if asset["id"] in {"crossing-x", "crossing-y"}:
            asset["failure_group_id"] = "shared-elevator"
            asset["kind"] = "elevator"
    return graph
