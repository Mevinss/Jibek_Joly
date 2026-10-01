from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import app


def test_reconnect_and_replay_after_one_tick():
    with tempfile.TemporaryDirectory() as directory:
        os.environ["TURKISIB_DB"] = str(Path(directory) / "api.sqlite3")
        try:
            with TestClient(app) as client:
                with client.websocket_connect("/ws/state") as websocket:
                    first = websocket.receive_json()
                    assert first["type"] == "SNAPSHOT"
                    assert first["schema_version"] == 1
                    assert first["snapshot_version"] == first["payload"]["version"]
                    canonical = client.get("/api/v2/state").json()
                    assert canonical["schema_version"] == "2.0"
                    assert canonical["snapshot_version"] == first["snapshot_version"]
                    assert canonical["run_id"] == first["run_id"]
                    graph = client.get("/api/topology").json()
                    assert graph["schema_version"] == "1.0"
                    assert {b["block_id"] for b in graph["blocks"]} == {b["block_id"] for b in canonical["blocks"]}
                    assert client.post("/api/scenarios/SCN-ALL/start?speed=60").status_code == 200
                    second = websocket.receive_json()
                    assert second["sequence"] > first["sequence"]
                    assert second["snapshot_version"] > first["snapshot_version"]
                    assert second["virtual_time"] > first["virtual_time"]
                with client.websocket_connect(f"/ws/state?last_sequence={first['sequence']}") as websocket:
                    replayed = websocket.receive_json()
                    assert replayed["sequence"] == second["sequence"]
                    assert replayed["event_id"] == second["event_id"]
                assert client.post("/api/scenarios/SCN-ALL/pause").status_code == 200
                current = client.get("/api/state").json()
                replay = client.get("/api/replay", params={"scenario_id": "SCN-ALL", "at": current["virtual_time"]}).json()
                assert replay == current
                canonical_replay = client.get("/api/v2/replay", params={"scenario_id": "SCN-ALL", "at": current["virtual_time"]}).json()
                assert canonical_replay["snapshot_version"] == current["version"]
                assert canonical_replay["trains"][0]["progress"] == canonical_replay["trains"][0]["route_progress_0_1"]
                assert client.get("/metrics").json()["events_received"] >= 1
        finally:
            os.environ.pop("TURKISIB_DB", None)
