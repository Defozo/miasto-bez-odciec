"""CP-SAT access witnesses over a bounded pool of legal, repairable paths.

Paths are generated on the physical graph before filtering observations, so a
route requiring two independent repairs is retained. Local truth tables bind
each object's whole-window validity to exactly the catalogue choices affecting
it. No truth table row inferred from one feature confirms another feature.
"""
from itertools import product
from time import monotonic

from .models import content_hash, records
from .planning import apply_actions, relations, temporal_boundaries
from .routing import destination_entrances, object_state


def legal_paths(graph, relation, limit, deadline):
    profile = relation["profile"]
    targets = {}
    for entrance in destination_entrances(graph, relation["destination"]):
        targets.setdefault(entrance["node_id"], []).append(entrance)
    adjacency = {}
    for edge in records(graph, "edges"):
        adjacency.setdefault(edge["u"], []).append(edge)
    result, stack = [], [(relation["origin"], (), frozenset([relation["origin"]]), 0, 0)]
    while stack:
        if monotonic() >= deadline or len(result) >= limit:
            return result, False
        node, path, visited, distance, duration = stack.pop()
        for entrance in targets.get(node, []):
            result.append({"edges": path, "entrance": entrance})
            if len(result) >= limit:
                return result, False
        for edge in adjacency.get(node, []):
            if edge["v"] in visited:
                continue
            next_distance, next_duration = distance+edge["length_m"], duration+edge["duration_s"]
            if next_distance <= profile["max_distance_m"] and next_duration <= profile["max_duration_s"]:
                stack.append((edge["v"], path+(edge,), visited | {edge["v"]}, next_distance, next_duration))
    return result, True


def add_access_model(model, variables, choices, variant_for, graph, request, deadline):
    base_indices = [0]*len(choices)
    # Every possible change contributes time boundaries, including a boundary
    # shifted backwards by tau for conservative whole-journey eligibility.
    variants = [variant_for(base_indices)]
    for group, options in enumerate(choices):
        for option in range(len(options)):
            indices = base_indices.copy()
            indices[group] = option
            variants.append(variant_for(indices))
    prepared = [apply_actions(graph, variant, request) for variant in variants]
    boundaries = temporal_boundaries([graph]+[g for g, _ in prepared], [s for _, s in prepared], request)
    rels = relations(request)
    critical_ids = set(request.get("critical_relation_ids", [r["id"] for r in rels]))
    pool_complete, tables_complete = True, True
    total_paths, total_tables, table_rows = 0, 0, 0
    cache, prepared_cache, access_terms, critical_terms = {}, {}, [], []
    path_limit = max(1, min(10000, int(request.get("max_paths_per_relation", 128))))
    table_limit = max(1, min(65536, int(request.get("max_local_assignments", 4096))))

    def eligibility(asset_id, edge, profile, start, end):
        nonlocal tables_complete, total_tables, table_rows
        key = (asset_id, edge["id"] if edge else None, content_hash(profile), start, end)
        if key in cache:
            return cache[key]
        relevant_groups = []
        for group, options in enumerate(choices):
            affected = False
            for option in options:
                # Schedule fragments can replace the baseline schedule, while
                # repairs only affect explicitly named physical objects.
                if option.get("works") or option.get("restrictions"):
                    affected = True
                for action in option.get("actions", [option] if option.get("kind") else []):
                    if action.get("kind") == "shift" or action.get("resolves_restriction_ids") or action.get("asset_id") == asset_id or any(f.get("asset_id", action.get("asset_id")) == asset_id for f in action.get("features", [])):
                        affected = True
            if affected:
                relevant_groups.append(group)
        valid_rows, inspected = [], 0
        all_rows = product(*[range(len(choices[g])) for g in relevant_groups])
        for row in all_rows:
            if inspected >= table_limit or monotonic() >= deadline:
                tables_complete = False
                break
            inspected += 1
            indices = base_indices.copy()
            for group, selected in zip(relevant_groups, row):
                indices[group] = selected
            signature = tuple(indices)
            if signature not in prepared_cache:
                prepared_cache[signature] = apply_actions(graph, variant_for(indices), request)
            candidate_graph, restrictions = prepared_cache[signature]
            status = object_state(candidate_graph, asset_id, edge, profile, start, end, restrictions, "scenario")["state"]
            if status == "confirmed":
                valid_rows.append(row)
        total_tables += 1
        table_rows += inspected
        eligible = model.new_bool_var(f"eligible_{total_tables}")
        if not valid_rows:
            model.add(eligible == 0)
        elif relevant_groups:
            model.add_allowed_assignments([variables[g] for g in relevant_groups], valid_rows).only_enforce_if(eligible)
        else:
            model.add(eligible == 1)
        cache[key] = eligible
        return eligible

    for relation in rels:
        if monotonic() >= deadline:
            pool_complete = tables_complete = False
            missing = model.new_bool_var("unmodeled_relations")
            model.add(missing == 0)
            critical_terms.append(missing)
            break
        paths, complete = legal_paths(graph, relation, path_limit, deadline)
        pool_complete &= complete
        total_paths += len(paths)
        for index, (left, right) in enumerate(zip(boundaries, boundaries[1:])):
            start = (left+right)/2
            end = start+relation["profile"]["max_duration_s"]
            witnesses = []
            for path_index, path in enumerate(paths):
                if monotonic() >= deadline:
                    tables_complete = False
                    break
                available = model.new_bool_var(f"path_{relation['id']}_{index}_{path_index}")
                required = [eligibility(edge["asset_id"], edge, relation["profile"], start, end) for edge in path["edges"]]
                required.append(eligibility(path["entrance"]["asset_id"], None, relation["profile"], start, end))
                for condition in required:
                    model.add(available <= condition)
                witnesses.append(available)
            access = model.new_bool_var(f"access_{relation['id']}_{index}")
            model.add_bool_or(witnesses).only_enforce_if(access)
            weight = round((right-left)*relation["weight"]*1000)
            if weight:
                access_terms.append((access, weight))
            if relation["id"] in critical_ids:
                critical_terms.append(access)
    critical = model.new_bool_var("all_critical_access")
    if critical_terms:
        for access in critical_terms:
            model.add(critical <= access)
    else:
        model.add(critical == 1)
    max_weighted = sum(weight for _, weight in access_terms)
    model.maximize(critical*(max_weighted+1)+sum(access*weight for access, weight in access_terms))
    return {"path_pool_count": total_paths, "path_pool_complete": pool_complete, "local_tables_complete": tables_complete,
            "whole_window_tables": total_tables, "local_assignments_checked": table_rows,
            "time_intervals": len(boundaries)-1, "max_paths_per_relation": path_limit,
            "objective": "Najpierw wszystkie wymagania krytyczne, następnie ważone sekundy dostępności w zadanej puli.",
            "path_pool_note": "Pula zachowuje ścieżki wymagające wielu napraw oraz niezależne limity czasu i dystansu. Optimum dotyczy wyłącznie tej puli i katalogu."}
