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
                    assert client.post("/api/scenarios/SCN-ALL/start?speed=60").status_code == 200
                    second = websocket.receive_json()
                    assert second["sequence"] > first["sequence"]
                    assert second["virtual_time"] > first["virtual_time"]
                with client.websocket_connect(f"/ws/state?last_sequence={first['sequence']}") as websocket:
                    replayed = websocket.receive_json()
                    assert replayed["sequence"] == second["sequence"]
                    assert replayed["event_id"] == second["event_id"]
                assert client.post("/api/scenarios/SCN-ALL/pause").status_code == 200
                current = client.get("/api/state").json()
                replay = client.get("/api/replay", params={"scenario_id": "SCN-ALL", "at": current["virtual_time"]}).json()
                assert replay == current
                assert client.get("/metrics").json()["events_received"] >= 1
        finally:
            os.environ.pop("TURKISIB_DB", None)
