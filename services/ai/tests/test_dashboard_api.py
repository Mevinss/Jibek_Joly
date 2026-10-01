"""The dashboard uses the same canonical snapshot across each real API result."""
from fastapi.testclient import TestClient

from services.ai.main import app


client = TestClient(app)


def test_short_route_planner_evaluation_and_eta_are_connected():
    state = client.get("/api/dashboard/short/state").json()
    plan = client.get("/api/dashboard/short/plan").json()
    comparison = client.get("/api/dashboard/short/compare").json()
    arrivals = client.get("/api/dashboard/short/stations/BOR/arrivals").json()

    assert len(state["trains"]) == 3
    assert plan["dataset_version"] == state["dataset_version"]
    assert plan["snapshot_version"] == state["snapshot_version"]
    assert plan["valid"] and plan["fully_validated"]
    assert comparison["comparable"] and comparison["cohort_size"] == 3
    assert comparison["fifo"]["dataset_version"] == state["dataset_version"]
    assert {row["train_id"] for row in arrivals["arrivals"]} == {row["train_id"] for row in state["trains"]}


def test_full_timetable_conflict_is_not_reported_as_a_valid_plan_or_benefit():
    state = client.get("/api/v2/state").json()
    plan = client.post("/api/dashboard/plan", json={}).json()
    comparison = client.get("/api/dashboard/compare").json()

    assert len(state["trains"]) == comparison["cohort_size"] == 28
    assert any(block["state_conflict"] for block in state["blocks"])
    assert plan["solver_status"] == "INVALID_INPUT"
    assert not plan["valid"]
    assert not comparison["comparable"]
    assert comparison["improvement_vs_fifo_pct"] is None


def test_short_what_if_uses_snapshot_identity_and_does_not_mutate_it():
    before = client.get("/api/dashboard/short/state").json()
    request = {"incident_type": "TRAIN_DELAY", "resource_id": before["trains"][0]["train_id"],
               "duration_min": 2, "scenario_id": before["scenario_id"], "seed": before["seed"],
               "snapshot_version": before["snapshot_version"],
               "start_time": before["virtual_time"][:16]}
    result = client.post("/api/dashboard/short/what-if", json=request)
    assert result.status_code == 200
    assert result.json()["original_snapshot_unchanged"] is True
    assert client.get("/api/dashboard/short/state").json() == before
    assert client.post("/api/dashboard/short/what-if", json={**request, "snapshot_version": -1}).status_code == 409
