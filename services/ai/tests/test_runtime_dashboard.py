"""End-to-end contract for the stateful 28-train dashboard loop."""
from fastapi.testclient import TestClient

from services.ai.main import app


def test_runtime_incident_preview_apply_and_history_share_one_run(tmp_path, monkeypatch):
    monkeypatch.setenv("TURKISIB_DB", str(tmp_path / "runtime.sqlite3"))
    with TestClient(app) as client:
        first = client.get("/api/runtime/state").json()
        assert first["schema_version"] == "2.0"
        assert len(first["trains"]) == 28
        assert not any(block["state_conflict"] for block in first["blocks"])
        assert first["snapshot_id"] == f'{first["run_id"]}:{first["snapshot_version"]}'

        resource = first["trains"][0]["train_id"]
        created = client.post("/api/runtime/incidents", json={"type": "TRAIN_DELAY",
            "resource_id": resource, "duration_min": 5,
            "run_id": first["run_id"], "snapshot_version": first["snapshot_version"]})
        assert created.status_code == 200
        incident_state = created.json()["state"]
        assert incident_state["run_id"] == first["run_id"]
        assert incident_state["snapshot_version"] > first["snapshot_version"]
        assert incident_state["active_incidents"]

        analysis = client.get("/api/runtime/analysis").json()
        assert analysis["snapshot_id"] == incident_state["snapshot_id"]
        assert analysis["network_train_count"] == 28
        assert {row["id"] for row in analysis["options"]} >= {"A", "B"}
        assert analysis["planner"]["cp_sat"]["fully_validated"] is False

        identity = {"run_id": incident_state["run_id"],
                    "snapshot_version": incident_state["snapshot_version"]}
        preview = client.post("/api/runtime/preview", json=identity | {"option_id": "B", "horizon_minutes": 10})
        assert preview.status_code == 200
        assert preview.json()["applied"] is False
        assert preview.json()["horizon_seconds"] == 600
        assert preview.json()["baseline_metrics"]["total_delay_min"] is not None
        assert any(row["train_id"] == resource for row in preview.json()["train_impacts"])
        assert all("without_action_eta" in row and "with_action_eta" in row
                   for row in preview.json()["train_impacts"])
        assert preview.json()["current"]["snapshot_id"] == incident_state["snapshot_id"]
        assert client.get("/api/runtime/state").json()["snapshot_id"] == incident_state["snapshot_id"]

        applied = client.post("/api/runtime/apply", json=identity | {"option_id": "B"})
        assert applied.status_code == 200
        after = applied.json()["after"]
        assert after["run_id"] == first["run_id"]
        assert after["snapshot_version"] > incident_state["snapshot_version"]
        assert client.get("/api/runtime/health-index").json()["snapshot_id"] == after["snapshot_id"]
        assert client.get("/api/runtime/stations/AST/arrivals").json()["snapshot_id"] == after["snapshot_id"]
        assert client.post("/api/runtime/apply", json=identity | {"option_id": "B"}).status_code == 409
        history = client.get("/api/runtime/history").json()
        assert history["run_id"] == first["run_id"]
        assert {row["type"] for row in history["events"]} >= {"INCIDENT_CREATED", "DECISION_APPLIED"}
        replay = client.get("/api/runtime/replay", params={"at": incident_state["virtual_time"]}).json()
        assert replay["replay"] is True
        assert replay["state"]["run_id"] == first["run_id"]


def test_runtime_root_and_auxiliary_views_use_live_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("TURKISIB_DB", str(tmp_path / "runtime.sqlite3"))
    with TestClient(app) as client:
        assert 'id="runtime-decisions"' in client.get("/dispatch-dashboard.html").text
        assert client.get("/dashboard.mjs").headers["content-type"].startswith("application/javascript")
        assert client.get("/legacy").status_code == 200
        state = client.get("/api/runtime/state").json()
        topology = client.get("/api/runtime/topology").json()
        assert {row["block_id"] for row in state["blocks"]} == {row["block_id"] for row in topology["blocks"]}
        plan = client.get("/api/runtime/plan").json()
        assert plan["run_id"] == state["run_id"]
        assert plan["snapshot_version"] == state["snapshot_version"]
        quality = client.get("/api/runtime/health-index").json()
        assert quality["snapshot_id"] == state["snapshot_id"]
        assert quality["method"].startswith("DEMO_HEALTH")
        arrivals = client.get("/api/runtime/stations/AST/arrivals").json()
        assert arrivals["snapshot_id"] == state["snapshot_id"]
        speed = client.get(f'/api/runtime/trains/{state["trains"][0]["train_id"]}/speed-profile').json()
        assert speed["snapshot_id"] == state["snapshot_id"]
        assert speed["status"] == "LIMIT_ONLY_ILLUSTRATION"
        assert speed["energy_proxy_units"] is None
        assert client.post("/api/runtime/control", json={"running": False, "speed": 10}).status_code == 200
        reset = client.post("/api/runtime/reset").json()
        assert reset["run_id"] != state["run_id"]
        assert reset["snapshot_version"] == 0
