"""Canonical input preparation and explicit demonstration resource semantics.

No solver or state mutation lives here. The validator re-derives this input
instead of trusting operation metadata supplied by a candidate plan.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from backend.validator.resources import DATA, load_infrastructure
from backend.validator.state import occupants, remaining_block_seconds
from .models import PlanningConfig, Violation


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("timestamps require a timezone offset")
    return result


@dataclass
class Operation:
    train_id: str
    sequence: int
    route_index: int
    kind: str
    resources: list[str]
    duration: int
    earliest: int
    direction: str | None = None
    segment_id: str | None = None
    existing: bool = False
    final: bool = False
    forbidden: list[tuple[int, int, str]] = field(default_factory=list)
    tail_seconds: int = 0


class PlanningContext:
    def __init__(self, snapshot: dict, config: PlanningConfig, infrastructure: dict | None = None):
        if snapshot.get("schema_version") != "2.0":
            raise ValueError("full planning requires CanonicalScenarioSnapshot schema_version 2.0")
        for key in ("scenario_id", "seed", "run_id", "dataset_version", "snapshot_version",
                    "source_type", "trains", "blocks", "station_tracks", "signals", "switches", "active_incidents"):
            if key not in snapshot:
                raise ValueError(f"canonical snapshot missing {key}")
        self.snapshot, self.config = snapshot, config
        self.base = timestamp(snapshot["virtual_time"])
        self.horizon = config.horizon_seconds
        self.infra = infrastructure if infrastructure is not None else self._fixture()
        self.trains = {t["train_id"]: t for t in snapshot["trains"]}
        self.blocks = {b["block_id"]: b for b in snapshot["blocks"]}
        self.tracks = {t.get("track_id", t.get("station_track_id")): t for t in snapshot["station_tracks"]}
        self.signals = {s["signal_id"]: s for s in snapshot["signals"]}
        self.switches = {s["switch_id"]: s for s in snapshot["switches"]}
        self.incidents = snapshot["active_incidents"] + snapshot.get("planned_incidents", [])
        self.violations: list[Violation] = []
        self.unverified: set[str] = set()
        self.operations: dict[str, list[Operation]] = {}
        self.deferred: list[str] = []
        self.priorities: dict[str, int] = {}
        self.weights: dict[str, int] = {}
        self.due: dict[str, int | None] = {}
        self.fixed_tracks: list[tuple[str, str, int]] = []
        self._initial_state()
        for train_id in sorted(self.trains):
            try:
                self._train(self.trains[train_id])
            except (KeyError, TypeError, ValueError, IndexError) as exc:
                self.violations.append(Violation("INPUT_INCOMPLETE", str(exc), train_ids=[train_id]))

    @staticmethod
    def _fixture() -> dict:
        infra = load_infrastructure()
        for name, relative, key in (("services", "KZ/train_services.csv", "train_id"),
                                    ("parameters", "mock/train_parameters.csv", "category")):
            with (DATA / relative).open(encoding="utf-8-sig", newline="") as stream:
                infra[name] = {row[key]: row for row in csv.DictReader(stream)}
        with (DATA / "KZ/run_stops.csv").open(encoding="utf-8-sig", newline="") as stream:
            infra["stops"] = list(csv.DictReader(stream))
        return infra

    def iso(self, seconds: float) -> str:
        return (self.base + timedelta(seconds=seconds)).isoformat()

    def offset(self, value: str) -> int:
        return math.ceil((timestamp(value) - self.base).total_seconds())

    def capacity(self, kind: str, resource_id: str) -> int:
        table = self.blocks if kind == "block" else self.tracks
        static = self.infra["blocks" if kind == "block" else "station_tracks"][resource_id]
        return int(table.get(resource_id, {}).get("capacity", static.get("demo_capacity_trains", 1)))

    def locked(self, segment_id: str | None) -> bool:
        return self.infra.get("segments", {}).get(segment_id, {}).get("direction_lock") == "one_direction_at_a_time"

    def _initial_state(self):
        if len(self.trains) != len(self.snapshot["trains"]) or len(self.blocks) != len(self.snapshot["blocks"]):
            self.violations.append(Violation("DUPLICATE_STATE_ID", "Duplicate train/block IDs"))
        for block_id, block in self.blocks.items():
            if not isinstance(block.get("occupied_train_ids"), list):
                self.violations.append(Violation("INPUT_INCOMPLETE", "Canonical block requires occupied_train_ids", block_id))
                continue
            ids = occupants(block)
            if block_id not in self.infra["blocks"]:
                self.violations.append(Violation("UNKNOWN_RESOURCE", "Block absent from topology", block_id, ids))
                continue
            if self.capacity("block", block_id) < 1:
                self.violations.append(Violation("INVALID_CAPACITY", "Capacity must be positive", block_id))
            if block.get("state_conflict") or len(ids) > self.capacity("block", block_id):
                self.violations.append(Violation("INITIAL_CAPACITY_CONFLICT", "Initial block capacity exceeded", block_id, ids))
            if len(ids) != len(set(ids)):
                self.violations.append(Violation("DUPLICATE_OCCUPANT", "Duplicate occupant", block_id, ids))
            for train_id in ids:
                train = self.trains.get(train_id, {})
                if train.get("current_block_id") != block_id or train.get("status") == "completed":
                    self.violations.append(Violation("OCCUPANCY_MISMATCH", "Occupant has no matching active train", block_id, [train_id]))
        for train in self.trains.values():
            block_id = train.get("current_block_id")
            if block_id and train["train_id"] not in occupants(self.blocks.get(block_id, {})):
                self.violations.append(Violation("OCCUPANCY_MISMATCH", "Current train missing from occupied_train_ids", block_id, [train["train_id"]]))
        for track_id, track in self.tracks.items():
            if track_id not in self.infra["station_tracks"]:
                continue
            if track.get("occupancy_source") == "UNAVAILABLE" or track.get("available") is None:
                self.unverified.add("STATION_TRACK_OCCUPANCY")
                continue
            ids = occupants(track)
            if len(ids) > self.capacity("station_track", track_id):
                self.violations.append(Violation("INITIAL_CAPACITY_CONFLICT", "Initial station capacity exceeded", track_id, ids))
            release = max(0, self.offset(track["release_time"])) if track.get("release_time") else self.horizon
            for train_id in ids:
                self.fixed_tracks.append((track_id, train_id, release))
        for incident in self.incidents:
            if incident.get("type") not in {"BLOCK_CLOSURE", "SIGNAL_FAILURE", "SWITCH_FAILURE", "TRAIN_DELAY"}:
                self.violations.append(Violation("UNSUPPORTED_INCIDENT", f"Unsupported incident {incident.get('type')}"))
                continue
            field_name, table = {"BLOCK_CLOSURE": ("block_id", self.blocks),
                                 "SIGNAL_FAILURE": ("signal_id", self.signals),
                                 "SWITCH_FAILURE": ("switch_id", self.switches),
                                 "TRAIN_DELAY": ("train_id", self.trains)}[incident["type"]]
            if incident.get(field_name) not in table:
                self.violations.append(Violation("INCIDENT_TARGET_UNKNOWN", f"Incident requires a known {field_name}"))
            try:
                if incident.get("duration_min") is not None and (not math.isfinite(float(incident["duration_min"])) or float(incident["duration_min"]) < 0):
                    raise ValueError("incident duration must be finite and nonnegative")
                self._window(incident)
            except (TypeError, ValueError) as exc:
                self.violations.append(Violation("INVALID_INCIDENT_WINDOW", str(exc)))

    def _window(self, incident: dict) -> tuple[int, int, str]:
        start = self.offset(incident.get("at", self.snapshot["virtual_time"]))
        if incident.get("end_time"):
            end = self.offset(incident["end_time"])
        elif incident.get("duration_min") is not None:
            end = start + math.ceil(float(incident["duration_min"]) * 60)
        else:
            end = self.horizon
        return max(0, start), max(0, end), incident["type"]

    def _forbidden(self, train: dict, index: int) -> list[tuple[int, int, str]]:
        block_id = train["route"][index]
        block = self.blocks[block_id]
        signal_id = self._at(train, "entry_signals", index)
        signal = self.signals.get(signal_id, {})
        switch_id = self._at(train, "entry_switches", index)
        switch = self.switches.get(switch_id, {})
        required = self._at(train, "required_tracks", index)
        windows = []
        closure, failure, switch_failure = False, False, False
        for incident in self.incidents:
            kind = incident.get("type")
            applies = False
            if kind == "BLOCK_CLOSURE" and incident.get("block_id") == block_id:
                a, b, _ = self._window(incident)
                closure, applies = closure or a == 0 < b, True
            if kind == "SIGNAL_FAILURE" and incident.get("signal_id") == signal_id:
                a, b, _ = self._window(incident)
                failure, applies = failure or a == 0 < b, True
            if kind == "SWITCH_FAILURE" and incident.get("switch_id") == switch_id and switch_id:
                a, b, _ = self._window(incident)
                switch_failure = switch_failure or a == 0 < b
                position = incident.get("locked_position", switch.get("position"))
                applies = not required or position not in (required, required.split("-")[-1])
            if applies:
                windows.append(self._window(incident))
        if block.get("closed") and not closure:
            windows.append((0, self.horizon, "BLOCK_CLOSED"))
        direction = self.infra.get("signals", {}).get(signal_id, {}).get("entry_direction_from") or train.get("direction")
        if block.get("direction_lock") and block["direction_lock"] != direction:
            segment_id = self.infra["blocks"][block_id]["segment_id"]
            has_occupant = any(occupants(b) and self.infra["blocks"].get(b["block_id"], {}).get("segment_id") == segment_id
                               for b in self.blocks.values())
            if not has_occupant:
                windows.append((0, self.horizon, "DIRECTION_LOCK"))
        if not signal or signal.get("aspect") is None:
            self.unverified.add("SIGNAL_STATE")
        elif signal.get("aspect") != "CLEAR" and not failure:
            # Simulator STOP can be derived from occupancy/direction. Its release
            # is then governed by resource reservations, not an invented timer.
            segment_id = self.infra["blocks"][block_id]["segment_id"]
            opposite_present = False
            for other in self.trains.values():
                other_block = other.get("current_block_id")
                if self.infra["blocks"].get(other_block, {}).get("segment_id") != segment_id:
                    continue
                other_signal = self._at(other, "entry_signals", int(other.get("block_index", -1)))
                other_direction = self.infra.get("signals", {}).get(other_signal, {}).get("entry_direction_from") or other.get("direction")
                if direction and other_direction and direction != other_direction:
                    opposite_present = True
            derived_stop = bool(block.get("closed") or occupants(block) or opposite_present)
            if signal.get("failed") or not derived_stop:
                windows.append((0, self.horizon, "SIGNAL_NOT_CLEAR"))
        if switch_id:
            if not switch or switch.get("position") is None or switch.get("failed") is None:
                self.unverified.add("SWITCH_STATE")
            elif (switch.get("failed") or switch.get("locked")) and not switch_failure:
                if not required or switch["position"] not in (required, required.split("-")[-1]):
                    windows.append((0, self.horizon, "SWITCH_ROUTE_UNAVAILABLE"))
            if required and switch.get("available_routes") is not None and required not in switch["available_routes"]:
                windows.append((0, self.horizon, "SWITCH_ROUTE_UNAVAILABLE"))
        return windows

    @staticmethod
    def _at(train: dict, key: str, index: int):
        values = train.get(key, [])
        return values[index] if 0 <= index < len(values) else None

    def _train(self, train: dict):
        train_id = train["train_id"]
        if train.get("status") == "completed":
            self.deferred.append(train_id)
            return
        route, durations = train["route"], train["block_seconds"]
        if not route or len(durations) != len(route) or any(not math.isfinite(float(d)) or d <= 0 for d in durations):
            raise ValueError("route requires a positive block_seconds value for every block")
        if any(b not in self.blocks or b not in self.infra["blocks"] for b in route):
            raise ValueError("route references missing blocks")
        current = train.get("current_block_id")
        first = int(train.get("block_index", -1)) if current else 0
        if first < 0 or first >= len(route) or (current and route[first] != current):
            raise ValueError("current block/index does not match route")
        if current and "block_progress_0_1" not in train:
            raise ValueError("canonical current block requires block_progress_0_1")
        start = 0 if current else max(0, self.offset(train["planned_start"]) + int(train.get("departure_shift_seconds", 0)))
        hold = max(0, self.offset(train["hold_until"])) if train.get("hold_until") else 0
        start = start if current else max(start, hold)
        for incident in self.incidents:
            if incident.get("type") == "TRAIN_DELAY" and incident.get("train_id") == train_id:
                if 0 < self._window(incident)[0] < self.horizon:
                    self.unverified.add("FUTURE_TRAIN_DELAY")
                # Active shifts/holds are already reflected by Person 1.
        service = self.infra.get("services", {}).get(train_id, {})
        category = train.get("category") or service.get("category", "unknown")
        params = self.infra.get("parameters", {}).get(category, {})
        self.priorities[train_id] = int(train.get("priority", params.get("priority", 0)))
        self.weights[train_id] = self.config.category_weights.get(category, 1)
        stops = sorted((s for s in self.infra.get("stops", []) if s["train_id"] == train_id), key=lambda s: int(s["stop_order"]))
        due = train.get("scheduled_final_arrival") or next((s["scheduled_arrival"] for s in reversed(stops) if s.get("scheduled_arrival")), None)
        self.due[train_id] = self.offset(due) if due else None
        if not due:
            self.unverified.add("FINAL_ARRIVAL_SCHEDULE")
        if start >= self.horizon:
            self.deferred.append(train_id)
            return
        explicit_stops = {int(s["after_route_index"]): s for s in train.get("station_stops", [])}
        all_ops = []
        earliest = start
        for index in range(first, len(route)):
            block_id = route[index]
            segment_id = self.infra["blocks"][block_id]["segment_id"]
            signal_id = self._at(train, "entry_signals", index)
            direction = self.infra.get("signals", {}).get(signal_id, {}).get("entry_direction_from") or train.get("direction")
            if self.locked(segment_id) and not direction:
                raise ValueError("direction-locked segment requires direction metadata")
            existing = bool(current and index == first)
            duration = remaining_block_seconds(train) if existing else math.ceil(durations[index])
            if existing:
                duration += hold
            op = Operation(train_id, len(all_ops), index, "block", [block_id], duration, earliest,
                           direction, segment_id, existing, index == len(route) - 1,
                           [] if existing else self._forbidden(train, index))
            all_ops.append(op)
            earliest += duration
            stop = explicit_stops.get(index)
            boundary = index < len(route) - 1 and self.infra["blocks"][route[index + 1]]["segment_id"] != segment_id
            if stop is None and boundary and stops:
                segment = self.infra["segments"][segment_id]
                station = segment["to_station_id"] if direction == segment["from_station_id"] or train.get("direction") == "forward" else segment["from_station_id"]
                row = next((s for s in stops if s["station_id"] == station), None)
                if row and row.get("scheduled_arrival") and row.get("scheduled_departure"):
                    stop = {"station_id": station, "min_dwell_seconds": max(0, int((timestamp(row["scheduled_departure"]) - timestamp(row["scheduled_arrival"])).total_seconds()))}
            if stop and int(stop["min_dwell_seconds"]) > 0:
                station_id = stop["station_id"]
                candidates = sorted(stop.get("track_ids") or [k for k, v in self.infra["station_tracks"].items() if v["station_id"] == station_id])
                required_tracks = [self._at(train, "required_tracks", j) for j in range(index + 1)
                                   if self.infra["blocks"][route[j]]["segment_id"] == segment_id]
                required_tracks = [r for r in required_tracks if r and self.infra["station_tracks"].get(r, {}).get("station_id") == station_id]
                if required_tracks:
                    candidates = [r for r in candidates if r == required_tracks[-1]]
                if not candidates or any(k not in self.infra["station_tracks"] or self.infra["station_tracks"][k]["station_id"] != station_id for k in candidates):
                    raise ValueError("station stop requires valid static track definitions")
                for track_id in candidates:
                    row = self.tracks.get(track_id, {})
                    if not row or row.get("occupancy_source") == "UNAVAILABLE" or row.get("available") is None:
                        self.unverified.add("STATION_TRACK_OCCUPANCY")
                dwell = int(stop["min_dwell_seconds"])
                op.final = False
                all_ops.append(Operation(train_id, len(all_ops), index, "station_track", candidates,
                                         dwell, earliest, final=index == len(route) - 1))
                earliest += dwell
        tail = 0
        for op in reversed(all_ops):
            op.tail_seconds = tail
            tail += op.duration
        self.operations[train_id] = [op for op in all_ops if op.earliest < self.horizon or op.existing]

    def available_tracks(self, op: Operation) -> list[str]:
        if op.kind != "station_track":
            return op.resources
        return [r for r in op.resources if self.tracks.get(r, {}).get("available") is not False
                or occupants(self.tracks.get(r, {}))]
