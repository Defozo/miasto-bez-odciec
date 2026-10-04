from copy import deepcopy

import pytest
from domain.graph import build_fixture, evaluate, route, validate_graph
from domain.graph.fixture import at
from domain.graph.models import instant
from domain.graph.routing import object_state


def reopened_observed(scope=None):
    graph = build_fixture()
    graph["layer"] = "observed"
    for evidence in graph["evidence"]:
        evidence["layer"] = "observed"
    for work in graph["restrictions"]:
        work.update(layer="observed", verified_open_at=at("16:30"))
        work["invalidated_features"] = scope
        fresh_feature(graph, work["asset_id"], "open")
    return graph


def fresh_feature(graph, asset, feature):
    previous = next(item for item in graph["evidence"] if item["asset_id"] == asset and item["feature"] == feature)
    graph["evidence"].append({**previous, "id": f"new-{asset}-{feature}", "observed_at": at("16:30"), "valid_from": at("16:30"), "valid_until": at("20:00")})


def observed_route(graph):
    return route(graph, "wheelchair", "origin-west", "clinic", at("17:00"), layer="observed")


def test_unknown_work_scope_and_new_opening_do_not_revalidate_geometry():
    graph = reopened_observed()
    result = observed_route(graph)
    assert result["status"] == "possible"
    assert {issue["feature"] for issue in result["unknowns"]} >= {"width_m", "surface", "slope_pct", "steps", "kerb_cm"}
    assert all(issue["required_observed_after"] == at("16:30") for issue in result["unknowns"])
    for asset in ("crossing-x", "crossing-y"):
        fresh_feature(graph, asset, "width_m")
    still_unknown = observed_route(graph)
    assert still_unknown["status"] == "possible"
    assert {issue["feature"] for issue in still_unknown["unknowns"]} >= {"surface", "slope_pct"}
    for asset in ("crossing-x", "crossing-y"):
        for feature in ("surface", "slope_pct", "steps", "kerb_cm"):
            fresh_feature(graph, asset, feature)
    assert observed_route(graph)["status"] == "confirmed"


def test_declared_scope_invalidates_only_targeted_features_and_always_open():
    graph = reopened_observed(["width_m"])
    edge = next(edge for edge in graph["edges"] if edge["id"] == "north-clinic")
    args = (graph, "crossing-x", edge, graph["profiles"][0], instant(at("17:00")), instant(at("17:30")), graph["restrictions"], "observed")
    state = object_state(*args)
    assert {reason["feature"] for reason in state["reasons"]} == {"width_m"}
    fresh_feature(graph, "crossing-x", "width_m")
    state = object_state(*args)
    assert state["state"] == "confirmed"
    assert any(evidence["id"] == "e-crossing-x-surface" for evidence in state["evidence"])
    graph["evidence"] = [evidence for evidence in graph["evidence"] if evidence["id"] != "new-crossing-x-open"]
    assert any(reason["feature"] == "open" for reason in object_state(*args)["reasons"])


def test_invalid_scope_is_rejected_for_publication_and_conservative_for_routing():
    graph = reopened_observed(["unknown-feature"])
    assert not validate_graph(graph)["valid"]
    assert observed_route(graph)["status"] == "possible"


@pytest.mark.parametrize("origin", ["origin-west", "origin-east", "south"])
def test_reverse_category_matches_forward_targets_with_directed_costs(origin):
    graph = build_fixture()
    graph["places"].append({"id": "clinic2", "category": "healthcare"})
    graph["entrances"].append({"id": "clinic2-door", "place_id": "clinic2", "node_id": "north", "asset_id": "clinic-entrance"})
    for edge in graph["edges"]:
        edge["preference_cost"] = edge["length_m"]*(7 if edge["id"].endswith("-reverse") else 1)
    options = [route(graph, "wheelchair", origin, target, at("09:00"), restrictions=[]) for target in ("clinic", "clinic2")]
    expected = min(options, key=lambda result: result["preference_cost"])
    actual = route(graph, "wheelchair", origin, {"category": "healthcare"}, at("09:00"), restrictions=[])
    assert actual["search_method"] == "reverse_multi_source_pareto"
    assert actual["status"] == expected["status"] == "confirmed"
    assert (actual["preference_cost"], actual["distance_m"], actual["duration_s"]) == (expected["preference_cost"], expected["distance_m"], expected["duration_s"])
    assert actual["entrance"]["id"] == expected["entrance"]["id"]
    assert actual["path"] == expected["path"]


def test_reverse_category_preserves_pareto_suffixes_and_both_limits():
    graph = build_fixture()
    graph["edges"] = [edge for edge in graph["edges"] if edge["id"] in {"west-north", "north-clinic"}]
    graph["edges"][0].update(length_m=50, duration_s=200, preference_cost=1)
    graph["edges"][1].update(length_m=50, duration_s=400, preference_cost=1)
    fast = {**deepcopy(graph["edges"][1]), "id": "fast-suffix", "length_m": 200, "duration_s": 100, "preference_cost": 10}
    graph["edges"].append(fast)
    profile = {**graph["profiles"][0], "max_distance_m": 300, "max_duration_s": 500}
    request = {"origin": "origin-west", "destination": {"category": "healthcare"}, "departure": at("09:00"), "restrictions": [], "profile": profile}
    result = route(graph, request)
    assert result["status"] == "confirmed" and result["path"] == ["west-north", "fast-suffix"]
    assert (result["distance_m"], result["duration_s"]) == (250, 300)
    assert route(graph, {**request, "profile": {**profile, "max_distance_m": 200}})["status"] == "limit"
    assert route(graph, {**request, "profile": {**profile, "max_duration_s": 250}})["status"] == "limit"
    assert route(graph, {**request, "max_labels": 1})["status"] == "incomplete"


def test_reverse_category_keeps_original_slope_direction_and_entrance_status():
    graph = build_fixture()
    for evidence in graph["evidence"]:
        if evidence["asset_id"] in {"crossing-x", "crossing-y"} and evidence["feature"] == "slope_pct":
            evidence["value"] = 7
    uphill = route(graph, "wheelchair", "origin-west", {"category": "healthcare"}, at("09:00"), restrictions=[])
    assert uphill["status"] == "barrier"
    graph["places"].append({"id": "home", "category": "home"})
    graph["entrances"].append({"id": "home-door", "place_id": "home", "node_id": "origin-west", "asset_id": "clinic-entrance"})
    downhill = route(graph, "wheelchair", "clinic-door", {"category": "home"}, at("09:00"), restrictions=[])
    assert downhill["status"] == "confirmed"
    assert all(edge.endswith("-reverse") for edge in downhill["path"])
    for evidence in graph["evidence"]:
        if evidence["asset_id"] == "clinic-entrance" and evidence["feature"] == "open":
            evidence["value"] = False
    assert route(graph, "wheelchair", "clinic-door", {"category": "home"}, at("09:00"), restrictions=[])["status"] == "barrier"


def test_category_analysis_reuses_reverse_search_across_origins(monkeypatch):
    import domain.graph.routing as routing
    calls = []
    original = routing.reverse_category_search

    def counted(*args, **kwargs):
        calls.append(args[1])
        return original(*args, **kwargs)

    monkeypatch.setattr(routing, "reverse_category_search", counted)
    result = evaluate(build_fixture(), {"restrictions": [], "variants": [], "destinations": [{"category": "healthcare"}]})
    assert result["baseline"]["available_relation_hours"] == 25
    # One full-window and one instantaneous traversal per interval serve both
    # origins; the departure horizon also includes its own tau-shifted boundary.
    assert len(calls) == 2*(len(result["boundaries"])-1)
