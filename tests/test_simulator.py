from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.simulator import Simulator
from backend.store import EventStore


class SimulatorTests(unittest.TestCase):
    def test_reset_is_deterministic_and_movement_is_safe(self):
        simulator = Simulator("SCN-ALL")
        first = simulator.snapshot().to_dict()
        progress = {train["train_id"]: 0 for train in first["trains"]}
        for _ in range(180):
            snapshot = simulator.advance(60).to_dict()
            occupants = [block["occupied_by"] for block in snapshot["blocks"] if block["occupied_by"]]
            self.assertEqual(len(occupants), len(set(occupants)))
            for train in snapshot["trains"]:
                self.assertGreaterEqual(train["progress"], progress[train["train_id"]])
                self.assertLessEqual(train["progress"], 1)
                self.assertTrue(train["block_id"] is None or train["block_id"] in train["route"])
                progress[train["train_id"]] = train["progress"]
        simulator.reset("SCN-ALL")
        self.assertEqual(first, simulator.snapshot().to_dict())

    def test_incidents_change_and_restore_resources(self):
        simulator = Simulator("SCN-ALL")
        simulator.advance(50 * 60)
        self.assertEqual(simulator.signals["SIG-BOR-AKK-B01-BOR"]["aspect"], "STOP")
        self.assertTrue(simulator.switches["SW-AST-ENTRY"]["failed"])
        self.assertIn("INC-01", simulator.occurred)
        self.assertIn("INC-02", simulator.active_incidents)
        affected = next(train for train in simulator.trains.values() if "SIG-BOR-AKK-B01-BOR" in train.entry_signals)
        index = affected.entry_signals.index("SIG-BOR-AKK-B01-BOR")
        self.assertFalse(simulator.can_enter(affected, index))
        simulator.advance(30 * 60)
        self.assertNotIn("INC-02", simulator.active_incidents)
        self.assertFalse(simulator.switches["SW-AST-ENTRY"]["failed"])
        simulator.advance(105 * 60)
        self.assertTrue(simulator.blocks["KAR-AKD-B01"]["closed"])
        simulator.advance(36 * 60)
        self.assertFalse(simulator.blocks["KAR-AKD-B01"]["closed"])
        event_types = {event["type"] for event in simulator.events}
        self.assertTrue(event_types <= {"INCIDENT_ONSET", "INCIDENT_RESOLUTION"})

    def test_chaos_fixture_is_independent_and_varied(self):
        simulator = Simulator("SCN-CHAOS")
        incidents = [simulator.incident_defs[id] for id in simulator.scenarios["SCN-CHAOS"]["incident_ids"]]
        self.assertEqual(len(incidents), 40)
        self.assertEqual(len({item["incident_id"] for item in incidents}), 40)
        self.assertEqual({item["type"] for item in incidents}, {"TRAIN_DELAY", "SIGNAL_FAILURE", "SWITCH_FAILURE", "BLOCK_CLOSURE"})
        self.assertNotEqual(simulator.seed, Simulator("SCN-ALL").seed)

    def test_sqlite_restart_and_replay_do_not_mutate_live_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "history.sqlite3")
            simulator = Simulator("SCN-01")
            run_id = store.start_run("SCN-01")
            store.append("SCN-01", run_id, [], simulator.export_state())
            first = simulator.snapshot().to_dict()
            simulator.advance(10 * 60)
            store.append("SCN-01", run_id, simulator.events, simulator.export_state())
            later = simulator.snapshot().to_dict()
            self.assertEqual(store.replay("SCN-01", first["virtual_time"]), first)
            self.assertEqual(store.replay("SCN-01", later["virtual_time"]), later)
            self.assertEqual(simulator.snapshot().to_dict(), later)
            restored = Simulator("SCN-01")
            restored.restore_state(store.latest_state("SCN-01", run_id))
            self.assertEqual(restored.snapshot().to_dict(), later)
            self.assertGreater(store.current("SCN-01")["last_sequence"], 1)
            store.connection.close()


if __name__ == "__main__":
    unittest.main()
