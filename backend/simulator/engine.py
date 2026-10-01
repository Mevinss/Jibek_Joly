"""Single deterministic movement rule used by live runs, replay and future solvers."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "kz_demo"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


@dataclass
class Train:
    train_id: str
    route: list[str]
    block_seconds: list[int]
    entry_signals: list[str]
    entry_switches: list[str | None]
    required_tracks: list[str | None]
    planned_start: str
    block_index: int = -1
    progress: float = 0.0
    block_elapsed: float = 0.0
    travel_elapsed: float = 0.0
    delay_min: float = 0.0
    hold_until: str | None = None
    departure_shift_seconds: int = 0
    status: str = "scheduled"

    @property
    def block_id(self) -> str | None:
        return self.route[self.block_index] if 0 <= self.block_index < len(self.route) else None


@dataclass
class ScenarioSnapshot:
    scenario_id: str
    seed: int
    virtual_time: str
    version: int
    trains: list[dict]
    blocks: list[dict]
    signals: list[dict]
    switches: list[dict]
    active_incidents: list[dict]
    source_type: str = "SIMULATED_DEMO"

    def to_dict(self) -> dict:
        return asdict(self)


class Simulator:
    def __init__(self, scenario_id: str = "SCN-ALL", data_root: Path = DATA):
        self.data_root = Path(data_root)
        self.scenarios = {item["scenario_id"]: item for item in json.loads((self.data_root / "scenarios/scenarios.json").read_text(encoding="utf-8"))}
        self.incident_defs = {item["incident_id"]: item for item in json.loads((self.data_root / "scenarios/incidents.json").read_text(encoding="utf-8"))}
        self.blocks_def = read_csv(self.data_root / "KZ/blocks.csv")
        self.segments = {row["segment_id"]: row for row in read_csv(self.data_root / "KZ/segments.csv")}
        self.signals_def = read_csv(self.data_root / "mock/signals.csv")
        self.switches_def = read_csv(self.data_root / "mock/switches.csv")
        self.services = read_csv(self.data_root / "KZ/train_services.csv")
        self.stops = read_csv(self.data_root / "KZ/run_stops.csv")
        self.station_tracks = read_csv(self.data_root / "KZ/station_tracks.csv")
        chaos_spec = json.loads((self.data_root / "scenarios/chaos_spec.json").read_text(encoding="utf-8"))
        self.scenarios["SCN-CHAOS"] = {"scenario_id": "SCN-CHAOS", "seed": chaos_spec["seed"], "start_time": self.scenarios["SCN-ALL"]["start_time"], "incident_ids": []}
        train_ids = [row["train_id"] for row in self.services]
        block_ids = [row["block_id"] for row in self.blocks_def]
        signal_ids = [row["signal_id"] for row in self.signals_def]
        switch_ids = [row["switch_id"] for row in self.switches_def]
        start = datetime.fromisoformat(self.scenarios["SCN-CHAOS"]["start_time"])
        for index in range(chaos_spec["events_per_type"]):
            for kind, key, values in (("TRAIN_DELAY", "train_id", train_ids), ("SIGNAL_FAILURE", "signal_id", signal_ids), ("SWITCH_FAILURE", "switch_id", switch_ids), ("BLOCK_CLOSURE", "block_id", block_ids)):
                incident_id = f"CHAOS-{kind}-{index + 1:02d}"
                self.incident_defs[incident_id] = {"incident_id": incident_id, "type": kind, "at": iso(start + timedelta(minutes=5 + index * 13 + (len(self.scenarios["SCN-CHAOS"]["incident_ids"]) % 4) * 2)), "duration_min": 7 + index % 9, key: values[(index * 3 + len(self.scenarios["SCN-CHAOS"]["incident_ids"])) % len(values)], "source_type": "SIMULATED_CHAOS"}
                self.scenarios["SCN-CHAOS"]["incident_ids"].append(incident_id)
        self._validate_data()
        self.reset(scenario_id)

    def _validate_data(self) -> None:
        if not self.scenarios or not self.services or not self.blocks_def:
            raise ValueError("empty Kazakhstan demo data")
        ids = {row["block_id"] for row in self.blocks_def}
        for row in self.signals_def:
            if row["block_id"] not in ids:
                raise ValueError(f"unknown signal block {row['block_id']}")

    def _build_trains(self) -> dict[str, Train]:
        by_segment: dict[str, list[dict]] = {}
        for row in self.blocks_def:
            by_segment.setdefault(row["segment_id"], []).append(row)
        for rows in by_segment.values():
            rows.sort(key=lambda row: int(row["block_order"]))
        signal_by_entry = {(row["block_id"], row["entry_direction_from"]): row["signal_id"] for row in self.signals_def}
        tracks_by_station: dict[str, list[str]] = {}
        for row in self.station_tracks:
            tracks_by_station.setdefault(row["station_id"], []).append(row["station_track_id"])
        stops_by_train: dict[str, list[dict]] = {}
        for row in self.stops:
            stops_by_train.setdefault(row["train_id"], []).append(row)
        result = {}
        for ordinal, service in enumerate(self.services):
            ordered = sorted(stops_by_train[service["train_id"]], key=lambda row: int(row["stop_order"]))
            route: list[str] = []
            seconds: list[int] = []
            signals: list[str] = []
            switches: list[str | None] = []
            tracks: list[str | None] = []
            for left, right in zip(ordered, ordered[1:]):
                a, b = left["station_id"], right["station_id"]
                segment = next((row for row in self.segments.values() if {row["from_station_id"], row["to_station_id"]} == {a, b}), None)
                if segment is None:
                    raise ValueError(f"missing segment {a}-{b}")
                rows = by_segment[segment["segment_id"]]
                if a == segment["to_station_id"]:
                    rows = list(reversed(rows))
                for idx, block in enumerate(rows):
                    route.append(block["block_id"])
                    seconds.append(max(1, round(float(segment["demo_travel_min"]) * 60 / len(rows))))
                    signals.append(signal_by_entry[(block["block_id"], a)])
                    switches.append(f"SW-{b}-ENTRY" if idx == 0 and f"SW-{b}-ENTRY" in {s["switch_id"] for s in self.switches_def} else None)
                    available = tracks_by_station.get(b, [])
                    tracks.append(available[ordinal % len(available)] if idx == 0 and available else None)
            result[service["train_id"]] = Train(service["train_id"], route, seconds, signals, switches, tracks, service["planned_start"])
        return result

    def reset(self, scenario_id: str) -> ScenarioSnapshot:
        if scenario_id not in self.scenarios:
            raise KeyError(scenario_id)
        self.scenario_id = scenario_id
        self.seed = int(self.scenarios[scenario_id]["seed"])
        self.virtual_time = datetime.fromisoformat(self.scenarios[scenario_id]["start_time"])
        self.version = 0
        self.trains = self._build_trains()
        self.blocks = {row["block_id"]: {"block_id": row["block_id"], "occupied_by": None, "closed": False} for row in self.blocks_def}
        self.signals = {row["signal_id"]: {"signal_id": row["signal_id"], "aspect": "STOP"} for row in self.signals_def}
        self.switches = {row["switch_id"]: {"switch_id": row["switch_id"], "position": row["initial_position"], "failed": False} for row in self.switches_def}
        self.active_incidents: dict[str, dict] = {}
        self.occurred: set[str] = set()
        self.events: list[dict] = []
        self._refresh_signals()
        return self.snapshot()

    def _incident_transitions(self) -> None:
        allowed = self.scenarios[self.scenario_id]["incident_ids"]
        for incident_id in allowed:
            incident = self.incident_defs[incident_id]
            onset = datetime.fromisoformat(incident["at"])
            end = onset + timedelta(minutes=int(incident["duration_min"]))
            if incident_id not in self.occurred and self.virtual_time >= onset:
                self.occurred.add(incident_id)
                self.active_incidents[incident_id] = incident
                if incident["type"] == "TRAIN_DELAY":
                    train = self.trains[incident["train_id"]]
                    if train.block_index < 0:
                        train.departure_shift_seconds += int(incident["duration_min"]) * 60
                        train.delay_min = round(train.departure_shift_seconds / 60, 2)
                        train.status = "delayed"
                    else:
                        train.hold_until = iso(end)
                elif incident["type"] == "BLOCK_CLOSURE":
                    self.blocks[incident["block_id"]]["closed"] = True
                elif incident["type"] == "SWITCH_FAILURE":
                    self.switches[incident["switch_id"]]["failed"] = True
                self.events.append({"type": "INCIDENT_ONSET", "incident_id": incident_id, "virtual_time": iso(self.virtual_time)})
            if incident_id in self.active_incidents and self.virtual_time >= end:
                self.active_incidents.pop(incident_id)
                if incident["type"] == "BLOCK_CLOSURE":
                    self.blocks[incident["block_id"]]["closed"] = False
                elif incident["type"] == "SWITCH_FAILURE":
                    self.switches[incident["switch_id"]]["failed"] = False
                self.events.append({"type": "INCIDENT_RESOLUTION", "incident_id": incident_id, "virtual_time": iso(self.virtual_time)})

    def can_enter(self, train: Train, index: int) -> bool:
        if index >= len(train.route):
            return True
        block = self.blocks[train.route[index]]
        if block["closed"] or block["occupied_by"] not in (None, train.train_id):
            return False
        if any(item["type"] == "SIGNAL_FAILURE" and item["signal_id"] == train.entry_signals[index] for item in self.active_incidents.values()):
            return False
        switch_id = train.entry_switches[index]
        if switch_id and self.switches[switch_id]["failed"] and self.switches[switch_id]["position"] != train.required_tracks[index].split("-")[-1]:
            return False
        segment_id = train.route[index].rsplit("-B", 1)[0]
        other_in_segment = [other for other in self.trains.values() if other.train_id != train.train_id and other.block_id and other.block_id.startswith(segment_id + "-B")]
        if other_in_segment:
            direction = self._entry_direction(train, index)
            if any(self._entry_direction(other, other.block_index) != direction for other in other_in_segment):
                return False
        return True

    def _entry_direction(self, train: Train, index: int) -> str:
        signal_id = train.entry_signals[index]
        return next(row["entry_direction_from"] for row in self.signals_def if row["signal_id"] == signal_id)

    def _refresh_signals(self) -> None:
        failures = {item["signal_id"] for item in self.active_incidents.values() if item["type"] == "SIGNAL_FAILURE"}
        for row in self.signals_def:
            block = self.blocks[row["block_id"]]
            segment_id = row["block_id"].rsplit("-B", 1)[0]
            opposite = any(train.block_id and train.block_id.startswith(segment_id + "-B") and self._entry_direction(train, train.block_index) != row["entry_direction_from"] for train in self.trains.values())
            self.signals[row["signal_id"]]["aspect"] = "STOP" if row["signal_id"] in failures or block["closed"] or block["occupied_by"] or opposite else "CLEAR"

    def advance(self, seconds: int) -> ScenarioSnapshot:
        if seconds < 0:
            raise ValueError("negative advance")
        remaining = seconds
        self.events = []
        while remaining:
            step = min(60, remaining)
            self.virtual_time += timedelta(seconds=step)
            self._incident_transitions()
            for train in sorted(self.trains.values(), key=lambda item: (item.planned_start, item.train_id)):
                if train.status == "completed":
                    continue
                start = datetime.fromisoformat(train.planned_start) + timedelta(seconds=train.departure_shift_seconds)
                if train.block_index < 0 and self.virtual_time < start:
                    continue
                if train.hold_until and self.virtual_time < datetime.fromisoformat(train.hold_until):
                    train.status = "held"
                    train.delay_min = round(max(0, (self.virtual_time - datetime.fromisoformat(train.planned_start)).total_seconds() - train.travel_elapsed) / 60, 2)
                    continue
                next_index = train.block_index + 1
                if train.block_index < 0 or train.block_elapsed >= train.block_seconds[train.block_index]:
                    if next_index >= len(train.route):
                        if train.block_id:
                            self.blocks[train.block_id]["occupied_by"] = None
                        train.block_index = len(train.route)
                        train.progress = 1.0
                        train.status = "completed"
                        continue
                    if not self.can_enter(train, next_index):
                        train.status = "waiting"
                        train.delay_min = round(max(0, (self.virtual_time - datetime.fromisoformat(train.planned_start)).total_seconds() - train.travel_elapsed) / 60, 2)
                        continue
                    if train.block_id:
                        self.blocks[train.block_id]["occupied_by"] = None
                    train.block_index = next_index
                    self.blocks[train.block_id]["occupied_by"] = train.train_id
                    train.block_elapsed = 0.0
                train.status = "running"
                train.block_elapsed = min(train.block_seconds[train.block_index], train.block_elapsed + step)
                train.travel_elapsed += step
                train.progress = round((train.block_index + train.block_elapsed / train.block_seconds[train.block_index]) / len(train.route), 6)
                train.delay_min = round(max(0, (self.virtual_time - datetime.fromisoformat(train.planned_start)).total_seconds() - train.travel_elapsed) / 60, 2)
            self._refresh_signals()
            self.version += 1
            remaining -= step
        return self.snapshot()

    def snapshot(self) -> ScenarioSnapshot:
        return ScenarioSnapshot(self.scenario_id, self.seed, iso(self.virtual_time), self.version, [asdict(train) | {"block_id": train.block_id} for train in self.trains.values()], list(self.blocks.values()), list(self.signals.values()), list(self.switches.values()), list(self.active_incidents.values()))

    def export_state(self) -> dict:
        return {"snapshot": self.snapshot().to_dict(), "occurred": sorted(self.occurred)}

    def restore_state(self, state: dict) -> None:
        snapshot = state["snapshot"]
        self.reset(snapshot["scenario_id"])
        self.virtual_time = datetime.fromisoformat(snapshot["virtual_time"])
        self.version = snapshot["version"]
        self.trains = {row["train_id"]: Train(**{key: value for key, value in row.items() if key != "block_id"}) for row in snapshot["trains"]}
        self.blocks = {row["block_id"]: row for row in snapshot["blocks"]}
        self.signals = {row["signal_id"]: row for row in snapshot["signals"]}
        self.switches = {row["switch_id"]: row for row in snapshot["switches"]}
        self.active_incidents = {row["incident_id"]: row for row in snapshot["active_incidents"]}
        self.occurred = set(state["occurred"])
