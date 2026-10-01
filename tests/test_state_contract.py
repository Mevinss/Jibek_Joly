"""Contract regressions for Person 1's canonical state boundary."""
from __future__ import annotations

import math
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from backend.planner.cp_sat import build_snapshot_block_operations
from backend.simulator import Simulator
from backend.simulator.state_contract import canonical_from_backend_snapshot, topology
from backend.store import EventStore
from services.ai.demo.simulation import geometry, snapshot as demo_snapshot
from services.ai.demo.state_adapter import (
    ai_state_from_canonical,
    canonical_from_demo_snapshot,
    planner_snapshot_from_canonical,
)


class CanonicalStateTests(unittest.TestCase):
    def later_block(self):
        original = Simulator("SCN-ALL").snapshot().to_dict()
        train = deepcopy(original["trains"][0])
        train["block_index"] = 2
        train["block_id"] = train["route"][2]
        train["block_elapsed"] = train["block_seconds"][2] * .75
        train["progress"] = (2 + .75) / len(train["route"])
        train["status"] = "running"
        original["trains"] = [train]
        original["blocks"] = [block for block in original["blocks"]
                              if block["block_id"] in train["route"]]
        next(block for block in original["blocks"]
             if block["block_id"] == train["block_id"])["occupied_by"] = train["train_id"]
        return original, train

    def test_route_progress_and_block_progress_are_distinct(self):
        old, _ = self.later_block()
        state = canonical_from_backend_snapshot(old)
        train = state["trains"][0]
        self.assertNotEqual(train["route_progress_0_1"], train["block_progress_0_1"])
        self.assertEqual(train["progress"], train["route_progress_0_1"])

    def test_train_in_later_block_has_correct_block_progress(self):
        old, original_train = self.later_block()
        state = canonical_from_backend_snapshot(old)
        train = state["trains"][0]
        self.assertEqual(train["block_progress_0_1"], .75)
        planner = planner_snapshot_from_canonical(state)
        self.assertEqual(planner["trains"][0]["progress"], .75)
        operation = build_snapshot_block_operations(planner)[0]
        self.assertEqual(operation["earliest_start_offset"],
                         math.ceil(original_train["block_seconds"][2] * .25))

    def test_canonical_snapshot_deterministic_for_same_seed(self):
        first = canonical_from_backend_snapshot(Simulator("SCN-ALL").snapshot().to_dict())
        second = canonical_from_backend_snapshot(Simulator("SCN-ALL").snapshot().to_dict())
        self.assertEqual(first, second)
        self.assertEqual(canonical_from_demo_snapshot(demo_snapshot(300, "closure", 0), 42),
                         canonical_from_demo_snapshot(demo_snapshot(300, "closure", 0), 42))

    def test_adapter_preserves_all_block_occupants(self):
        raw = demo_snapshot()
        state = canonical_from_demo_snapshot(raw, 42)
        occupants = {}
        for train in raw["state"]["trains"]:
            occupants.setdefault(train["position"]["block_id"], set()).add(train["train_id"])
        for block in state["blocks"]:
            self.assertEqual(set(block["occupied_train_ids"]), occupants.get(block["block_id"], set()))

    def test_block_capacity_conflict_not_hidden(self):
        state = canonical_from_demo_snapshot(demo_snapshot(), 42)
        conflicts = [block for block in state["blocks"] if block["state_conflict"]]
        self.assertTrue(conflicts)
        for block in conflicts:
            self.assertGreater(len(block["occupied_train_ids"]), block["capacity"])
            self.assertIn(block["occupied_by"], block["occupied_train_ids"])
        with self.assertRaisesRegex(ValueError, "cannot represent occupied blocks"):
            planner_snapshot_from_canonical(state)

    def test_legacy_progress_field_still_available_if_required(self):
        old = Simulator("SCN-ALL").snapshot().to_dict()
        self.assertIn("progress", old["trains"][0])
        state = canonical_from_backend_snapshot(old)
        self.assertEqual(state["trains"][0]["progress"], state["trains"][0]["route_progress_0_1"])

    def test_stable_train_ids(self):
        simulator = Simulator("SCN-ALL")
        before = [t["train_id"] for t in canonical_from_backend_snapshot(simulator.snapshot().to_dict())["trains"]]
        simulator.advance(60)
        after = [t["train_id"] for t in canonical_from_backend_snapshot(simulator.snapshot().to_dict())["trains"]]
        self.assertEqual(before, after)
        self.assertEqual(len(before), len(set(before)))

    def test_topology_ids_reference_existing_objects(self):
        graph = topology(geometry=geometry())
        stations = {s["station_id"] for s in graph["stations"]}
        segments = {s["segment_id"] for s in graph["segments"]}
        blocks = {b["block_id"] for b in graph["blocks"]}
        tracks = {t["track_id"] for t in graph["station_tracks"]}
        for segment in graph["segments"]:
            self.assertIn(segment["from_station_id"], stations)
            self.assertIn(segment["to_station_id"], stations)
        for block in graph["blocks"]:
            self.assertIn(block["segment_id"], segments)
        for signal in graph["signals"]:
            self.assertIn(signal["block_id"], blocks)
        for switch in graph["switches"]:
            self.assertIn(switch["station_id"], stations)
            self.assertTrue(set(switch["available_routes"]).issubset(tracks))

    def test_websocket_sequence_monotonic(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "state.sqlite3")
            simulator = Simulator("SCN-ALL")
            run_id = store.start_run(simulator.scenario_id)
            first, _ = store.append(simulator.scenario_id, run_id, [], simulator.export_state())
            simulator.advance(60)
            second, _ = store.append(simulator.scenario_id, run_id,
                                     [{"type": "INCIDENT_ONSET", "incident_id": "TEST",
                                       "virtual_time": simulator.snapshot().virtual_time}],
                                     simulator.export_state())
            self.assertGreater(second[-1]["sequence"], first[-1]["sequence"])
            self.assertNotEqual(second[-1]["event_id"], first[-1]["event_id"])
            self.assertEqual(second[0]["payload"]["snapshot_version"], simulator.version)
            store.connection.close()

    def test_snapshot_version_increments(self):
        simulator = Simulator("SCN-ALL")
        initial = canonical_from_backend_snapshot(simulator.snapshot().to_dict())["snapshot_version"]
        simulator.advance(60)
        self.assertGreater(canonical_from_backend_snapshot(simulator.snapshot().to_dict())["snapshot_version"], initial)

    def test_replay_does_not_mutate_live_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "state.sqlite3")
            simulator = Simulator("SCN-ALL")
            run_id = store.start_run(simulator.scenario_id)
            store.append(simulator.scenario_id, run_id, [], simulator.export_state())
            first_time = simulator.snapshot().virtual_time
            simulator.advance(60)
            live = simulator.snapshot().to_dict()
            store.append(simulator.scenario_id, run_id, [], simulator.export_state())
            old = store.replay(simulator.scenario_id, first_time)
            self.assertEqual(old["version"], 0)
            self.assertEqual(simulator.snapshot().to_dict(), live)
            self.assertEqual(canonical_from_backend_snapshot(old)["snapshot_version"], 0)
            store.connection.close()

    def test_demo_adapter_preserves_scenario_id_seed(self):
        state = canonical_from_demo_snapshot(demo_snapshot(300, "closure", 0), 20261001)
        self.assertEqual(state["scenario_id"], "KZ-DEMO-ADVISORY")
        self.assertEqual(state["seed"], 20261001)
        self.assertEqual(state["schema_version"], "2.0")

    def test_source_type_is_preserved(self):
        state = canonical_from_demo_snapshot(demo_snapshot(), 42)
        self.assertEqual(state["source_type"], "SIMULATED_DEMO")
        self.assertTrue(all(t["source_type"] == "SIMULATED_DEMO" for t in state["trains"]))

    def test_ai_adapter_uses_only_available_demo_fields(self):
        raw = demo_snapshot()
        state = canonical_from_demo_snapshot(raw, 42)
        ai = ai_state_from_canonical(state)
        self.assertEqual({t["train_id"] for t in ai["trains"]},
                         {t["train_id"] for t in raw["state"]["trains"]})
        self.assertEqual(ai["trains"][0]["position"], raw["state"]["trains"][0]["position"])
        with self.assertRaisesRegex(ValueError, "has no AI input fields"):
            ai_state_from_canonical(canonical_from_backend_snapshot(Simulator().snapshot().to_dict()))


if __name__ == "__main__":
    unittest.main()
