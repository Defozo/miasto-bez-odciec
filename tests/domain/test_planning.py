from copy import deepcopy
import pytest
from domain.graph import build_fixture, evaluate, optimize_catalog, verification_impact
from domain.graph.fixture import at
from domain.graph.models import content_hash


def test_exact_demonstration_nine_hours_eight_instantaneous():
    result = evaluate(build_fixture())
    assert result["baseline"]["unavailable_relation_hours"] == 9
    assert result["baseline"]["instantaneous_lost_relation_hours"] == 8
    assert result["baseline"]["total_relation_hours"] == 25
    safe = next(v for v in result["variants"] if v["id"] == "safe")
    assert safe["recovered_relation_hours"] == 9
    assert safe["critical_satisfied"] and safe["success"]
    assert safe["feasibility"]["all_works_completed"]
    assert safe["cost"] is None
    assert safe["feasibility"]["budget_status"] == "unknown"


@pytest.mark.parametrize("work_id", ["X", "Y"])
def test_each_work_individually_preserves_access(work_id):
    graph = build_fixture()
    request = {"restrictions": [w for w in graph["works"] if w["id"] == work_id], "variants": []}
    assert evaluate(graph, request)["baseline"]["available_relation_hours"] == 25


def test_touching_schedules_fail_whole_window_critical_requirement():
    result = evaluate(build_fixture())
    touching = next(v for v in result["variants"] if v["id"] == "touching")
    assert touching["instantaneous_lost_relation_hours"] == 0
    assert touching["unavailable_relation_hours"] == 1
    assert not touching["critical_satisfied"]
    assert not touching["success"]


def test_delayed_reopening_exposes_new_loss_not_hidden_net_gain():
    result = evaluate(build_fixture())
    delayed = next(v for v in result["variants"] if v["id"] == "delayed")
    assert delayed["lost_relation_hours"] == 0.5
    assert delayed["net_relation_hours"] == 8.5
    assert not delayed["critical_satisfied"]


def test_fixed_horizon_rejects_moving_work_outside_plot():
    graph = build_fixture()
    schedule = deepcopy(graph["works"])
    schedule[1].update(start=at("18:00"), end="2026-10-04T00:00:00+02:00")
    result = evaluate(graph, {"variants": [{"id": "outside", "works": schedule}]})
    assert not result["variants"][0]["feasible"]
    assert result["recommended_id"] is None


def test_work_cannot_be_dropped_or_shortened():
    graph = build_fixture()
    short = deepcopy(graph["works"])
    short[1]["end"] = at("15:00")
    result = evaluate(graph, {"variants": [{"id": "missing", "works": graph["works"][:1]}, {"id": "short", "works": short}]})
    assert all(not v["feasible"] for v in result["variants"])


def test_resource_capacity_and_dependency_validated():
    graph = build_fixture()
    for work in graph["works"]:
        work["resource"] = "single-crew"
    graph["works"][1]["depends_on"] = [{"id": "X", "lag_s": 1800}]
    result = evaluate(graph, {"variants": [{"id": "overlap", "works": graph["works"]}]})
    codes = {e["code"] for e in result["variants"][0]["feasibility"]["errors"]}
    assert "resource_capacity" in codes
    assert "dependency_violation" in codes


def test_joint_repairs_not_sum_of_individual_benefits():
    graph = build_fixture()
    graph["works"] = []
    graph["restrictions"] = []
    graph["edges"] = [e for e in graph["edges"] if e["id"] in {"west-north", "north-clinic"}]
    for e in graph["evidence"]:
        if e["asset_id"] in {"west-north", "crossing-x"} and e["feature"] == "width_m":
            e["value"] = 0.5
    actions = [{"id": aid, "kind": "repair", "asset_id": aid, "feature": "width_m", "value": 1.2, "cost": 5} for aid in ["west-north", "crossing-x"]]
    result = evaluate(graph, {"origins": ["origin-west"], "variants": [
        {"id": "first", "actions": actions[:1]}, {"id": "second", "actions": actions[1:]}, {"id": "both", "actions": actions}]})
    assert [v["available_relation_hours"] for v in result["variants"]] == [0, 0, 12.5]
    assert result["variants"][2]["cost"] == 10


def test_category_counted_once_and_exact_target_separate():
    graph = build_fixture()
    graph["places"].append({"id": "clinic2", "category": "healthcare"})
    graph["entrances"].append({"id": "clinic2-main", "place_id": "clinic2", "node_id": "clinic-door", "asset_id": "clinic-entrance"})
    result = evaluate(graph, {"restrictions": [], "variants": [], "destinations": [{"category": "healthcare"}, {"category": "healthcare"}]})
    assert result["baseline"]["relation_count"] == 2
    assert result["baseline"]["available_relation_hours"] == 25
    assert set(result["baseline"]["by_kind"]) == {"category"}


def test_missing_cost_does_not_claim_budget_compliance():
    result = evaluate(build_fixture(), {"budget": 100})
    assert all(v["feasibility"]["budget_status"] == "unknown" for v in result["variants"])


def test_snapshot_reproducible_and_no_input_mutation():
    graph = build_fixture()
    before = content_hash(graph)
    first, second = evaluate(graph), evaluate(graph)
    assert content_hash(graph) == before
    assert first["snapshot"] == second["snapshot"]


def test_incomplete_is_not_confirmed_loss():
    result = evaluate(build_fixture(), {"max_labels": 1, "variants": []})
    assert result["baseline"]["incomplete_relation_hours"] > 0
    assert result["baseline"]["available_relation_hours"] == 0
    assert result["baseline"]["unavailable_relation_hours"] == 0


def test_measurement_only_changes_target_feature():
    graph = build_fixture()
    graph["evidence"] = [e for e in graph["evidence"] if not (e["asset_id"] in {"crossing-x", "crossing-y"} and e["feature"] in {"width_m", "surface"})]
    result = verification_impact(graph, {"restrictions": [], "variants": []})
    assert result["measurements"]
    assert all(m["potential_relation_hours"] == 0 for m in result["measurements"])
    assert all(m["knowledge_change_only"] for m in result["measurements"])


def test_finite_catalog_cp_sat_matches_exhaustive():
    # Native solver module initialization is outside the requested solve budget.
    # It can include the first Windows binary integrity scan on a fresh install.
    pytest.importorskip("ortools.sat.python.cp_model")
    graph = build_fixture()
    options = [{"id": "baseline", "works": deepcopy(graph["works"])}]
    safe = deepcopy(graph["works"])
    safe[1].update(start=at("14:30"), end=at("20:30"))
    options.append({"id": "safe", "works": safe})
    request = {"catalog": [{"id": "schedules", "options": options}], "time_limit_s": 30}
    enumeration = optimize_catalog(graph, request)
    cp_sat = optimize_catalog(graph, {**request, "solver": "cp_sat"})
    assert enumeration["solver_status"] == cp_sat["solver_status"] == "OPTIMAL", cp_sat.get("search")
    assert enumeration["recommended_id"] == cp_sat["recommended_id"]
    assert all(v["full_graph_verified"] for v in cp_sat["variants"])


def test_cold_solver_import_has_separate_time_budget(monkeypatch):
    cp_model = pytest.importorskip("ortools.sat.python.cp_model")
    from time import monotonic as real_clock
    import domain.graph.catalog as catalog
    import domain.graph.pathpool as pathpool
    import domain.graph.planning as planning
    import domain.graph.routing as routing
    offset = [0.0]
    for module in (catalog, pathpool, planning, routing):
        monkeypatch.setattr(module, "monotonic", lambda: real_clock()+offset[0])

    def delayed_import():
        offset[0] += 120
        return cp_model

    monkeypatch.setattr(catalog, "load_cp_model", delayed_import)
    graph = build_fixture()
    safe = deepcopy(graph["works"])
    safe[1].update(start=at("14:30"), end=at("20:30"))
    result = optimize_catalog(graph, {"catalog": [{"options": [
        {"id": "baseline", "works": graph["works"]}, {"id": "safe", "works": safe},
    ]}], "solver": "cp_sat", "time_limit_s": 30})
    assert result["solver_status"] == "OPTIMAL", result.get("search")
    assert result["recommended_id"] == "catalog-1"
    assert result["variants"][0]["recovered_relation_hours"] == 9
    assert result["search"]["solver_setup_s"] >= 120
    assert result["search"]["elapsed_s"] >= 120
    assert result["search"]["solve_elapsed_s"] < 30


def test_missing_optional_solver_preserves_manual_evaluation(monkeypatch):
    import domain.graph.catalog as catalog

    def missing_adapter():
        raise ImportError("Optional adapter absent")

    monkeypatch.setattr(catalog, "load_cp_model", missing_adapter)
    graph = build_fixture()
    result = optimize_catalog(graph, {"catalog": [{"options": [{"works": graph["works"]}]}], "solver": "cp_sat"})
    assert result["solver_status"] == "UNKNOWN"
    assert result["reason"] == "cp_sat_adapter_unavailable"
    assert result["search"]["engine"] == "cp_sat"
    assert evaluate(graph)["recommended_id"] == "safe"


def test_catalog_limit_never_claims_optimum():
    graph = build_fixture()
    result = optimize_catalog(graph, {"catalog": [{"options": [{"id": str(i)} for i in range(3)]}], "max_variants": 1})
    assert result["solver_status"] == "FEASIBLE"
    assert not result["complete"]


def test_timeout_is_unknown_and_never_reports_optimal():
    result = evaluate(build_fixture(), {"time_limit_s": 0})
    assert result["solver_status"] == "UNKNOWN"
    assert not result["complete"]
    assert result["baseline"]["incomplete_relation_hours"] == 25
    assert result["recommended_id"] is None


def test_cp_sat_retains_path_requiring_two_repairs():
    pytest.importorskip("ortools.sat.python.cp_model")
    graph = build_fixture()
    graph["works"] = []
    graph["restrictions"] = []
    graph["edges"] = [e for e in graph["edges"] if e["id"] in {"west-north", "north-clinic"}]
    assets = ["west-north", "crossing-x"]
    for evidence in graph["evidence"]:
        if evidence["asset_id"] in assets and evidence["feature"] == "width_m":
            evidence["value"] = 0.5
    catalog = [{"id": asset, "options": [
        {"id": "no-change", "cost": 0},
        {"id": "repair", "actions": [{"id": asset, "kind": "repair", "asset_id": asset, "feature": "width_m", "value": 1.2, "cost": 5}]}]} for asset in assets]
    result = optimize_catalog(graph, {"origins": ["origin-west"], "catalog": catalog, "solver": "cp_sat", "time_limit_s": 30})
    assert result["solver_status"] == "OPTIMAL", result.get("search")
    assert result["recommended_id"] == "catalog-1-1"
    assert result["variants"][0]["available_relation_hours"] == 12.5
    assert result["search"]["path_pool_count"] == 1
    assert result["search"]["whole_window_tables"] > 0
    assert result["search"]["full_graph_verification"]


def test_cp_sat_pool_scope_remains_explicit_when_paths_are_bounded():
    pytest.importorskip("ortools.sat.python.cp_model")
    graph = build_fixture()
    result = optimize_catalog(graph, {"catalog": [{"options": [{"id": "unchanged", "works": graph["works"]}]}], "solver": "cp_sat", "max_paths_per_relation": 1, "time_limit_s": 30})
    assert not result["search"]["path_pool_complete"]
    assert "puli" in result["scope"]
    assert all(v["full_graph_verified"] for v in result["variants"])


def test_schedule_cannot_move_work_to_another_asset_or_drop_other_fault():
    graph = build_fixture()
    moved = deepcopy(graph["works"])
    moved[0]["asset_id"] = "imaginary-asset"
    result = evaluate(graph, {"variants": [{"id": "moved", "works": moved}]})
    assert not result["variants"][0]["feasible"]
    assert "physical_scope_changed" in {item["code"] for item in result["variants"][0]["feasibility"]["errors"]}
    graph["restrictions"].append({"id": "independent-warning", "asset_id": "crossing-y", "kind": "warning", "status": "unverified", "start": at("08:00"), "end": at("09:00")})
    result = evaluate(graph, {"variants": [{"id": "lost-warning", "works": graph["works"]}]})
    assert not result["variants"][0]["feasible"]


def test_cp_sat_incomplete_local_state_table_never_claims_optimal():
    pytest.importorskip("ortools.sat.python.cp_model")
    graph = build_fixture()
    result = optimize_catalog(graph, {"catalog": [{"options": [{"id": "one", "works": graph["works"]}, {"id": "two", "works": graph["works"]}]}], "solver": "cp_sat", "max_local_assignments": 1, "time_limit_s": 30})
    assert not result["search"]["local_tables_complete"]
    assert result["solver_status"] in {"FEASIBLE", "UNKNOWN"}
    assert not result["complete"]
