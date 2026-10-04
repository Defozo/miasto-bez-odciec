from copy import deepcopy
import pytest
from domain.graph import build_fixture, route, validate_graph, rebind_assets, elevator_fixture, failure_analysis
from domain.graph.fixture import at
from domain.graph.models import instant


def query(graph, **changes):
    request = {"profile": "wheelchair", "origin": "origin-west", "destination": "clinic", "departure": at("09:00"), "restrictions": []}
    request.update(changes)
    return route(graph, request)


def change(graph, asset_id, feature, value):
    for evidence in graph["evidence"]:
        if evidence["asset_id"] == asset_id and evidence["feature"] == feature:
            evidence["value"] = value


@pytest.mark.parametrize("feature,value", [("steps", True), ("width_m", 0.5), ("kerb_cm", 15), ("surface", "sand"), ("slope_pct", 12)])
def test_hard_requirements_exclude_not_penalize(feature, value):
    graph = build_fixture()
    for asset in ("crossing-x", "crossing-y"):
        change(graph, asset, feature, value)
    result = query(graph)
    assert result["status"] == "barrier"
    assert not result["path"]


def test_missing_feature_possible_does_not_confirm_other_features():
    graph = build_fixture()
    graph["evidence"] = [e for e in graph["evidence"] if not (e["asset_id"] in {"crossing-x", "crossing-y"} and e["feature"] == "surface")]
    result = query(graph)
    assert result["status"] == "possible"
    assert any(u["feature"] == "surface" for u in result["unknowns"])


def test_conflicting_trusted_observation_is_unknown():
    graph = build_fixture()
    for asset in ("crossing-x", "crossing-y"):
        source = next(e for e in graph["evidence"] if e["asset_id"] == asset and e["feature"] == "width_m")
        graph["evidence"].append({**source, "id": source["id"] + "-conflict", "value": 0.4})
    result = query(graph)
    assert result["status"] == "possible"
    assert any(r["code"] == "conflicting_evidence" for r in result["reasons"])


def test_expiry_during_trip_prevents_confirmation():
    graph = build_fixture()
    for e in graph["evidence"]:
        if e["asset_id"] in {"crossing-x", "crossing-y"} and e["feature"] == "width_m":
            e["valid_until"] = at("09:15")
    assert query(graph)["status"] == "possible"
    assert query(graph, departure=at("08:44"))["status"] == "confirmed"


def test_adjacent_equivalent_evidence_covers_window_without_gap():
    graph = build_fixture()
    for e in list(graph["evidence"]):
        if e["feature"] == "width_m":
            graph["evidence"].append({**e, "id": e["id"] + "-later", "valid_from": at("09:15")})
            e["valid_until"] = at("09:15")
    assert query(graph)["status"] == "confirmed"


def test_warning_requires_moderation_before_public_change():
    graph = build_fixture()
    warnings = [{"id": a, "asset_id": a, "kind": "warning", "status": "submitted", "layer": "fixture", "start": at("08:00"), "end": at("16:00")} for a in ["crossing-x", "crossing-y"]]
    assert query(graph, restrictions=warnings)["status"] == "confirmed"
    for warning in warnings:
        warning["status"] = "located_unverified"
    assert query(graph, restrictions=warnings)["status"] == "possible"
    for warning in warnings:
        warning.update(kind="closure", status="confirmed")
    assert query(graph, restrictions=warnings)["status"] == "barrier"


def test_warning_expiry_requires_recheck_not_automatic_confirmation():
    graph = build_fixture()
    warnings = [{"id": a, "asset_id": a, "kind": "warning", "status": "located_unverified", "layer": "fixture", "start": at("08:00"), "end": at("09:00")} for a in ["crossing-x", "crossing-y"]]
    assert query(graph, restrictions=warnings, departure=at("10:00"))["status"] == "possible"
    for warning in warnings:
        warning["status"] = "retired"
    assert query(graph, restrictions=warnings, departure=at("10:00"))["status"] == "confirmed"


def test_expired_observation_retains_its_historically_valid_interval():
    graph = build_fixture()
    for e in graph["evidence"]:
        e["status"] = "expired"
        e["valid_until"] = at("12:00")
    assert query(graph)["status"] == "confirmed"
    assert query(graph, departure=at("13:00"))["status"] == "possible"


def test_specific_entrance_evidence_required():
    graph = build_fixture()
    change(graph, "clinic-entrance", "width_m", 0.5)
    assert query(graph, destination="clinic-main")["status"] == "barrier"
    assert query(graph, destination="clinic-door")["status"] == "outside_coverage"


def test_separate_no_connection_outside_and_limit():
    graph = build_fixture()
    assert query(graph, origin="outside")["status"] == "outside_coverage"
    limited = {**graph["profiles"][0], "max_distance_m": 1}
    assert query(graph, profile=limited)["status"] == "limit"
    graph["edges"] = [e for e in graph["edges"] if e["v"] != "clinic-door"]
    assert query(graph)["status"] == "no_connection"


def test_time_horizon_not_covered_is_unknown():
    graph = build_fixture()
    graph["valid_until"] = at("09:20")
    assert query(graph)["status"] == "possible"


def test_label_budget_does_not_claim_no_route():
    assert query(build_fixture(), max_labels=1)["status"] == "incomplete"


def test_pareto_labels_keep_longer_faster_feasible_route():
    graph = build_fixture()
    graph["edges"] = [e for e in graph["edges"] if e["id"] in {"west-north", "west-south", "north-clinic", "south-clinic"}]
    for edge in graph["edges"]:
        edge["preference_cost"] = edge["length_m"]
        if edge["id"] in {"west-north", "north-clinic"}:
            edge.update(length_m=50, duration_s=900, preference_cost=1)
        else:
            edge.update(length_m=100, duration_s=200, preference_cost=5)
    profile = {**graph["profiles"][0], "max_distance_m": 300, "max_duration_s": 500}
    result = query(graph, profile=profile)
    assert result["status"] == "confirmed"
    assert result["distance_m"] == 200
    assert result["duration_s"] == 400
    assert "south-clinic" in result["path"]


def test_merge_vertex_needs_nondominated_labels():
    graph = build_fixture()
    graph["edges"] = [e for e in graph["edges"] if e["id"] in {"west-north", "north-clinic"}]
    fast = deepcopy(graph["edges"][0])
    fast.update(id="parallel-fast", length_m=200, duration_s=100, preference_cost=10)
    graph["edges"][0].update(length_m=50, duration_s=900, preference_cost=1)
    graph["edges"][1].update(length_m=50, duration_s=200, preference_cost=1)
    graph["edges"].append(fast)
    result = query(graph, profile={**graph["profiles"][0], "max_duration_s": 500, "max_distance_m": 300})
    assert result["status"] == "confirmed"
    assert result["path"] == ["parallel-fast", "north-clinic"]


def test_directional_slope_reverses_sign():
    graph = build_fixture()
    change(graph, "crossing-x", "slope_pct", 7)
    change(graph, "crossing-y", "slope_pct", 7)
    assert query(graph)["status"] == "barrier"  # uphill limit six
    graph["places"].append({"id": "west-home", "category": "home"})
    graph["entrances"].append({"id": "west-door", "node_id": "origin-west", "asset_id": "clinic-entrance", "place_id": "west-home"})
    result = query(graph, origin="clinic-door", destination="west-home")
    assert result["status"] == "confirmed"  # downhill limit eight


def test_observed_planned_end_never_reopens_without_observation():
    graph = build_fixture()
    graph["layer"] = "observed"
    for e in graph["evidence"] + graph["restrictions"]:
        e["layer"] = "observed"
    result = query(graph, departure=at("17:00"), restrictions=graph["restrictions"], layer="observed")
    assert result["status"] == "barrier"
    for work in graph["restrictions"]:
        work["verified_open_at"] = at("16:30")
    assert query(graph, departure=at("17:00"), restrictions=graph["restrictions"], layer="observed")["status"] == "possible"
    for asset in ("crossing-x", "crossing-y"):
        graph["evidence"].append({"id": "fresh-opening-"+asset, "asset_id": asset, "feature": "open", "value": True, "observed_at": at("16:30"), "valid_from": at("16:30"), "valid_until": at("18:00"), "layer": "observed", "status": "confirmed"})
    assert query(graph, departure=at("17:00"), restrictions=graph["restrictions"], layer="observed")["status"] == "confirmed"
    assert query(graph, departure=at("18:00"), restrictions=graph["restrictions"], layer="observed")["status"] == "possible"


def test_layer_mismatch_rejected():
    with pytest.raises(ValueError):
        query(build_fixture(), layer="observed")


def test_shared_elevator_failure_removes_both_apparent_paths():
    graph = elevator_fixture()
    result = failure_analysis(graph)
    shared = next(f for f in result["failures"] if f.get("failure_group_id") == "shared-elevator")
    assert shared["lost_relation_hours"] == 25
    assert len(shared["affected_relations"]) == 2


def test_rebinding_split_keeps_closure_and_ambiguous_import_blocks_publication():
    old = build_fixture()
    new = deepcopy(old)
    new["version"] = "fixture-v2"
    for edge in new["edges"]:
        edge["source_edge_ids"] = [edge["id"]]
        edge["id"] += "-new"
    result = rebind_assets(old, new, old["restrictions"])
    assert result["publication_allowed"]
    assert next(b for b in result["bindings"] if b["asset_id"] == "crossing-x")["edge_ids"]
    new["edges"] = [e for e in new["edges"] if e["asset_id"] != "crossing-x"]
    result = rebind_assets(old, new, old["restrictions"])
    assert not result["publication_allowed"]
    assert result["previous_version_retained"]


def test_topology_wrong_level_not_implicit_connection():
    graph = build_fixture()
    graph["nodes"][2]["level"] = 1
    assert not validate_graph(graph)["valid"]


def test_edge_only_closure_rebound_to_new_version_stays_effective():
    graph = build_fixture()
    restrictions = [{"id": "edge-only", "edge_ids": ["north-clinic", "south-clinic"], "start": at("08:00"), "end": at("16:00"),
                     "kind": "closure", "status": "confirmed", "layer": "fixture"}]
    new = deepcopy(graph)
    new["version"] = "fixture-v2"
    for edge in new["edges"]:
        edge["id"] += "-new"
    binding = rebind_assets(graph, new, restrictions)
    assert binding["publication_allowed"]
    assert query(new, restrictions=binding["restrictions"])["status"] == "barrier"


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        query(build_fixture(), departure="2026-10-03T09:00:00")
