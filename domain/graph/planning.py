"""Reproducible whole-window schedule evaluation and finite-catalog search."""
from __future__ import annotations
from copy import deepcopy
from itertools import product
from math import prod
from time import monotonic
from .models import records, instant, iso, profile_for, content_hash
from .routing import route, ALGORITHM_VERSION
from .fixture import at


def default_variants(graph: dict) -> list[dict]:
    works = records(graph, "works") or records(graph, "restrictions")
    if {w["id"] for w in works} != {"X", "Y"}:
        return []
    safe, touching, delayed = deepcopy(works), deepcopy(works), deepcopy(works)
    for items, start, end in [(safe, "14:30", "20:30"), (touching, "14:00", "20:00"), (delayed, "14:30", "20:30")]:
        for item in items:
            if item["id"] == "Y":
                item.update(start=at(start), end=at(end))
    for item in delayed:
        if item["id"] == "X":
            item["verified_open_at"] = at("14:15")
    return [
        {"id": "safe", "name": "Y od 14:30 · 30 min wspólnej drożności", "restrictions": safe, "cost": None,
         "assumptions": ["Potwierdzone otwarcie X o 14:00.", "Oba przejścia pozostają otwarte od 14:00 do 14:30.", "Wymagana kontrola przed zamknięciem Y."]},
        {"id": "touching", "name": "Y od 14:00 · bez wspólnej drożności", "restrictions": touching, "cost": None,
         "assumptions": ["Potwierdzone otwarcie X o 14:00."]},
        {"id": "delayed", "name": "Y od 14:30 · otwarcie X opóźnione", "restrictions": delayed, "cost": None,
         "assumptions": ["Otwarcie X potwierdzone dopiero o 14:15."]},
    ]


def normalize_request(graph: dict, request: dict) -> dict:
    horizon = request.get("horizon", graph.get("horizon"))
    if not horizon or instant(horizon["end"]) <= instant(horizon["start"]):
        raise ValueError("Horyzont musi mieć dodatnią długość i jednoznaczną strefę.")
    profiles = [profile_for(graph, p) for p in request.get("profiles", [records(graph, "profiles")[0]])]
    origins = request.get("origins", [o["id"] for o in records(graph, "origins")])
    origins = [o["id"] if isinstance(o, dict) else o for o in origins]
    destinations = request.get("destinations", [records(graph, "places")[0]["id"]] if records(graph, "places") else [])
    # The same service category is one relation, regardless of destination count.
    origins = list(dict.fromkeys(origins))
    profiles = list({p["id"]: p for p in profiles}.values())
    destinations = list({content_hash(c): c for c in destinations}.values())
    if not origins or not destinations or not profiles:
        raise ValueError("Analiza wymaga początków, profili i celów.")
    return {**request, "horizon": horizon, "origins": origins, "profiles": profiles, "destinations": destinations,
            "baseline_kind": request.get("baseline_kind", "schedule_without_intervention"),
            "max_labels": request.get("max_labels", 100000)}


def relations(request: dict) -> list[dict]:
    result = []
    for origin, profile, destination in product(request["origins"], request["profiles"], request["destinations"]):
        category = destination.get("category") if isinstance(destination, dict) else None
        destination_id = "category:" + category if category else str(destination)
        rid = f"{origin}|{profile['id']}|{destination_id}"
        weight = float(request.get("weights", {}).get(rid, 1))
        if weight < 0:
            raise ValueError("Wagi relacji nie mogą być ujemne.")
        result.append({"id": rid, "origin": origin, "profile": profile, "destination": destination,
                       "profile_id": profile["id"], "destination_id": destination_id, "kind": "category" if category else "specific",
                       "weight": weight})
    return result


def temporal_boundaries(graphs: list[dict], schedules: list[list[dict]], request: dict) -> list[float]:
    start, end = instant(request["horizon"]["start"]), instant(request["horizon"]["end"])
    raw = {start, end}
    for graph in graphs:
        for obj in records(graph, "evidence") + [graph]:
            for key in ("valid_from", "valid_until", "verified_open_at"):
                if obj.get(key):
                    raw.add(instant(obj[key]))
    for schedule in schedules:
        for obj in schedule:
            for key in ("start", "end", "verified_open_at"):
                if obj.get(key):
                    raw.add(instant(obj[key]))
    for resource in request.get("resources", {}).values():
        if isinstance(resource, dict):
            for window in resource.get("windows", []):
                raw.update(instant(window[key]) for key in ("start", "end"))
    boundaries = raw | {t - p["max_duration_s"] for t in raw for p in request["profiles"]}
    return sorted({start, end} | {t for t in boundaries if start < t < end})


def apply_actions(graph: dict, variant: dict, request: dict) -> tuple[dict, list[dict]]:
    result = deepcopy(graph)
    schedule = deepcopy(variant.get("restrictions", variant.get("works", request.get("restrictions", records(graph, "restrictions")))))
    for action in variant.get("actions", []):
        kind = action.get("kind")
        if kind == "shift":
            for item in schedule:
                if item["id"] == action["work_id"]:
                    item.update(start=action["start"], end=action["end"])
        elif kind in {"repair", "measurement", "maintain_bypass"}:
            for change in action.get("features", [action] if "feature" in action else []):
                asset_id = change.get("asset_id", action.get("asset_id"))
                feature = change["feature"]
                result.setdefault("evidence", []).append({"id": f"assumption-{action['id']}-{asset_id}-{feature}", "asset_id": asset_id,
                                           "feature": feature, "value": change.get("value"), "unit": change.get("unit"),
                                           "valid_from": action.get("effective_from", action.get("end", request["horizon"]["start"])),
                                           "valid_until": action.get("valid_until", iso(instant(request["horizon"]["end"]) + max(p["max_duration_s"] for p in request["profiles"]))),
                                           "status": "assumed", "layer": "scenario", "method": "scenario_assumption", "action_id": action["id"]})
            # Explicit restriction IDs only. One repair never clears other faults.
            for item in schedule:
                if item["id"] in action.get("resolves_restriction_ids", []):
                    item["verified_open_at"] = action.get("effective_from", action.get("end", request["horizon"]["start"]))
    return result, schedule


def feasibility(graph: dict, variant: dict, schedule: list[dict], request: dict) -> dict:
    errors = []
    baseline = request.get("works", records(graph, "works"))
    baseline_by_id = {w["id"]: w for w in baseline}
    works_by_id = {w["id"]: w for w in schedule if w["id"] in baseline_by_id}
    schedule_ids = [work["id"] for work in schedule]
    if len(schedule_ids) != len(set(schedule_ids)):
        errors.append({"code": "duplicate_restriction", "message": "Każde ograniczenie musi wystąpić w harmonogramie dokładnie raz."})
    original_restrictions = {r["id"]: r for r in request.get("restrictions", records(graph, "restrictions"))}
    for identifier, original_restriction in original_restrictions.items():
        corresponding = next((item for item in schedule if item["id"] == identifier), None)
        if corresponding is None and identifier not in baseline_by_id:
            errors.append({"code": "restriction_removed_without_action", "restriction_id": identifier})
        elif corresponding and any(corresponding.get(key) != original_restriction.get(key) for key in ("asset_id", "asset_ids", "failure_group_id", "edge_ids", "kind", "status", "layer", "invalidated_features")):
            errors.append({"code": "physical_scope_changed", "restriction_id": identifier, "message": "Wariant terminów nie może przenieść ograniczenia na inny obiekt."})
    if set(baseline_by_id) != set(works_by_id):
        errors.append({"code": "missing_work", "message": "Wariant musi zakończyć wszystkie te same prace."})
    hstart, hend = instant(request["horizon"]["start"]), instant(request["horizon"]["end"])
    for wid, work in works_by_id.items():
        start, end = instant(work["start"]), instant(work["end"])
        original = baseline_by_id[wid]
        required_duration = original.get("duration_s", instant(original["end"]) - instant(original["start"]))
        if end - start != required_duration:
            errors.append({"code": "duration_changed", "work_id": wid, "message": "Nie zachowano pełnego czasu pracy."})
        if start < hstart or end > hend:
            errors.append({"code": "outside_horizon", "work_id": wid, "message": "Prace wykraczają poza wspólny horyzont."})
        if original.get("earliest_start") and start < instant(original["earliest_start"]):
            errors.append({"code": "window_violation", "work_id": wid})
        if original.get("latest_end") and end > instant(original["latest_end"]):
            errors.append({"code": "window_violation", "work_id": wid})
        for dependency in original.get("depends_on", []):
            depid = dependency if isinstance(dependency, str) else dependency["id"]
            lag = 0 if isinstance(dependency, str) else dependency.get("lag_s", 0)
            if depid not in works_by_id or instant(works_by_id[depid]["end"]) + lag > start:
                errors.append({"code": "dependency_violation", "work_id": wid, "depends_on": depid})
    actions = variant.get("actions", [])
    action_ids = {a["id"] for a in actions}
    if len(action_ids) != len(actions):
        errors.append({"code": "duplicate_action", "message": "Działanie można uwzględnić tylko raz."})
    for action in actions:
        missing = set(action.get("requires", [])) - action_ids
        conflict = set(action.get("excludes", [])) & action_ids
        if missing:
            errors.append({"code": "action_dependency", "action_id": action["id"], "missing": sorted(missing)})
        if conflict:
            errors.append({"code": "action_exclusion", "action_id": action["id"], "conflicts": sorted(conflict)})
        if action.get("approved_feasible") is False:
            errors.append({"code": "unapproved_action", "action_id": action["id"]})
        if action.get("start") and action.get("end"):
            if instant(action["start"]) < hstart or instant(action["end"]) > hend:
                errors.append({"code": "action_outside_horizon", "action_id": action["id"]})
    activities = list(works_by_id.values()) + [a for a in actions if a.get("start") and a.get("end") and a.get("kind") != "shift"]
    resources = request.get("resources", {})
    resource_ids = {a.get("resource") for a in activities if a.get("resource")}
    for rid in resource_ids:
        resource_activities = [a for a in activities if a.get("resource") == rid]
        capacity = resources.get(rid, {}).get("capacity", 1) if isinstance(resources.get(rid, {}), dict) else resources[rid]
        boundaries = sorted({instant(a[k]) for a in resource_activities for k in ("start", "end")})
        for start, end in zip(boundaries, boundaries[1:]):
            probe = (start + end) / 2
            used = sum(a.get("resource_units", 1) for a in resource_activities if instant(a["start"]) <= probe < instant(a["end"]))
            if used > capacity:
                errors.append({"code": "resource_capacity", "resource": rid, "start": iso(start), "end": iso(end), "required": used, "capacity": capacity})
        windows = resources.get(rid, {}).get("windows", []) if isinstance(resources.get(rid, {}), dict) else []
        for activity in resource_activities:
            if windows and not any(instant(w["start"]) <= instant(activity["start"]) and instant(activity["end"]) <= instant(w["end"]) for w in windows):
                errors.append({"code": "resource_window", "resource": rid, "activity_id": activity["id"]})
    costs = [a.get("cost") for a in actions] if actions else [variant.get("cost")]
    cost = sum(costs) if all(c is not None for c in costs) else None
    budget = request.get("budget")
    budget_status = "unknown" if cost is None else "not_requested" if budget is None else "within_budget" if cost <= budget else "exceeded"
    if budget_status == "exceeded":
        errors.append({"code": "budget_exceeded", "cost": cost, "budget": budget})
    unverified = ["cost"] if budget is not None and cost is None else []
    return {"feasible": not errors and not unverified, "errors": errors, "unverified_requirements": unverified, "cost": cost, "cost_known": cost is not None, "budget_status": budget_status,
            "all_works_completed": set(baseline_by_id) == set(works_by_id) and not any(e["code"] in {"duration_changed", "outside_horizon"} for e in errors)}


def evaluate_schedule(graph: dict, schedule: list[dict], request: dict, boundaries: list[float], *, layer: str) -> dict:
    rels = relations(request)
    horizon_hours = (boundaries[-1] - boundaries[0]) / 3600
    metrics = {"available_relation_hours": 0.0, "unavailable_relation_hours": 0.0, "unknown_relation_hours": 0.0,
               "incomplete_relation_hours": 0.0, "weighted_available_relation_hours": 0.0, "instantaneous_lost_relation_hours": 0.0,
               "instantaneous_unknown_relation_hours": 0.0, "total_relation_hours": len(rels) * horizon_hours,
               "relation_count": len(rels), "longest_interruption_hours": 0.0}
    per_relation, timeline, by_profile, by_kind, by_origin = [], [], {}, {}, {}
    # Validity depends on profile and time, not on the requested origin/target.
    # This cache lives for exactly one frozen schedule evaluation.
    state_cache = {}
    incomplete_intervals = [{"start": iso(a), "end": iso(b), "hours": (b-a)/3600, "status": "incomplete", "reason_codes": ["calculation_timeout"],
                             "distance_m": None, "duration_s": None, "path": []} for a, b in zip(boundaries, boundaries[1:])]
    for relation in rels:
        row = {k: relation[k] for k in ("id", "origin", "profile_id", "destination_id", "kind", "weight")}
        row.update(available_hours=0.0, unavailable_hours=0.0, unknown_hours=0.0, incomplete_hours=0.0, longest_interruption_hours=0.0, intervals=[])
        interruption = 0.0
        for interval_index, (a, b) in enumerate(zip(boundaries, boundaries[1:])):
            if request.get("_deadline") is not None and monotonic() >= request["_deadline"]:
                remainder = (boundaries[-1]-a)/3600
                row["incomplete_hours"] += remainder
                metrics["incomplete_relation_hours"] += remainder
                metrics["instantaneous_unknown_relation_hours"] += remainder
                row["intervals"].extend(incomplete_intervals[interval_index:])
                break
            probe, hours = (a + b) / 2, (b - a) / 3600
            result = route(graph, relation["profile"], relation["origin"], relation["destination"], probe, schedule, layer,
                           max_labels=request["max_labels"], deadline=request.get("_deadline"), state_cache=state_cache)
            diagnostic = route(graph, relation["profile"], relation["origin"], relation["destination"], probe, schedule, layer,
                               max_labels=request["max_labels"], instantaneous=True, deadline=request.get("_deadline"), state_cache=state_cache)
            status = result["status"]
            column = "available" if status == "confirmed" else "unknown" if status in {"possible", "outside_coverage"} else "incomplete" if status == "incomplete" else "unavailable"
            row[column + "_hours"] += hours
            metrics[column + "_relation_hours"] += hours
            if status == "confirmed":
                metrics["weighted_available_relation_hours"] += hours * relation["weight"]
                interruption = 0.0
            elif column == "unavailable":
                interruption += hours
                row["longest_interruption_hours"] = max(row["longest_interruption_hours"], interruption)
            else:
                interruption = 0.0
            if diagnostic["status"] in {"barrier", "limit", "no_connection"}:
                metrics["instantaneous_lost_relation_hours"] += hours
            elif diagnostic["status"] != "confirmed":
                metrics["instantaneous_unknown_relation_hours"] += hours
            interval = {"start": iso(a), "end": iso(b), "hours": hours, "status": status, "reason_codes": sorted({r["code"] for r in result["reasons"]}),
                        "distance_m": result["distance_m"], "duration_s": result["duration_s"], "path": result["path"]}
            row["intervals"].append(interval)
        metrics["longest_interruption_hours"] = max(metrics["longest_interruption_hours"], row["longest_interruption_hours"])
        per_relation.append(row)
        for key, target in [(row["profile_id"], by_profile), (row["kind"], by_kind), (row["origin"], by_origin)]:
            group = target.setdefault(key, {"relation_count": 0, "available_relation_hours": 0, "unavailable_relation_hours": 0, "unknown_relation_hours": 0, "incomplete_relation_hours": 0})
            group["relation_count"] += 1
            for col in ("available", "unavailable", "unknown", "incomplete"):
                group[col + "_relation_hours"] += row[col + "_hours"]
    for idx, (a, b) in enumerate(zip(boundaries, boundaries[1:])):
        statuses = [r["intervals"][idx]["status"] for r in per_relation]
        timeline.append({"start": iso(a), "end": iso(b), "hours": (b-a)/3600, "confirmed": statuses.count("confirmed"),
                         "unknown": sum(s in {"possible", "outside_coverage"} for s in statuses), "unavailable": sum(s in {"barrier", "limit", "no_connection"} for s in statuses),
                         "incomplete": statuses.count("incomplete"), "total": len(rels)})
    critical_ids = set(request.get("critical_relation_ids", [r["id"] for r in rels]))
    critical_violations = [{"relation_id": r["id"], "unavailable_hours": r["unavailable_hours"], "unknown_hours": r["unknown_hours"], "incomplete_hours": r["incomplete_hours"]}
                           for r in per_relation if r["id"] in critical_ids and r["available_hours"] < horizon_hours - 1e-10]
    for key in metrics:
        if isinstance(metrics[key], float):
            metrics[key] = round(metrics[key], 10)
    return {"metrics": metrics, **metrics, "relations": per_relation, "timeline": timeline, "by_profile": by_profile,
            "by_kind": by_kind, "by_origin": by_origin, "critical_satisfied": not critical_violations,
            "critical_violations": critical_violations, "complete": metrics["incomplete_relation_hours"] == 0,
            "unit": "godziny dopuszczalnego rozpoczęcia całej podróży dla relacji", "restrictions": schedule}


def compare(baseline: dict, variant: dict) -> dict:
    recovered = lost = detour_sum = detour_weight = 0.0
    knowledge_gain = physical_recovery = 0.0
    recovering, losing = set(), set()
    changes = []
    for before, after in zip(baseline["relations"], variant["relations"]):
        row_recovered = row_lost = 0.0
        for b, a in zip(before["intervals"], after["intervals"]):
            hours = b["hours"]
            if b["status"] != "confirmed" and a["status"] == "confirmed":
                recovered += hours
                row_recovered += hours
                recovering.add(after["id"])
                if b["status"] in {"possible", "outside_coverage", "incomplete"}:
                    knowledge_gain += hours
                else:
                    physical_recovery += hours
            if b["status"] == "confirmed" and a["status"] != "confirmed":
                lost += hours
                row_lost += hours
                losing.add(after["id"])
            if b["status"] == a["status"] == "confirmed":
                detour_sum += (a["distance_m"] - b["distance_m"]) * hours
                detour_weight += hours
        changes.append({"relation_id": after["id"], "profile_id": after["profile_id"], "recovered_hours": row_recovered, "lost_hours": row_lost})
    return {"recovered_relation_hours": round(recovered, 10), "lost_relation_hours": round(lost, 10),
            "knowledge_gain_relation_hours": round(knowledge_gain, 10), "confirmed_access_recovery_relation_hours": round(physical_recovery, 10),
            "net_relation_hours": round(recovered-lost, 10), "recovered_relations": sorted(recovering), "lost_relations": sorted(losing),
            "changes": changes, "mean_distance_change_m": round(detour_sum / detour_weight, 2) if detour_weight else None}


def evaluate(graph: dict, request: dict | None = None) -> dict:
    request = normalize_request(graph, request or {})
    if request.get("time_limit_s") is not None and not request.get("_deadline"):
        request["_deadline"] = monotonic() + max(0, float(request["time_limit_s"]))
    baseline_schedule = deepcopy(request.get("restrictions", records(graph, "restrictions")))
    raw_variants = request.get("variants")
    if raw_variants is None:
        raw_variants = default_variants(graph)
    prepared = [(v, *apply_actions(graph, v, request)) for v in raw_variants]
    boundaries = temporal_boundaries([graph] + [g for _, g, _ in prepared], [baseline_schedule] + [s for _, _, s in prepared], request)
    baseline = evaluate_schedule(graph, baseline_schedule, request, boundaries, layer=graph.get("layer", "fixture"))
    baseline.update(id="baseline", name="Harmonogram bazowy", baseline_kind=request["baseline_kind"])
    variants = []
    for raw, variant_graph, schedule in prepared:
        result = evaluate_schedule(variant_graph, schedule, request, boundaries, layer="scenario")
        feasibility_result = feasibility(graph, raw, schedule, request)
        result.update(id=raw.get("id", content_hash(raw)[:12]), name=raw.get("name", "Wariant ręczny"),
                      feasibility=feasibility_result, feasible=feasibility_result["feasible"], cost=feasibility_result["cost"],
                      assumptions=raw.get("assumptions", []), actions=raw.get("actions", []), layer="scenario", full_graph_verified=True)
        result.update(compare(baseline, result))
        kinds = {a.get("kind") for a in raw.get("actions", [])}
        result["benefit_kind"] = "knowledge" if kinds == {"measurement"} else "infrastructure" if "repair" in kinds else "schedule"
        result["success"] = result["feasible"] and result["critical_satisfied"] and result["complete"]
        variants.append(result)
    feasible = [v for v in variants if v["feasible"] and v["complete"]]
    ranked = sorted(feasible, key=lambda v: (not v["critical_satisfied"], -v["weighted_available_relation_hours"], v["lost_relation_hours"], v["longest_interruption_hours"], v["cost"] is None, v["cost"] or 0))
    # Unknown costs cannot dominate known costs or vice versa.
    nondominated = []
    for candidate in feasible:
        def dominates(other):
            if candidate is other or (candidate["cost"] is None) != (other["cost"] is None):
                return False
            c = [int(candidate["critical_satisfied"]), candidate["available_relation_hours"], -candidate["lost_relation_hours"], -candidate["longest_interruption_hours"], -(candidate["cost"] or 0)]
            o = [int(other["critical_satisfied"]), other["available_relation_hours"], -other["lost_relation_hours"], -other["longest_interruption_hours"], -(other["cost"] or 0)]
            return all(a >= b for a, b in zip(o, c)) and any(a > b for a, b in zip(o, c))
        if not any(dominates(other) for other in feasible):
            nondominated.append(candidate["id"])
    snapshot = {"graph_version": graph.get("version"), "evidence_version": graph.get("evidence_version"), "graph_hash": content_hash(graph),
                "request_hash": content_hash({k: v for k, v in request.items() if not k.startswith("_")}), "algorithm_version": ALGORITHM_VERSION, "horizon": request["horizon"],
                "origins": request["origins"], "profiles": request["profiles"], "destinations": request["destinations"], "baseline_kind": request["baseline_kind"],
                "layer": graph.get("layer"), "assumptions": {v["id"]: v["assumptions"] for v in variants}}
    snapshot["hash"] = content_hash(snapshot)
    selected = ranked[0] if ranked else None
    work_impacts = []
    if request.get("include_work_impacts", True) and len(baseline_schedule) > 1:
        for work in baseline_schedule:
            solo = evaluate_schedule(graph, [work], request, boundaries, layer=graph.get("layer", "fixture"))
            work_impacts.append({"work_id": work["id"], "name": work.get("name", work["id"]), "metrics": solo["metrics"],
                                 "critical_satisfied": solo["critical_satisfied"], "complete": solo["complete"]})
    all_complete = baseline["complete"] and all(v["complete"] for v in variants) and all(w["complete"] for w in work_impacts)
    return {"baseline": baseline, "variants": variants, "work_impacts": work_impacts, "recommended_id": selected["id"] if selected else None,
            "recommendation_status": "critical_satisfied" if selected and selected["success"] else "least_loss" if selected else "no_feasible_variant",
            "nondominated_ids": nondominated, "snapshot": snapshot, "horizon": request["horizon"], "boundaries": [iso(b) for b in boundaries],
            "layer": "scenario", "data_layer": graph.get("layer"), "solver_status": "OPTIMAL" if all_complete else "UNKNOWN", "complete": all_complete,
            "scope": "Pełny przegląd przekazanych wariantów. Optimum dotyczy tego skończonego katalogu i jawnej kolejności kryteriów.",
            "ranking_criteria": ["wymagania krytyczne", "ważone godziny dostępności", "pogorszenia", "najdłuższa przerwa", "znany koszt"],
            "notice": "Symulacja na zamrożonych danych. Zatwierdzenie wariantu nie zmienia obserwowanej infrastruktury."}


def failure_analysis(graph: dict, request: dict | None = None) -> dict:
    request = normalize_request(graph, request or {})
    request = {**request, "variants": [], "include_work_impacts": False, "restrictions": request.get("restrictions", [])}
    base = evaluate(graph, request)["baseline"]
    assets = records(graph, "assets")
    groups = sorted({a["failure_group_id"] for a in assets if a.get("failure_group_id")})
    trials = []
    for group in groups:
        trials.append(({"failure_group_id": group}, [a for a in assets if a.get("failure_group_id") == group]))
    for asset in assets:
        trials.append(({"asset_id": asset["id"]}, [asset]))
    rows = []
    for target, affected_assets in trials:
        fault = {"id": "failure-test", **target, "kind": "closure", "status": "confirmed", "layer": graph.get("layer", "fixture"),
                 "start": request["horizon"]["start"], "end": iso(instant(request["horizon"]["end"]) + max(p["max_duration_s"] for p in request["profiles"]))}
        result = evaluate(graph, {**request, "restrictions": request["restrictions"] + [fault]})["baseline"]
        rows.append({**target, "name": ", ".join(a.get("name", a["id"]) for a in affected_assets), "asset_ids": [a["id"] for a in affected_assets],
                     "baseline_available_relation_hours": base["available_relation_hours"], "available_relation_hours": result["available_relation_hours"],
                     "lost_relation_hours": base["available_relation_hours"] - result["available_relation_hours"],
                     "affected_relations": [r["id"] for r in result["relations"] if r["available_hours"] < next(b["available_hours"] for b in base["relations"] if b["id"] == r["id"])],
                     "complete": result["complete"]})
    return {"failures": sorted(rows, key=lambda r: -r["lost_relation_hours"]), "baseline": base["metrics"],
            "notice": "Test pojedynczej awarii całego obiektu lub grupy wspólnej przyczyny w modelu."}


def verification_impact(graph: dict, request: dict | None = None) -> dict:
    from .routing import object_state
    request = normalize_request(graph, request or {})
    unknowns = {}
    for profile in request["profiles"]:
        for edge in records(graph, "edges") + [{**e, "is_entrance": True} for e in records(graph, "entrances")]:
            state = object_state(graph, edge["asset_id"], None if edge.get("is_entrance") else edge, profile, instant(request["horizon"]["start"]),
                                 instant(request["horizon"]["end"]) + profile["max_duration_s"], request.get("restrictions", records(graph, "restrictions")), graph.get("layer", "fixture"))
            for reason in state["reasons"]:
                if reason.get("feature") and reason["code"] in {"missing_or_expired_evidence", "conflicting_evidence"}:
                    unknowns[(reason["asset_id"], reason["feature"])] = profile
    rows = []
    for (asset_id, feature), profile in unknowns.items():
        positive = {"open": True, "steps": False, "width_m": profile.get("min_width_m", 0.9), "kerb_cm": 0,
                    "slope_pct": 0, "surface": profile.get("allowed_surfaces", ["asphalt"])[0]}[feature]
        negative = {"open": False, "steps": True, "width_m": 0, "kerb_cm": 100, "slope_pct": 100, "surface": "impassable"}[feature]
        variants = [{"id": outcome, "name": outcome, "actions": [{"id": "measurement", "kind": "measurement", "asset_id": asset_id,
                        "feature": feature, "value": value, "effective_from": request["horizon"]["start"]}]} for outcome, value in [("positive", positive), ("negative", negative)]]
        result = evaluate(graph, {**request, "variants": variants})
        yes, no = result["variants"]
        rows.append({"asset_id": asset_id, "feature": feature, "measurement": {"method": "Pomiar w terenie" if feature in {"width_m", "kerb_cm", "slope_pct"} else "Obserwacja terenowa",
                     "unit": {"width_m": "m", "kerb_cm": "cm", "slope_pct": "%"}.get(feature), "threshold": positive,
                     "instruction": f"Sprawdź cechę {feature} obiektu {asset_id}. Zapisz metodę, czas, wartość i zakres dowodu."},
                     "positive_available_relation_hours": yes["available_relation_hours"], "negative_available_relation_hours": no["available_relation_hours"],
                     "potential_relation_hours": yes["available_relation_hours"] - no["available_relation_hours"],
                     "affected_relations": sorted(set(yes["recovered_relations"]) | set(no["lost_relations"])),
                     "knowledge_change_only": True})
    return {"measurements": sorted(rows, key=lambda r: -r["potential_relation_hours"]), "notice": "Potencjalny wpływ pomiaru, bez założeń o prawdopodobieństwie i bez przypisywania poprawy infrastruktury."}
