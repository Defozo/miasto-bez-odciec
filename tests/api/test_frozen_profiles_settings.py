from copy import deepcopy
import json

import pytest
from tests.api.test_flow import client, login, post


@pytest.mark.parametrize("original_value", ["absent", None])
def test_effect_does_not_inherit_new_optional_profile_requirement(client, monkeypatch, original_value):
    from services.api import planning
    from services.api.db import Entity
    login(client)
    old = client.get("/api/v1/bootstrap").json()["graph"]
    old["restrictions"], old["works"] = [], []
    if original_value == "absent":
        old["profiles"][0].pop("max_kerb_cm")
    else:
        old["profiles"][0]["max_kerb_cm"] = None
    for evidence in old["evidence"]:
        if evidence["asset_id"] in {"crossing-x", "crossing-y"} and evidence["feature"] == "kerb_cm":
            evidence["value"] = 5
    monkeypatch.setattr(planning, "graph_snapshot", lambda db, layer: old)
    created = post(client, "/scenarios", {"name": "Profil bez dodatkowego wymogu krawężnika"}, expected=201)
    current = deepcopy(old)
    current["profiles"][0]["max_kerb_cm"] = 2
    current["data_version"] += 1
    monkeypatch.setattr(planning, "graph_snapshot", lambda db, layer: current)
    with client.test_db() as db:
        effect = planning.compute_effect(db, db.get(Entity, created["id"]))
    assert effect["before"]["available_relation_hours"] == effect["after"]["available_relation_hours"] == 25
    assert current["profiles"][0]["max_kerb_cm"] == 2


def test_worker_reads_analysis_setting_and_request_takes_precedence(client, monkeypatch, tmp_path):
    import domain.graph as graph_module
    from services.worker.main import process_one
    configuration = tmp_path / "settings.json"
    configuration.write_text(json.dumps({"analysis_timeout_seconds": 7}), encoding="utf-8")
    monkeypatch.setenv("SMART_CITY_SETTINGS", str(configuration))
    seen = []
    evaluate = graph_module.evaluate

    def capture(graph, request):
        seen.append(request["time_limit_s"])
        return evaluate(graph, request)

    monkeypatch.setattr(graph_module, "evaluate", capture)
    login(client)
    for request in ({}, {"time_limit_s": 3}):
        scenario = post(client, "/scenarios", {"name": "Limit z konfiguracji albo żądania", "request": request}, expected=201)
        queued = post(client, f"/scenarios/{scenario['id']}/evaluate", {"expected_version": 1}, expected=202)
        assert process_one("configured-worker")
        assert client.get(f"/api/v1/jobs/{queued['job_id']}").json()["status"] == "completed"
    assert seen == [7, 3]


def test_public_analysis_uses_setting_with_request_override_and_public_cap(client, monkeypatch, tmp_path):
    import domain.graph as graph_module
    configuration = tmp_path / "settings.json"
    configuration.write_text(json.dumps({"analysis_timeout_seconds": 7}), encoding="utf-8")
    monkeypatch.setenv("SMART_CITY_SETTINGS", str(configuration))
    seen = []
    evaluate = graph_module.evaluate

    def capture(graph, request):
        seen.append(request["time_limit_s"])
        return evaluate(graph, request)

    monkeypatch.setattr(graph_module, "evaluate", capture)
    for request in ({}, {"time_limit_s": 3}, {"time_limit_s": 50}):
        response = client.post("/api/v1/analysis/evaluate", json=request)
        assert response.status_code == 200, response.text
    assert client.get("/api/v1/demo/evaluation").status_code == 200
    assert seen == [7, 3, 10, 7]


@pytest.mark.parametrize("analysis_request,expected", [({}, 7), ({"time_limit_s": 3}, 3)])
def test_effect_uses_same_configured_or_requested_budget_for_both_sides(client, monkeypatch, tmp_path, analysis_request, expected):
    import domain.graph as graph_module
    from services.api import planning
    from services.api.db import Entity
    configuration = tmp_path / "settings.json"
    configuration.write_text(json.dumps({"analysis_timeout_seconds": 7}), encoding="utf-8")
    monkeypatch.setenv("SMART_CITY_SETTINGS", str(configuration))
    seen = []
    evaluate = graph_module.evaluate

    def capture(graph, calculation):
        seen.append(calculation["time_limit_s"])
        return evaluate(graph, calculation)

    monkeypatch.setattr(graph_module, "evaluate", capture)
    login(client)
    scenario = post(client, "/scenarios", {"name": "Jednakowy budżet porównania efektu", "request": analysis_request}, expected=201)
    with client.test_db() as db:
        effect = planning.compute_effect(db, db.get(Entity, scenario["id"]))
    assert effect["before"]["available_relation_hours"] == effect["after"]["available_relation_hours"]
    assert seen == [expected, expected]
