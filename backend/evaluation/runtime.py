"""Narrow public-engine adapter; station-capable forks belong to Person 1.

The existing engine has no station dwell/apply API. This adapter supports ONLY
block-only journeys on checked-in KZ infrastructure, capacity one, no dwell.
It preserves can_enter/advance movement rules and adds advisory entry-time gates.
Arrival is always observed from advance(), never copied from a plan.
"""
from copy import deepcopy
from dataclasses import fields
from datetime import datetime, timedelta
from typing import Protocol

from backend.simulator.engine import Simulator, Train


class ExecutorUnavailable(ValueError):
    pass


class SimulationFork(Protocol):
    rules_id: str
    def snapshot(self) -> dict: ...
    def advance(self, seconds: int) -> dict: ...


class BlockRouteEngineFork:
    rules_id = "backend-engine-v1/block-route-plan-gate-v1/step-1s"

    def __init__(self, snapshot: dict, plan: dict, schedule: dict):
        if any(t.get("station_stops") for t in snapshot["trains"]):
            raise ExecutorUnavailable("STATION_CAPABLE_FORK_REQUIRED: only block-only journeys supported")
        if any(r["resource_type"] != "block" for r in plan["resource_intervals"]):
            raise ExecutorUnavailable("STATION_OPERATIONS_UNSUPPORTED")
        if any(b.get("capacity", 1) != 1 or len(b["occupied_train_ids"]) > 1 for b in snapshot["blocks"]):
            raise ExecutorUnavailable("MULTI_CAPACITY_FORK_REQUIRED")
        engine = Simulator(snapshot["scenario_id"])
        if {b["block_id"] for b in snapshot["blocks"]} != set(engine.blocks):
            raise ExecutorUnavailable("KZ_ENGINE_INFRASTRUCTURE_MISMATCH")
        if {s["signal_id"] for s in snapshot["signals"]} != set(engine.signals):
            raise ExecutorUnavailable("KZ_ENGINE_SIGNALS_MISMATCH")
        if {s["switch_id"] for s in snapshot["switches"]} != set(engine.switches):
            raise ExecutorUnavailable("KZ_ENGINE_SWITCHES_MISMATCH")
        trains = []
        for row in snapshot["trains"]:
            values = {f.name: deepcopy(row[f.name]) for f in fields(Train) if f.name in row}
            train = Train(**values)
            if 0 <= train.block_index < len(train.route):
                train.block_elapsed = row["block_progress_0_1"] * train.block_seconds[train.block_index]
                if "travel_elapsed" not in row:
                    train.travel_elapsed = sum(train.block_seconds[:train.block_index]) + train.block_elapsed
            train.progress = row["route_progress_0_1"]
            trains.append({f.name: getattr(train, f.name) for f in fields(Train)})
        active = deepcopy(snapshot["active_incidents"])
        incidents = {i["incident_id"]: i for i in active + deepcopy(snapshot.get("planned_incidents", []))}
        # The original engine cannot safely resolve overlapping closures on one resource.
        windows = {}
        for incident in incidents.values():
            if incident["type"] not in {"TRAIN_DELAY", "BLOCK_CLOSURE", "SIGNAL_FAILURE", "SWITCH_FAILURE"}:
                raise ExecutorUnavailable("INCIDENT_TYPE_UNSUPPORTED")
            if not isinstance(incident["duration_min"], int):
                raise ExecutorUnavailable("ENGINE_REQUIRES_INTEGER_INCIDENT_DURATION")
            key = (incident["type"], incident.get("block_id") or incident.get("signal_id") or incident.get("switch_id") or incident.get("train_id"))
            left = datetime.fromisoformat(incident["at"])
            right = left + timedelta(minutes=incident["duration_min"])
            if any(left < b and a < right for a, b in windows.get(key, [])):
                raise ExecutorUnavailable("OVERLAPPING_INCIDENTS_UNSUPPORTED")
            windows.setdefault(key, []).append((left, right))
        state = {"snapshot": dict(scenario_id=snapshot["scenario_id"], seed=snapshot["seed"],
            virtual_time=snapshot["virtual_time"], version=snapshot["snapshot_version"], trains=trains,
            blocks=[dict(block_id=b["block_id"], occupied_by=next(iter(b["occupied_train_ids"]), None), closed=b["closed"]) for b in snapshot["blocks"]],
            signals=deepcopy(snapshot["signals"]), switches=deepcopy(snapshot["switches"]), active_incidents=active),
            "occurred": [i["incident_id"] for i in active]}
        engine.restore_state(state)
        engine.seed = snapshot["seed"]
        # Only the supplied incident schedule is used, not the engine fixture schedule.
        engine.incident_defs = incidents
        engine.scenarios[engine.scenario_id]["incident_ids"] = list(incidents)
        commands = {(c["train_id"], c["sequence"]): datetime.fromisoformat(c["at"])
                    for c in schedule["transitions"] if c["action"] == "ENTER_RESOURCE"}
        entries = {(r["train_id"], r["route_index"]): commands[(r["train_id"], r["sequence"])]
                   for r in plan["resource_intervals"] if not r["existing_occupancy"]}
        self.completions = {c["train_id"]: c["at"] for c in schedule["transitions"] if c["action"] == "COMPLETE_TRAIN"}
        self.horizon_end = plan["planning_horizon_end"]
        original_can_enter = engine.can_enter
        released = {}
        headway = plan["config"]["headway_seconds"]

        def gated(train, index):
            bid = train.route[index]
            at = entries.get((train.train_id, index))
            if at is None or engine.virtual_time < at:
                return False
            if bid in released and released[bid][1] != train.train_id and (engine.virtual_time - released[bid][0]).total_seconds() < headway:
                return False
            return original_can_enter(train, index)

        engine.can_enter = gated
        self.engine, self.released = engine, released

    def snapshot(self):
        return deepcopy(self.engine.snapshot().to_dict())

    def advance(self, seconds):
        if seconds != 1:
            raise ValueError("block-route adapter requires one-second observations")
        before = {t.train_id: t.block_id for t in self.engine.trains.values()}
        # Preserve release headway even when the engine iterates the next train
        # in the same second: know which completed traversal will release now.
        for train in self.engine.trains.values():
            if train.block_index == len(train.route) - 1 and train.block_elapsed >= train.block_seconds[train.block_index]:
                release_at = self.completions.get(train.train_id)
                if release_at is None:
                    release_at = (datetime.fromisoformat(self.horizon_end) + timedelta(seconds=1)).isoformat()
                if not train.hold_until or datetime.fromisoformat(train.hold_until) < datetime.fromisoformat(release_at):
                    train.hold_until = release_at
            if train.block_id and train.block_elapsed >= train.block_seconds[train.block_index]:
                if not train.hold_until or datetime.fromisoformat(train.hold_until) <= self.engine.virtual_time + timedelta(seconds=1):
                    self.released[train.block_id] = (self.engine.virtual_time + timedelta(seconds=1), train.train_id)
        frame = self.engine.advance(seconds).to_dict()
        frame["events"] = deepcopy(self.engine.events)
        frame["runtime_violations"] = []
        for block in frame["blocks"]:
            occupants = [t["train_id"] for t in frame["trains"] if t["block_id"] == block["block_id"]]
            if len(occupants) > 1:
                frame["runtime_violations"].append(dict(type="BLOCK_CAPACITY", resource_id=block["block_id"], train_ids=occupants))
        for t in frame["trains"]:
            if before[t["train_id"]] and before[t["train_id"]] != t["block_id"]:
                self.released[before[t["train_id"]]] = (self.engine.virtual_time, t["train_id"])
        return deepcopy(frame)
