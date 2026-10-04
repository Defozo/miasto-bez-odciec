"""Conservative temporal routing with non-dominated resource labels.

One label per vertex is insufficient: a shorter route can take longer. Labels
retain distance, physical duration and preference cost independently. No hard
barrier is represented as a cost penalty. Temporal validity covers the user's
entire maximum journey window, not merely estimated arrival at each edge.
"""
from __future__ import annotations
from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from math import inf
from time import monotonic
from typing import Any

from .models import instant, iso, records, profile_for, content_hash

ALGORITHM_VERSION = "temporal-pareto-1.1"
FEATURE_LABELS = {"open": "drożność", "steps": "schody", "width_m": "szerokość", "kerb_cm": "krawężnik", "slope_pct": "nachylenie", "surface": "nawierzchnia"}
INVALIDATABLE_FEATURES = frozenset({*FEATURE_LABELS, "lit", "entrance_open", "elevator_operational"})


def feature_requirements(profile: dict) -> dict:
    requirements = {"open": True}
    if not profile.get("allow_steps", False):
        requirements["steps"] = False
    for feature, setting in [("width_m", "min_width_m"), ("kerb_cm", "max_kerb_cm"), ("slope_pct", "max_uphill_pct"), ("surface", "allowed_surfaces")]:
        if profile.get(setting) is not None:
            requirements[feature] = profile[setting]
    if profile.get("max_downhill_pct") is not None:
        requirements["slope_pct"] = profile["max_downhill_pct"]
    return requirements


def satisfies(feature: str, value: Any, profile: dict, direction: int = 1) -> bool:
    if feature == "open":
        return value is True
    if feature == "steps":
        return value is False or bool(profile.get("allow_steps", False))
    if feature == "width_m":
        return isinstance(value, (float, int)) and not isinstance(value, bool) and value >= profile.get("min_width_m", 0)
    if feature == "kerb_cm":
        return isinstance(value, (float, int)) and not isinstance(value, bool) and value <= profile.get("max_kerb_cm", inf)
    if feature == "slope_pct":
        if not isinstance(value, (float, int)) or isinstance(value, bool):
            return False
        slope = value * direction
        downhill, uphill = profile.get("max_downhill_pct"), profile.get("max_uphill_pct")
        return -(inf if downhill is None else downhill) <= slope <= (inf if uphill is None else uphill)
    if feature == "surface":
        return value in profile.get("allowed_surfaces", [value])
    return True


def overlaps(start: float, end: float, other_start: float, other_end: float) -> bool:
    if end == start:  # instantaneous diagnostic, separate from full-window routing
        return other_start <= start < other_end
    return start < other_end and other_start < end


def restriction_interval(item: dict, layer: str) -> tuple[float, float]:
    start = instant(item.get("start", item.get("valid_from", "1970-01-01T00:00:00Z")))
    end = instant(item.get("end", item.get("valid_until", "2100-01-01T00:00:00Z")))
    # An estimated completion time is not evidence that an observed closure opened.
    if (layer == "observed" or item.get("layer") == "observed") and item.get("kind") == "closure":
        end = instant(item["verified_open_at"]) if item.get("verified_open_at") else inf
        if layer == "scenario" and item.get("assume_open_at"):
            end = instant(item["assume_open_at"])
    # Expiring an unresolved warning is a recheck trigger, never evidence that
    # the suspected obstruction disappeared. Scenarios may explicitly assume an
    # end; published resident layers require a resolving observation/moderation.
    if item.get("kind") == "warning":
        end = instant(item["verified_open_at"]) if item.get("verified_open_at") else inf
    if item.get("verified_open_at"):
        end = instant(item["verified_open_at"])
    return start, end


def feature_state(graph: dict, asset_id: str, edge: dict | None, feature: str, profile: dict,
                  start: float, end: float, layer: str, observed_after: float | None = None) -> tuple[str, list[dict], list[dict]]:
    allowed_layers = {graph.get("layer", layer), "scenario"} if layer == "scenario" else {layer}
    matching = [e for e in records(graph, "evidence") if e.get("asset_id") == asset_id and e.get("feature") == feature
                and (not e.get("edge_id") or edge and e["edge_id"] == edge["id"])
                and e.get("layer", graph.get("layer", layer)) in allowed_layers
                and e.get("status") in {"confirmed", "conflicted", "assumed", "expired"}
                and (e.get("status") != "assumed" or layer == "scenario" and e.get("layer") == "scenario")
                and e.get("valid_from") and e.get("valid_until")
                and (observed_after is None or instant(e.get("observed_at") or e["valid_from"]) >= observed_after)]
    relevant = [e for e in matching if overlaps(start, end, instant(e["valid_from"]), instant(e["valid_until"]))]
    boundaries = sorted({start, end} | {t for e in relevant for t in [instant(e["valid_from"]), instant(e["valid_until"])] if start < t < end})
    probes = [start] if start == end else [(a + b) / 2 for a, b in zip(boundaries, boundaries[1:])]
    state = "confirmed"
    issues = []
    for probe in probes:
        active = [e for e in relevant if instant(e["valid_from"]) <= probe < instant(e["valid_until"])]
        # Scenario evidence replaces exactly this feature, never other attributes.
        assumptions = [e for e in active if e.get("layer") == "scenario" and e.get("status") == "assumed"]
        if assumptions:
            active = assumptions
        conflict = any(e.get("status") == "conflicted" for e in active) or len({content_hash(e.get("value")) for e in active}) > 1
        if not active or conflict:
            if state != "barrier":
                state = "unknown"
            code = "conflicting_evidence" if conflict else "missing_or_expired_evidence"
            issues.append({"code": code, "asset_id": asset_id, "feature": feature,
                           "required_observed_after": iso(observed_after) if observed_after is not None else None,
                           "message": f"{'Sprzeczne dowody' if conflict else 'Brak dowodu po zmianie organizacji' if observed_after is not None else 'Brak aktualnego dowodu'}: {FEATURE_LABELS.get(feature, feature)}."})
        elif not satisfies(feature, active[0].get("value"), profile,
                           1 if active[0].get("edge_id") else (edge or {}).get("slope_direction", 1)):
            state = "barrier"
            issues.append({"code": "requirement_failed", "asset_id": asset_id, "feature": feature, "value": active[0].get("value"), "message": f"Warunek profilu niespełniony: {FEATURE_LABELS.get(feature, feature)}."})
    return state, relevant, list({content_hash(i): i for i in issues}.values())


def object_state(graph: dict, asset_id: str, edge: dict | None, profile: dict, start: float, end: float,
                 restrictions: list[dict], layer: str) -> dict:
    state, evidence, reasons = "confirmed", [], []
    assets = {a["id"]: a for a in records(graph, "assets")}
    asset = assets.get(asset_id, {})
    def matches_asset(item):
        return (item.get("asset_id") == asset_id or asset_id in item.get("asset_ids", [])
                or bool(item.get("failure_group_id") and asset.get("failure_group_id") == item["failure_group_id"])
                or bool(edge and edge["id"] in item.get("edge_ids", [])))
    allowed_layers = {graph.get("layer", layer), "scenario", "planned"} if layer == "scenario" else {layer}
    # A confirmed organization change invalidates its declared features. Unknown
    # scope invalidates every accessibility feature. Opening alone cannot renew
    # an old width, slope or surface measurement after works changed the object.
    invalidated_after = {}
    for item in restrictions:
        if item.get("kind") not in {"closure", "organization_change"} or item.get("status") in {"submitted", "needs_review", "rejected", "cancelled", "unverified", "located_unverified", "no_pedestrian_impact"}:
            continue
        if item.get("layer", graph.get("layer", layer)) not in allowed_layers or not item.get("start") or instant(item["start"]) > start or not matches_asset(item):
            continue
        scope = item.get("invalidated_features")
        scope = set(scope) if isinstance(scope, list) and all(isinstance(feature, str) and feature in INVALIDATABLE_FEATURES for feature in scope) else set(INVALIDATABLE_FEATURES)
        scope = {"open" if feature in {"entrance_open", "elevator_operational"} else feature for feature in scope}
        observed = item.get("layer", graph.get("layer", layer)) == "observed"
        if observed:
            scope.add("open")
        else:
            # Fixture/schedule reopening is explicitly a simulation assumption;
            # it does not permit stale geometry after a declared physical change.
            scope.discard("open")
        changed_at = instant(item.get("verified_open_at") or item.get("assume_open_at") or (item.get("end") if not observed else None) or item["start"])
        for feature in scope:
            invalidated_after[feature] = max(changed_at, invalidated_after.get(feature, changed_at))
    for feature in feature_requirements(profile):
        feature_status, feature_evidence, feature_reasons = feature_state(graph, asset_id, edge, feature, profile, start, end, layer, invalidated_after.get(feature))
        evidence.extend(feature_evidence)
        reasons.extend(feature_reasons)
        if feature_status == "barrier" or state != "barrier" and feature_status == "unknown":
            state = feature_status
    for item in restrictions:
        if item.get("status") in {"submitted", "needs_review", "rejected", "resolved", "retired"}:
            continue
        if item.get("layer", graph.get("layer", layer)) not in allowed_layers:
            continue
        matches = matches_asset(item)
        if not matches or not overlaps(start, end, *restriction_interval(item, layer)):
            continue
        warning = item.get("kind") in {"warning", "unverified"} or item.get("status") in {"unverified", "located_unverified", "needs_recheck", "conflicted"}
        if not warning:
            state = "barrier"
        elif state != "barrier":
            state = "unknown"
        reasons.append({"code": "unverified_warning" if warning else "active_closure", "asset_id": asset_id, "restriction_id": item.get("id"),
                        "message": "Ostrzeżenie wymaga kontroli terenowej." if warning else "Zamknięcie nachodzi na okno podróży."})
    if graph.get("valid_from") and start < instant(graph["valid_from"]) or graph.get("valid_until") and end > instant(graph["valid_until"]):
        if state != "barrier":
            state = "unknown"
        reasons.append({"code": "time_outside_coverage", "asset_id": asset_id, "message": "Dane nie obejmują całego okna podróży."})
    return {"state": state, "evidence": evidence, "reasons": reasons}


@dataclass(frozen=True)
class Label:
    node: str
    distance: float
    duration: float
    cost: float
    path: tuple[str, ...]
    target: str | None = None


def dominates(a: Label, b: Label) -> bool:
    return a.distance <= b.distance and a.duration <= b.duration and a.cost <= b.cost


def search(edges: list[dict], source: str, targets: set[str], profile: dict, max_labels: int,
           bounded: bool = True, deadline: float | None = None) -> tuple[Label | None, bool, int]:
    adjacency: dict[str, list[dict]] = {}
    for edge in edges:
        adjacency.setdefault(edge["u"], []).append(edge)
    first = Label(source, 0, 0, 0, ())
    labels = {source: [first]}
    serial = count()
    queue = [(0.0, next(serial), first)]
    created = 1
    while queue:
        if deadline is not None and monotonic() >= deadline:
            return None, False, created
        _, _, current = heappop(queue)
        if current not in labels.get(current.node, []):
            continue
        if current.node in targets:
            return current, True, created
        for edge in adjacency.get(current.node, []):
            candidate = Label(edge["v"], current.distance + float(edge["length_m"]),
                              current.duration + float(edge["duration_s"]),
                              current.cost + float(edge.get("preference_cost", edge["length_m"])), current.path + (edge["id"],))
            if bounded and (candidate.distance > profile["max_distance_m"] or candidate.duration > profile["max_duration_s"]):
                continue
            previous = labels.setdefault(candidate.node, [])
            if any(dominates(old, candidate) for old in previous):
                continue
            if created >= max_labels:
                return None, False, created
            labels[candidate.node] = [old for old in previous if not dominates(candidate, old)] + [candidate]
            heappush(queue, (candidate.cost, next(serial), candidate))
            created += 1
    return None, True, created


def reverse_category_search(edges: list[dict], targets: set[str], profile: dict, max_labels: int,
                            bounded: bool = True, deadline: float | None = None) -> tuple[dict[str, Label], bool, int]:
    """One reverse multi-source Pareto traversal for every origin in a category.

    Edges keep their original directed costs and validated slope requirements.
    Only traversal order reverses. A label stores the selected entrance node and
    an original-direction path, so reconstruction never invents a reverse edge.
    """
    incoming = {}
    for edge in edges:
        incoming.setdefault(edge["v"], []).append(edge)
    labels, queue = {}, []
    serial = count()
    created = 0
    for target in sorted(targets):
        if created >= max_labels:
            return {}, False, created
        first = Label(target, 0, 0, 0, (), target)
        labels[target] = [first]
        heappush(queue, (0.0, next(serial), first))
        created += 1
    while queue:
        if deadline is not None and monotonic() >= deadline:
            return {}, False, created
        _, _, current = heappop(queue)
        if current not in labels.get(current.node, []):
            continue
        for edge in incoming.get(current.node, []):
            candidate = Label(edge["u"], current.distance+float(edge["length_m"]),
                              current.duration+float(edge["duration_s"]),
                              current.cost+float(edge.get("preference_cost", edge["length_m"])),
                              (edge["id"],)+current.path, current.target)
            if bounded and (candidate.distance > profile["max_distance_m"] or candidate.duration > profile["max_duration_s"]):
                continue
            previous = labels.setdefault(candidate.node, [])
            if any(dominates(old, candidate) for old in previous):
                continue
            if created >= max_labels:
                return {}, False, created
            labels[candidate.node] = [old for old in previous if not dominates(candidate, old)]+[candidate]
            heappush(queue, (candidate.cost, next(serial), candidate))
            created += 1
    best = {}
    for origin, alternatives in labels.items():
        if alternatives:
            chosen = min(alternatives, key=lambda label: (label.cost, label.distance, label.duration, label.target, label.path))
            best[origin] = Label(chosen.target, chosen.distance, chosen.duration, chosen.cost, chosen.path, chosen.target)
    return best, True, created


def destination_entrances(graph: dict, destination: str | dict) -> list[dict]:
    places = records(graph, "places")
    entrances = records(graph, "entrances")
    if isinstance(destination, dict) and "category" in destination:
        ids = {p["id"] for p in places if p.get("category") == destination["category"]}
        return [e for e in entrances if e.get("place_id") in ids]
    target = destination.get("id") if isinstance(destination, dict) else destination
    exact = [e for e in entrances if e["id"] == target or e.get("place_id") == target]
    return exact


def route(graph: dict, profile: str | dict | None = None, origin: str | None = None,
          destination: str | dict | None = None, departure: str | float | None = None,
          restrictions: list[dict] | None = None, layer: str = "fixture", max_labels: int = 100000,
          instantaneous: bool = False, deadline: float | None = None, state_cache: dict | None = None) -> dict:
    if isinstance(profile, dict) and "origin" in profile and origin is None:
        request = profile
        return route(graph, request.get("profile", request.get("profile_id")), request.get("origin", request.get("origin_id")),
                     request.get("destination", request.get("destination_id")), request.get("departure", graph.get("clock")),
                     request.get("restrictions", restrictions), request.get("layer", graph.get("layer", layer)),
                     request.get("max_labels", max_labels), request.get("instantaneous", instantaneous), deadline, state_cache)
    profile = profile_for(graph, profile)
    if origin is None or destination is None or departure is None:
        raise ValueError("Wymagane są początek, cel i czas wyjścia.")
    if layer != "scenario" and layer != graph.get("layer", layer):
        raise ValueError("Warstwa zapytania nie odpowiada warstwie grafu.")
    start = instant(departure)
    end = start if instantaneous else start + profile["max_duration_s"]
    restrictions = records(graph, "restrictions") if restrictions is None else restrictions
    base = {"status": "incomplete", "complete": True, "path": [], "coordinates": [], "distance_m": None, "duration_s": None,
            "preference_cost": None, "steps": [], "reasons": [], "unknowns": [], "evidence": [], "valid_until": None,
            "graph_version": graph.get("version"), "evidence_version": graph.get("evidence_version"), "profile": profile,
            "origin": origin, "destination": destination, "layer": layer, "window": {"start": iso(start), "end": iso(end)},
            "algorithm_version": ALGORITHM_VERSION, "instantaneous": instantaneous,
            "search_method": "reverse_multi_source_pareto" if isinstance(destination, dict) and "category" in destination else "forward_pareto",
            "notice": "Dane syntetyczne." if layer == "fixture" else "Warunkowa symulacja." if layer == "scenario" else "Potwierdzenie dotyczy danych, nie gwarancji w terenie.",
            "model_note": "Każdy odcinek i wejście musi spełniać wymagania przez całe maksymalne okno podróży. Wynik nie potwierdza godzin pracy ani dostępności usługi wewnątrz."}
    if deadline is not None and monotonic() >= deadline:
        return {**base, "complete": False, "reasons": [{"code": "calculation_timeout", "message": "Osiągnięto limit czasu obliczeń. Pozostałe relacje są nierozstrzygnięte."}]}
    nodes = {n["id"]: n for n in records(graph, "nodes")}
    entrances = destination_entrances(graph, destination)
    if origin not in nodes or not entrances:
        return {**base, "status": "outside_coverage", "reasons": [{"code": "outside_coverage", "message": "Początek lub właściwe wejście celu znajduje się poza pokryciem danych."}]}
    edges = records(graph, "edges")
    cache_key = (id(graph), id(restrictions), content_hash(profile), start, end, layer)
    cached = state_cache.get(cache_key) if state_cache is not None else None
    if cached is None:
        states, entry_states = {}, {}
        for edge in edges:
            if deadline is not None and monotonic() >= deadline:
                return {**base, "complete": False, "reasons": [{"code": "calculation_timeout", "message": "Nie zakończono sprawdzania dowodów w limicie obliczeń."}]}
            states[edge["id"]] = object_state(graph, edge["asset_id"], edge, profile, start, end, restrictions, layer)
        for entrance in records(graph, "entrances"):
            if deadline is not None and monotonic() >= deadline:
                return {**base, "complete": False, "reasons": [{"code": "calculation_timeout", "message": "Nie zakończono sprawdzania wejść w limicie obliczeń."}]}
            entry_states[entrance["id"]] = object_state(graph, entrance["asset_id"], None, profile, start, end, restrictions, layer)
        if state_cache is not None:
            state_cache[cache_key] = (states, entry_states)
    else:
        states, entry_states = cached
    calls = [("confirmed", {"confirmed"}, True), ("possible", {"confirmed", "unknown"}, True),
             ("limit", {"confirmed", "unknown"}, False), ("barrier", {"confirmed", "unknown", "barrier"}, False)]
    chosen, status, targets, work = None, "no_connection", set(), 0
    for candidate_status, allowed, bounded in calls:
        targets = {e["node_id"] for e in entrances if entry_states[e["id"]]["state"] in allowed and e["node_id"] in nodes}
        if not targets:
            continue
        usable = [e for e in edges if states[e["id"]]["state"] in allowed]
        if isinstance(destination, dict) and "category" in destination:
            reverse_key = ("category_search", cache_key, content_hash(destination), candidate_status, bounded, max_labels, tuple(sorted(targets)))
            cached_search = state_cache.get(reverse_key) if state_cache is not None else None
            if cached_search is None:
                results, complete, created = reverse_category_search(usable, targets, profile, max_labels, bounded, deadline)
                if state_cache is not None:
                    state_cache[reverse_key] = (results, complete)
            else:
                results, complete = cached_search
                created = 0
            found = results.get(origin)
        else:
            found, complete, created = search(usable, origin, targets, profile, max_labels, bounded, deadline)
        work += created
        if not complete:
            return {**base, "status": "incomplete", "complete": False, "labels_examined": work,
                    "reasons": [{"code": "calculation_limit", "message": "Osiągnięto limit obliczeń. Nie rozstrzygnięto istnienia dojścia."}]}
        if found is not None:
            chosen, status = found, candidate_status
            break
    base.update(status=status, labels_examined=work)
    if chosen is None:
        base["reasons"] = [{"code": "model_disconnected", "message": "Brak połączenia w modelu. Nie jest to dowód odcięcia w terenie."}]
        return base
    edge_index = {e["id"]: e for e in edges}
    path_edges = [edge_index[eid] for eid in chosen.path]
    matching_entries = [e for e in entrances if e["node_id"] == chosen.node]
    selected_entry = min(matching_entries, key=lambda e: {"confirmed": 0, "unknown": 1, "barrier": 2}[entry_states[e["id"]]["state"]])
    used_states = [states[eid] for eid in chosen.path] + [entry_states[selected_entry["id"]]]
    evidence = list({e["id"]: e for state in used_states for e in state["evidence"]}.values())
    reasons = list({content_hash(r): r for state in used_states for r in state["reasons"]}.values())
    unknowns = [r for r in reasons if r["code"] in {"missing_or_expired_evidence", "conflicting_evidence", "unverified_warning", "time_outside_coverage"}]
    if status == "limit":
        reasons.insert(0, {"code": "journey_limit", "message": "Istnieje połączenie, ale przekracza limit czasu lub dystansu.",
                           "max_distance_m": profile["max_distance_m"], "max_duration_s": profile["max_duration_s"]})
    coordinates = []
    for edge in path_edges:
        geometry = edge.get("geometry") or [[nodes[edge["u"]]["lon"], nodes[edge["u"]]["lat"]], [nodes[edge["v"]]["lon"], nodes[edge["v"]]["lat"]]]
        if isinstance(geometry, dict):
            geometry = geometry["coordinates"]
        coordinates.extend(geometry if not coordinates else geometry[1:])
    base.update(path=list(chosen.path) if status in {"confirmed", "possible"} else [],
                diagnostic_path=list(chosen.path) if status in {"barrier", "limit"} else [],
                coordinates=coordinates if status in {"confirmed", "possible"} else [], distance_m=chosen.distance, duration_s=chosen.duration,
                preference_cost=chosen.cost, entrance=selected_entry, reasons=reasons, unknowns=unknowns, evidence=evidence,
                valid_until=min((e["valid_until"] for e in evidence), key=instant, default=None),
                steps=[{"edge_id": e["id"], "name": e.get("name", "Przejście"), "distance_m": e["length_m"], "duration_s": e["duration_s"],
                        "state": states[e["id"]]["state"]} for e in path_edges] if status in {"confirmed", "possible"} else [])
    return base
