"""Finite action search with CP-SAT path, time, resource and dependency rules.

Every candidate, including CP-SAT solutions, is evaluated against the complete
graph. Enumeration proves the finite catalog; CP-SAT proves only its stated
catalog and legal path pool. A timed-out solve or incomplete full-graph
verification never claims optimality.
"""
from __future__ import annotations
from itertools import product
from time import monotonic
from .models import instant
from .planning import evaluate, normalize_request, apply_actions, feasibility


def load_cp_model():
    """Optional native dependency, preloaded by the worker before readiness."""
    from ortools.sat.python import cp_model
    return cp_model


def optimize_catalog(graph: dict, request: dict) -> dict:
    normalized = normalize_request(graph, request)
    catalogs = request.get("catalog", [])
    choices = [entry.get("options", []) for entry in catalogs]
    if any(not options for options in choices):
        return {"solver_status": "INFEASIBLE", "reason": "empty_catalog", "variants": [], "complete": True}
    total = 1
    for options in choices:
        total *= len(options)
    limit = int(request.get("max_variants", 4096))
    seconds = float(request.get("time_limit_s", 30))
    if limit <= 0 or seconds <= 0:
        return {"solver_status": "UNKNOWN", "complete": False, "variants": [], "reason": "calculation_limit"}
    started = monotonic()
    use_cp = request.get("solver") == "cp_sat" or total > request.get("enumeration_threshold", 128)
    schedules = []
    solver_info = {"engine": "enumeration", "catalog_combinations": total, "time_limit_s": seconds, "max_variants": limit, "solver_setup_s": 0.0}
    enumerated_all = True

    def variant_for(indices):
        selected = [choices[i][j] for i, j in enumerate(indices)]
        actions = [a for option in selected for a in option.get("actions", [option] if option.get("kind") else [])]
        schedule = [w for option in selected for w in option.get("works", option.get("restrictions", []))]
        result = {"id": "catalog-" + "-".join(str(i) for i in indices), "name": " + ".join(o.get("name", o.get("id", "Wariant")) for o in selected),
                  "actions": actions, "assumptions": [a for o in selected for a in o.get("assumptions", [])],
                  "cost": sum(o["cost"] for o in selected) if all(o.get("cost") is not None for o in selected) else None}
        if schedule:
            result["restrictions"] = schedule
        return result

    if use_cp:
        setup_started = monotonic()
        solver_info["engine"] = "cp_sat"
        try:
            cp_model = load_cp_model()
        except (ImportError, OSError):
            solver_info["solver_setup_s"] = round(monotonic()-setup_started, 3)
            return {"solver_status": "UNKNOWN", "complete": False, "variants": [], "reason": "cp_sat_adapter_unavailable", "search": solver_info}
        solver_info["solver_setup_s"] = round(monotonic()-setup_started, 3)
        # Loading native libraries is startup work, not the optimization budget.
        # Report it separately rather than exhausting solve time before solving.
        started = monotonic()
        model = cp_model.CpModel()
        variables = []
        literals = []
        activities = []
        action_literals = {}
        hstart = instant(normalized["horizon"]["start"])
        hend = instant(normalized["horizon"]["end"])
        for i, options in enumerate(choices):
            variable = model.new_int_var(0, len(options)-1, f"choice_{i}")
            variables.append(variable)
            row = []
            for j, option in enumerate(options):
                literal = model.new_bool_var(f"selected_{i}_{j}")
                model.add(variable == j).only_enforce_if(literal)
                model.add(variable != j).only_enforce_if(literal.Not())
                row.append(literal)
                for action in option.get("actions", [option] if option.get("kind") else []):
                    action_literals.setdefault(action["id"], []).append(literal)
                for activity in option.get("works", option.get("restrictions", [])) + [a for a in option.get("actions", []) if a.get("start") and a.get("end")]:
                    astart, aend = instant(activity["start"]), instant(activity["end"])
                    if astart < hstart or aend > hend or aend <= astart:
                        model.add(literal == 0)
                        continue
                    interval = model.new_optional_fixed_size_interval_var(int(astart-hstart), int(aend-astart), literal, f"interval_{i}_{j}_{activity['id']}")
                    activities.append((activity, interval, literal))
            model.add_exactly_one(row)
            literals.append(row)
        for i, options in enumerate(choices):
            for j, option in enumerate(options):
                for action in option.get("actions", [option] if option.get("kind") else []):
                    for required in action.get("requires", []):
                        required_literals = action_literals.get(required, [])
                        model.add_bool_or(required_literals).only_enforce_if(literals[i][j])
                    for excluded in action.get("excludes", []):
                        for conflict in action_literals.get(excluded, []):
                            model.add(literals[i][j] + conflict <= 1)
        for rid in {a.get("resource") for a, _, _ in activities if a.get("resource")}:
            matching = [(a, interval) for a, interval, _ in activities if a.get("resource") == rid]
            resource = request.get("resources", {}).get(rid, {})
            capacity = resource.get("capacity", 1) if isinstance(resource, dict) else resource
            model.add_cumulative([interval for _, interval in matching], [a.get("resource_units", 1) for a, _ in matching], capacity)
        from .pathpool import add_access_model
        solver_info.update(add_access_model(model, variables, choices, variant_for, graph, normalized, started+seconds*0.55))
        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        enumerated_all = False
        rejected = 0
        # Optimize actual path availability. Every proposed decision is checked
        # against domain feasibility; rejected decisions become no-good cuts.
        while monotonic()-started < seconds*0.8 and rejected < limit:
            solver.parameters.max_time_in_seconds = max(0.001, started+seconds*0.8-monotonic())
            status = solver.solve(model)
            solver_info["cp_sat_status"] = solver.status_name(status)
            if status == cp_model.INFEASIBLE:
                enumerated_all = True
                break
            if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
                break
            indices = [solver.value(v) for v in variables]
            candidate = variant_for(indices)
            _, candidate_schedule = apply_actions(graph, candidate, normalized)
            if feasibility(graph, candidate, candidate_schedule, normalized)["feasible"]:
                schedules.append(candidate)
                enumerated_all = status == cp_model.OPTIMAL
                solver_info["objective_value"] = solver.objective_value
                solver_info["objective_bound"] = solver.best_objective_bound
                break
            rejected += 1
            model.add_forbidden_assignments(variables, [indices])
        solver_info["rejected_infeasible_candidates"] = rejected
        solver_info["pool_optimality_proven"] = enumerated_all
    else:
        for indices in product(*[range(len(options)) for options in choices]):
            if len(schedules) >= limit or monotonic() - started >= seconds:
                enumerated_all = False
                break
            schedules.append(variant_for(indices))
    # Domain feasibility is authoritative for every adapter; catches requirements
    # that are not encoded in the finite CP-SAT resource model.
    feasible_variants = []
    for variant in schedules:
        _, schedule = apply_actions(graph, variant, normalized)
        if feasibility(graph, variant, schedule, normalized)["feasible"]:
            feasible_variants.append(variant)
    evaluated = []
    evaluated_all = True
    # One shared evaluation creates a common partition; reserve verification time
    # by enforcing both a candidate count cap and per-route label caps.
    for variant in feasible_variants:
        if monotonic() - started > seconds:
            evaluated_all = False
            break
        evaluated.append(variant)
    result = evaluate(graph, {**normalized, "variants": evaluated, "include_work_impacts": False, "_deadline": started + seconds})
    complete = enumerated_all and evaluated_all and result["complete"] and solver_info.get("local_tables_complete", True)
    has_feasible = any(v["feasible"] and v["complete"] for v in result["variants"])
    result["solver_status"] = "OPTIMAL" if complete and has_feasible else "INFEASIBLE" if complete else "FEASIBLE" if has_feasible else "UNKNOWN"
    result["complete"] = complete
    if use_cp:
        result["scope"] = "Optimum dotyczy zadanego katalogu i puli legalnych ścieżek. Kandydat został zweryfikowany na pełnym grafie."
        result["ranking_criteria"] = ["Wszystkie wymagania krytyczne w puli", "Ważone sekundy dostępności w puli"]
    result["search"] = {**solver_info, "enumerated_candidates": len(schedules), "verified_candidates": len(evaluated),
                        "elapsed_s": round(monotonic()-started+solver_info["solver_setup_s"], 3),
                        "solve_elapsed_s": round(monotonic()-started, 3), "full_graph_verification": True,
                        "optimality_scope": ("Zadana pula legalnych ścieżek i lokalnych stanów oraz skończony katalog" if use_cp else "Wszystkie kombinacje podanego skończonego katalogu") if complete else "Najlepszy znaleziony wariant; zakres przeszukiwania niepełny"}
    return result
