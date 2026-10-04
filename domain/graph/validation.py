"""Publication gates: topology, provenance and stable physical asset bindings."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from math import isfinite
from .models import records, instant, content_hash
from .routing import INVALIDATABLE_FEATURES


def validate_graph(graph: dict) -> dict:
    errors, warnings = [], []
    for collection in ("nodes", "edges", "assets", "places", "entrances", "evidence"):
        values = records(graph, collection)
        if not isinstance(values, list) or any(not isinstance(r, dict) or not isinstance(r.get("id"), str) or not r["id"] for r in values):
            errors.append({"code": "invalid_collection_or_id", "collection": collection})
            continue
        ids = [r.get("id") for r in records(graph, collection)]
        for key, count in Counter(ids).items():
            if key is None or count > 1:
                errors.append({"code": "duplicate_or_missing_id", "collection": collection, "id": key})
    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings, "components": [], "node_count": 0, "edge_count": 0, "entrance_count": 0, "graph_hash": None}
    nodes = {n["id"]: n for n in records(graph, "nodes")}
    assets = {a["id"]: a for a in records(graph, "assets")}
    places = {p["id"]: p for p in records(graph, "places")}
    entrances = {e["id"]: e for e in records(graph, "entrances")}
    for node in nodes.values():
        if any(not isinstance(node.get(k), (int, float)) or isinstance(node.get(k), bool) or not isfinite(node[k]) for k in ("lon", "lat")) or not (-180 <= node["lon"] <= 180 and -90 <= node["lat"] <= 90):
            errors.append({"code": "invalid_coordinate", "node_id": node["id"]})
    adjacency = {nid: set() for nid in nodes}
    for edge in records(graph, "edges"):
        if edge.get("u") not in nodes or edge.get("v") not in nodes:
            errors.append({"code": "dangling_edge", "edge_id": edge["id"]})
            continue
        if edge.get("asset_id") not in assets:
            errors.append({"code": "missing_asset", "edge_id": edge["id"]})
        for key in ("length_m", "duration_s"):
            if not isinstance(edge.get(key), (int, float)) or not isfinite(edge[key]) or edge[key] <= 0:
                errors.append({"code": "invalid_edge_measurement", "edge_id": edge["id"], "feature": key})
        cost = edge.get("preference_cost", edge.get("length_m", 0))
        if not isinstance(cost, (int, float)) or not isfinite(cost) or cost < 0:
            errors.append({"code": "negative_preference_cost", "edge_id": edge["id"]})
        if edge.get("geometry"):
            geometry = edge["geometry"]
            coordinates = geometry.get("coordinates", []) if isinstance(geometry, dict) else geometry
            if not isinstance(coordinates, list) or len(coordinates) < 2 or any(not isinstance(p, (list, tuple)) or len(p) != 2 or any(not isinstance(v, (int, float)) or not isfinite(v) for v in p) or not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90) for p in coordinates):
                errors.append({"code": "invalid_edge_geometry", "edge_id": edge["id"]})
        ulevel, vlevel = nodes[edge["u"]].get("level"), nodes[edge["v"]].get("level")
        kind = assets.get(edge.get("asset_id"), {}).get("kind")
        if ulevel is not None and vlevel is not None and ulevel != vlevel and kind not in {"stairs", "ramp", "elevator", "escalator"}:
            errors.append({"code": "unexplained_level_transition", "edge_id": edge["id"]})
        adjacency[edge["u"]].add(edge["v"])
        adjacency[edge["v"]].add(edge["u"])
    for entrance in entrances.values():
        if entrance.get("node_id") not in nodes or entrance.get("asset_id") not in assets or entrance.get("place_id") not in places:
            errors.append({"code": "dangling_entrance", "entrance_id": entrance["id"]})
    for place in places.values():
        if not any(e.get("place_id") == place["id"] for e in entrances.values()):
            warnings.append({"code": "place_without_entrance", "place_id": place["id"]})
    for evidence in records(graph, "evidence"):
        if evidence.get("asset_id") not in assets:
            errors.append({"code": "evidence_unknown_asset", "evidence_id": evidence["id"]})
        try:
            if instant(evidence["valid_until"]) <= instant(evidence["valid_from"]):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            errors.append({"code": "invalid_evidence_validity", "evidence_id": evidence["id"]})
        if not evidence.get("source_id"):
            warnings.append({"code": "missing_source_provenance", "evidence_id": evidence["id"]})
    for restriction in records(graph, "restrictions") + records(graph, "works"):
        scope = restriction.get("invalidated_features")
        if scope is not None and (not isinstance(scope, list) or any(not isinstance(feature, str) or feature not in INVALIDATABLE_FEATURES for feature in scope)):
            errors.append({"code": "invalid_invalidation_scope", "restriction_id": restriction.get("id")})
    components, remaining = [], set(nodes)
    while remaining:
        first = remaining.pop()
        component, frontier = {first}, [first]
        while frontier:
            current = frontier.pop()
            for neighbor in adjacency[current] & remaining:
                remaining.remove(neighbor)
                component.add(neighbor)
                frontier.append(neighbor)
        components.append(sorted(component))
    if len(components) > 1:
        warnings.append({"code": "disconnected_components_preserved", "count": len(components)})
    return {"valid": not errors, "errors": errors, "warnings": warnings, "components": components,
            "node_count": len(nodes), "edge_count": len(records(graph, "edges")), "entrance_count": len(entrances),
            "graph_hash": content_hash(graph) if not errors else None}


def rebind_assets(old_graph: dict, new_graph: dict, restrictions: list[dict]) -> dict:
    """Never silently drop a closure when an OSM way is split or renumbered.

    Stable asset IDs are authoritative. Importers can supply explicit previous
    edge IDs in ``source_edge_ids``. Ambiguous geometric proximity deliberately
    remains unresolved and requires operator review before atomic publication.
    """
    bindings, unresolved = [], []
    old_edges = {e["id"]: e for e in records(old_graph, "edges")}
    new_edges = records(new_graph, "edges")
    required_assets = set()
    for restriction in restrictions:
        if restriction.get("status") in {"resolved", "rejected"}:
            continue
        if restriction.get("asset_id"):
            required_assets.add(restriction["asset_id"])
        required_assets.update(restriction.get("asset_ids", []))
        if restriction.get("failure_group_id"):
            required_assets.update(a["id"] for a in records(old_graph, "assets") if a.get("failure_group_id") == restriction["failure_group_id"])
        for eid in restriction.get("edge_ids", []):
            if eid in old_edges:
                required_assets.add(old_edges[eid]["asset_id"])
            else:
                unresolved.append({"restriction_id": restriction.get("id"), "edge_id": eid, "reason": "unknown_old_edge"})
    all_assets = {a["id"] for a in records(new_graph, "assets")} | required_assets
    entrance_assets = {e["asset_id"] for e in records(new_graph, "entrances")}
    for asset_id in all_assets:
        matching = [e for e in new_edges if e.get("asset_id") == asset_id]
        old_ids = {e["id"] for e in old_edges.values() if e.get("asset_id") == asset_id}
        lineage = [e for e in new_edges if old_ids & set(e.get("source_edge_ids", []))]
        if lineage and any(e.get("asset_id") != asset_id for e in lineage):
            unresolved.append({"asset_id": asset_id, "candidate_edge_ids": [e["id"] for e in lineage], "reason": "conflicting_asset_lineage"})
        if asset_id in required_assets and not matching and asset_id not in entrance_assets:
            unresolved.append({"asset_id": asset_id, "reason": "active_restriction_unbound"})
        bindings.append({"asset_id": asset_id, "graph_version": new_graph.get("version"), "edge_ids": [e["id"] for e in matching]})
    remapped = deepcopy(restrictions)
    for restriction in remapped:
        if restriction.get("status") in {"resolved", "rejected"}:
            continue
        old_restricted_ids = set(restriction.get("edge_ids", []))
        if not old_restricted_ids:
            continue
        edge_assets = {old_edges[eid]["asset_id"] for eid in old_restricted_ids if eid in old_edges}
        new_restricted_ids = {e["id"] for e in new_edges if e["id"] in old_restricted_ids or set(e.get("source_edge_ids", [])) & old_restricted_ids or e.get("asset_id") in edge_assets}
        restriction["edge_ids"] = sorted(new_restricted_ids)
        restriction["asset_ids"] = sorted(set(restriction.get("asset_ids", [])) | edge_assets)
        restriction["binding_graph_version"] = new_graph.get("version")
    validation = validate_graph(new_graph)
    return {"publication_allowed": validation["valid"] and not unresolved, "bindings": bindings,
            "restrictions": remapped, "unresolved": unresolved, "validation": validation, "previous_version_retained": bool(unresolved or not validation["valid"])}
