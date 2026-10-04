import pytest
from domain.graph import build_fixture, route
from domain.graph.fixture import at


@pytest.mark.parametrize("uphill,downhill,outward,returning", [(None, 8, "confirmed", "barrier"), (6, None, "barrier", "confirmed")])
def test_optional_null_directional_limit_is_unbounded(uphill, downhill, outward, returning):
    graph = build_fixture()
    for evidence in graph["evidence"]:
        if evidence["asset_id"] in {"crossing-x", "crossing-y"} and evidence["feature"] == "slope_pct":
            evidence["value"] = 12
    graph["places"].append({"id": "home", "category": "home"})
    graph["entrances"].append({"id": "home-door", "node_id": "origin-west", "place_id": "home", "asset_id": "clinic-entrance"})
    profile = {**graph["profiles"][0], "max_uphill_pct": uphill, "max_downhill_pct": downhill}
    assert route(graph, profile, "origin-west", "clinic", at("09:00"), restrictions=[])["status"] == outward
    assert route(graph, profile, "clinic-door", {"category": "home"}, at("09:00"), restrictions=[])["status"] == returning
