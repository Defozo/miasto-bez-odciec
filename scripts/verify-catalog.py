"""Exercise the live HTTP queue and worker's native CP-SAT catalog search.

Run with the real credential injected by psst, for example:
psst --global SMART_CITY_OPERATOR_PASSWORD -- .venv/Scripts/python.exe scripts/verify-catalog.py
The scenario remains available for inspection. No credential or session is saved.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import uuid

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8087")
    parser.add_argument("--output", default="artifacts/catalog-live.json")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    password = os.environ.get("SMART_CITY_OPERATOR_PASSWORD")
    if not password:
        raise SystemExit("Inject SMART_CITY_OPERATOR_PASSWORD with psst before running this verification.")
    started = time.monotonic()
    checks = []
    report = {"success": False, "base_url": args.base, "data_layer": "fixture", "checks": checks,
              "records": {}, "public_network_verified": False}

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    try:
        with httpx.Client(base_url=args.base, timeout=40) as client:
            ready = client.get("/health/ready")
            check("api_and_worker_ready", ready.status_code == 200 and ready.json().get("worker", {}).get("status") == "active")
            login = client.post("/api/v1/auth/login", json={"username": "operator", "password": password})
            check("real_operator_login", login.status_code == 200 and login.json().get("user", {}).get("role") == "operator")
            csrf = login.json()["csrf_token"]

            def get(path):
                response = client.get("/api/v1" + path)
                check("get_" + path.split("?")[0] + "_ok", response.status_code == 200)
                return response.json()

            def post(path, body, expected):
                response = client.post("/api/v1" + path, json=body,
                                       headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid.uuid4())})
                # Do not copy arbitrary response bodies into the artifact or log.
                check("post_" + path + "_http_" + str(expected), response.status_code == expected)
                return response.json()

            bootstrap = get("/bootstrap?layer=fixture")
            graph = bootstrap["graph"]
            check("synthetic_fixture_graph", graph["layer"] == "fixture" and graph.get("coverage", {}).get("status") == "synthetic")
            unchanged = deepcopy(graph.get("works") or graph["restrictions"])
            check("original_work_catalog", {work["id"] for work in unchanged} == {"X", "Y"})
            safe = deepcopy(unchanged)
            next(work for work in safe if work["id"] == "Y").update(
                start="2026-10-03T14:30:00+02:00", end="2026-10-03T20:30:00+02:00")
            versions = get("/versions?layer=fixture")
            request = {"catalog": [{"id": "schedules", "options": [
                {"id": "unchanged", "name": "Obecny harmonogram", "works": unchanged},
                {"id": "safe", "name": "Y po 30 minutach wspólnej drożności", "works": safe},
            ]}], "solver": "cp_sat", "time_limit_s": 60, "horizon": graph["horizon"],
                "origins": ["origin-west", "origin-east"], "profiles": ["wheelchair"], "destinations": ["clinic"]}
            scenario = post("/scenarios", {"name": "Test odbiorowy: rzeczywisty worker CP-SAT", "layer": "fixture",
                            "request": request, "assumptions": ["Dane syntetyczne. Kontrola katalogu nie publikuje robót ani otwarcia."]}, 201)
            report["records"]["scenario_id"] = scenario["id"]
            queued = post(f"/scenarios/{scenario['id']}/evaluate", {"expected_version": scenario["version"]}, 202)
            report["records"]["job_id"] = queued["job_id"]
            deadline = time.monotonic() + args.timeout
            job = {"status": "queued"}
            while time.monotonic() < deadline:
                response = client.get("/api/v1/jobs/" + queued["job_id"])
                if response.status_code != 200:
                    raise AssertionError("job_poll_http_200")
                job = response.json()
                if job["status"] in {"completed", "failed", "stale"}:
                    break
                time.sleep(0.5)
            report["job_status"] = job["status"]
            report["job_attempts"] = job.get("attempts")
            check("durable_worker_completed", job["status"] == "completed")
            result = job["result"]
            search = result.get("search", {})
            check("native_cp_sat_used", search.get("engine") == "cp_sat")
            check("catalog_and_pool_optimum", result["solver_status"] == "OPTIMAL" and search.get("cp_sat_status") == "OPTIMAL"
                  and search.get("pool_optimality_proven") is True)
            check("nonempty_physical_path_pool", search.get("path_pool_count", 0) > 0)
            check("whole_travel_window_eligibility_tables", search.get("whole_window_tables", 0) > 0 and search.get("local_assignments_checked", 0) > 0)
            check("complete_pool_and_local_tables", search.get("path_pool_complete") is True and search.get("local_tables_complete") is True)
            check("explicit_optimality_scope", bool(search.get("optimality_scope")) and bool(result.get("scope")))
            check("full_graph_candidate_verification", search.get("full_graph_verification") is True and bool(result["variants"])
                  and all(variant.get("full_graph_verified") is True for variant in result["variants"]))
            selected = next((variant for variant in result["variants"] if variant["id"] == result["recommended_id"]), None)
            check("safe_schedule_selected", selected is not None and selected["id"] == "catalog-1")
            baseline = result["baseline"]["metrics"]
            check("baseline_unavailable_9_relation_hours", baseline["unavailable_relation_hours"] == 9)
            check("instantaneous_8_hours_separate", baseline["instantaneous_lost_relation_hours"] == 8)
            check("safe_schedule_recovers_9_relation_hours", selected["recovered_relation_hours"] == 9)
            check("critical_relations_remain_available", selected["critical_satisfied"] and selected["feasible"] and selected["complete"])
            check("scenario_evaluated", get("/scenarios/" + scenario["id"])["status"] == "evaluated")
            check("evaluation_did_not_publish_facts", get("/versions?layer=fixture") == versions)
            report.update({"success": True, "solver_status": result["solver_status"], "recommended_id": selected["id"],
                           "snapshot_versions": scenario["snapshot_versions"], "data_versions": versions,
                           "baseline_unavailable_relation_hours": baseline["unavailable_relation_hours"],
                           "instantaneous_lost_relation_hours": baseline["instantaneous_lost_relation_hours"],
                           "recovered_relation_hours": selected["recovered_relation_hours"], "critical_satisfied": selected["critical_satisfied"],
                           "full_graph_verified": selected["full_graph_verified"], "scope": result["scope"],
                           "search": {key: search[key] for key in (
                               "engine", "catalog_combinations", "time_limit_s", "path_pool_count", "path_pool_complete",
                               "local_tables_complete", "whole_window_tables", "local_assignments_checked", "cp_sat_status",
                               "pool_optimality_proven", "enumerated_candidates", "verified_candidates", "elapsed_s",
                               "full_graph_verification", "optimality_scope") if key in search}})
            serialized = json.dumps(report, ensure_ascii=False)
            check("artifact_excludes_credentials_and_sessions", password not in serialized and csrf not in serialized
                  and all(value not in serialized for value in client.cookies.values()))
    except Exception as exc:
        report["success"] = False
        # All assertions above are fixed check identifiers, never arbitrary server data.
        report["failure"] = str(exc) if isinstance(exc, AssertionError) else type(exc).__name__
        raise
    finally:
        report.update(completed_at=datetime.now(timezone.utc).isoformat(), duration_s=round(time.monotonic() - started, 3), passed=len(checks))
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
