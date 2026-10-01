"""Independent checks for dispatcher actions and resource reservations.

This module validates proposed decisions; it never mutates the simulator.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .state import remaining_block_seconds

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "kz_demo"


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    train_id: str | None = None
    resource_id: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    issues: tuple[ValidationIssue, ...]
    snapshot_version: int | None = None
    affected_resource: str | None = None
    run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "accepted": self.valid,
                "issues": [asdict(issue) for issue in self.issues],
                "snapshot_version": self.snapshot_version,
                "affected_resource": self.affected_resource, "run_id": self.run_id,
                "reason_code": self.issues[0].code if self.issues else "ACCEPTED",
                "reason": "; ".join(issue.message for issue in self.issues)}


def load_infrastructure(data_root: Path = DATA) -> dict[str, Any]:
    """Read only the small checked-in infrastructure tables; no simulator copy."""
    data_root = Path(data_root)

    def rows(relative: str) -> list[dict[str, str]]:
        with (data_root / relative).open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    return {
        "blocks": {r["block_id"]: r for r in rows("KZ/blocks.csv")},
        "segments": {r["segment_id"]: r for r in rows("KZ/segments.csv")},
        "signals": {r["signal_id"]: r for r in rows("mock/signals.csv")},
        "switches": {r["switch_id"]: r for r in rows("mock/switches.csv")},
        "station_tracks": {r["station_track_id"]: r for r in rows("KZ/station_tracks.csv")},
    }


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("timestamps must include a timezone offset")
    return result


def _issue(code: str, message: str, train_id: str | None = None,
           resource_id: str | None = None) -> ValidationIssue:
    return ValidationIssue(code, message, train_id, resource_id)


def validate_human_decision(
    snapshot: dict[str, Any],
    decision: dict[str, Any],
    infrastructure: dict[str, Any] | None = None,
) -> ValidationResult:
    """Check a proposed action against one immutable snapshot and return a reason."""
    if snapshot.get("schema_version") == "2.0":
        from .dispatch import validate_canonical_human_decision
        return validate_canonical_human_decision(snapshot, decision, infrastructure)
    infra = infrastructure or load_infrastructure()
    train_id = decision.get("train_id")
    trains = {t["train_id"]: t for t in snapshot.get("trains", [])}
    train = trains.get(train_id)

    if decision.get("snapshot_version") != snapshot.get("version"):
        return ValidationResult(False, (_issue(
            "STALE_SNAPSHOT",
            f"Stale snapshot_version: received {decision.get('snapshot_version')}, current {snapshot.get('version')}.",
            train_id,
        ),))
    action = decision.get("action")
    if action not in {"GRANT_ENTRY", "HOLD_TRAIN", "SELECT_STATION_TRACK"}:
        return ValidationResult(False, (_issue("UNKNOWN_ACTION", f"Unsupported action: {action!r}.", train_id),))
    if train is None:
        return ValidationResult(False, (_issue("UNKNOWN_TRAIN", f"Unknown train: {train_id!r}.", train_id),))

    if action == "HOLD_TRAIN":
        return ValidationResult(True, ())

    if action == "SELECT_STATION_TRACK":
        track_id = decision.get("resource_id")
        if track_id not in infra["station_tracks"]:
            return ValidationResult(False, (_issue("UNKNOWN_STATION_TRACK", f"Unknown station track: {track_id!r}.", train_id, track_id),))
        track_state = next((t for t in snapshot.get("station_tracks", []) if t.get("station_track_id") == track_id), None)
        if track_state is None:
            return ValidationResult(False, (_issue("STATION_TRACK_STATE_UNKNOWN", f"Snapshot v1 does not report occupancy for {track_id}; selection cannot be validated safely.", train_id, track_id),))
        if track_state.get("occupied_by") not in (None, train_id):
            return ValidationResult(False, (_issue("STATION_TRACK_OCCUPIED", f"Station track {track_id} is occupied by {track_state.get('occupied_by')}.", train_id, track_id),))
        next_index = int(train.get("block_index", -1)) + 1
        required = train.get("required_tracks", [])
        expected = required[next_index] if 0 <= next_index < len(required) else None
        if expected and expected != track_id:
            return ValidationResult(False, (_issue("ROUTE_TRACK_MISMATCH", f"Train requires {expected}; {track_id} is not on its route.", train_id, track_id),))
        return ValidationResult(True, ())

    route = train.get("route", [])
    index = int(train.get("block_index", -1)) + 1
    if index < 0 or index >= len(route):
        return ValidationResult(False, (_issue("NO_NEXT_BLOCK", "Train has no next block to enter.", train_id),))
    block_id = route[index]
    requested_block = decision.get("resource_id")
    if requested_block and requested_block != block_id:
        return ValidationResult(False, (_issue("ROUTE_BLOCK_MISMATCH", f"Next route block is {block_id}, not {requested_block}.", train_id, requested_block),))

    blocks = {b["block_id"]: b for b in snapshot.get("blocks", [])}
    block = blocks.get(block_id)
    issues: list[ValidationIssue] = []
    if block is None:
        issues.append(_issue("UNKNOWN_BLOCK", f"Block {block_id} is absent from the snapshot.", train_id, block_id))
    elif block.get("closed"):
        issues.append(_issue("BLOCK_CLOSED", f"Block {block_id} is closed to new entry.", train_id, block_id))
    elif block.get("occupied_by") not in (None, train_id):
        issues.append(_issue("BLOCK_OCCUPIED", f"Block {block_id} is occupied by {block.get('occupied_by')}.", train_id, block_id))

    signals = {s["signal_id"]: s for s in snapshot.get("signals", [])}
    entry_signals = train.get("entry_signals", [])
    signal_id = entry_signals[index] if index < len(entry_signals) else None
    signal = signals.get(signal_id)
    if signal_id is None or signal is None:
        issues.append(_issue("MISSING_ENTRY_SIGNAL", "The next block has no signal state in this snapshot.", train_id, block_id))
    elif signal.get("aspect") != "CLEAR":
        issues.append(_issue("SIGNAL_NOT_CLEAR", f"Signal {signal_id} is {signal.get('aspect')}; entry is denied.", train_id, signal_id))

    switches = {s["switch_id"]: s for s in snapshot.get("switches", [])}
    switch_ids = train.get("entry_switches", [])
    switch_id = switch_ids[index] if index < len(switch_ids) else None
    switch = switches.get(switch_id) if switch_id else None
    required_tracks = train.get("required_tracks", [])
    required_track = required_tracks[index] if index < len(required_tracks) else None
    if switch_id and switch is None:
        issues.append(_issue("MISSING_SWITCH_STATE", f"Switch {switch_id} is absent from the snapshot.", train_id, switch_id))
    elif switch and switch.get("failed") and (not required_track or switch.get("position") != required_track.split("-")[-1]):
        issues.append(_issue("SWITCH_ROUTE_UNAVAILABLE", f"Failed switch {switch_id} is locked at {switch.get('position')}; requested route is unavailable.", train_id, switch_id))

    segment_id = infra["blocks"].get(block_id, {}).get("segment_id")
    segment = infra["segments"].get(segment_id, {})
    if segment.get("direction_lock") == "one_direction_at_a_time" and signal:
        direction = infra["signals"].get(signal_id, {}).get("entry_direction_from")
        for other in snapshot.get("trains", []):
            other_block = other.get("block_id")
            if other.get("train_id") == train_id or not other_block:
                continue
            if infra["blocks"].get(other_block, {}).get("segment_id") != segment_id:
                continue
            other_index = int(other.get("block_index", -1))
            other_signals = other.get("entry_signals", [])
            other_signal_id = other_signals[other_index] if 0 <= other_index < len(other_signals) else None
            other_direction = infra["signals"].get(other_signal_id, {}).get("entry_direction_from")
            if direction and other_direction and direction != other_direction:
                issues.append(_issue("DIRECTION_LOCK", f"Opposing train {other['train_id']} occupies segment {segment_id}.", train_id, segment_id))
                break

    return ValidationResult(not issues, tuple(issues))


def validate_plan(
    snapshot: dict[str, Any],
    plan: dict[str, Any],
    infrastructure: dict[str, Any] | None = None,
) -> ValidationResult:
    """Independently check plan reservations for capacity, direction and closures.

    Reservation schema: {train_id, resource_type, resource_id, start, end,
    direction?, entry_signal_id?}. Intervals use [start, end).
    """
    if getattr(plan, "schema_version", None) == "dispatch-2.0" or (isinstance(plan, dict) and plan.get("schema_version") == "dispatch-2.0"):
        from .dispatch import validate_dispatch_plan
        return validate_dispatch_plan(snapshot, plan, infrastructure)
    infra = infrastructure or load_infrastructure()
    issues: list[ValidationIssue] = []
    trains = {t["train_id"]: t for t in snapshot.get("trains", [])}
    incident_rows = snapshot.get("active_incidents", []) + snapshot.get("planned_incidents", [])
    if plan.get("snapshot_version") != snapshot.get("version"):
        issues.append(_issue("STALE_PLAN", f"Plan snapshot_version {plan.get('snapshot_version')} does not match current version {snapshot.get('version')}."))
    reservations: list[dict[str, Any]] = []

    for item in plan.get("reservations", []):
        train_id, kind, resource_id = item.get("train_id"), item.get("resource_type"), item.get("resource_id")
        if train_id not in trains:
            issues.append(_issue("UNKNOWN_TRAIN", f"Unknown train {train_id!r} in reservation.", train_id, resource_id))
            continue
        if kind not in {"block", "station_track", "direction_lock"}:
            issues.append(_issue("UNKNOWN_RESOURCE_TYPE", f"Unknown resource_type {kind!r}.", train_id, resource_id))
            continue
        table = {"block": infra["blocks"], "station_track": infra["station_tracks"]}.get(kind)
        if table is not None and resource_id not in table:
            issues.append(_issue("UNKNOWN_RESOURCE", f"Unknown {kind} {resource_id!r}.", train_id, resource_id))
            continue
        if kind == "direction_lock" and resource_id not in infra["segments"]:
            issues.append(_issue("UNKNOWN_RESOURCE", f"Unknown direction-lock segment {resource_id!r}.", train_id, resource_id))
            continue
        try:
            start, end = _time(item["start"]), _time(item["end"])
        except (KeyError, TypeError, ValueError):
            issues.append(_issue("INVALID_INTERVAL", "Reservation needs timezone-aware start and end timestamps.", train_id, resource_id))
            continue
        if end <= start:
            issues.append(_issue("INVALID_INTERVAL", "Reservation end must be after start.", train_id, resource_id))
            continue
        normalized = {**item, "_start": start, "_end": end}
        if kind == "block":
            train = trains[train_id]
            route = train.get("route", [])
            if resource_id not in route:
                issues.append(_issue("BLOCK_NOT_ON_ROUTE", f"Block {resource_id} is not on train {train_id}'s route.", train_id, resource_id))
                continue
            route_index = route.index(resource_id)
            if item.get("route_index") is not None and int(item["route_index"]) != route_index:
                issues.append(_issue("ROUTE_INDEX_MISMATCH", f"Block {resource_id} has route index {route_index}, not {item['route_index']}.", train_id, resource_id))
                continue
            switch_ids = train.get("entry_switches", [])
            required_tracks = train.get("required_tracks", [])
            switch_id = switch_ids[route_index] if route_index < len(switch_ids) else None
            switch_state = next((s for s in snapshot.get("switches", []) if s.get("switch_id") == switch_id), None)
            required = required_tracks[route_index] if route_index < len(required_tracks) else None
            if switch_state and switch_state.get("failed") and (not required or switch_state.get("position") != required.split("-")[-1]):
                switch_failure = next((failure for failure in incident_rows
                                       if failure.get("type") == "SWITCH_FAILURE"
                                       and failure.get("switch_id") == switch_id), None)
                if switch_failure is None:
                    issues.append(_issue("SWITCH_ROUTE_UNAVAILABLE", f"Failed switch {switch_id} is locked at {switch_state.get('position')}; route to {resource_id} is unavailable.", train_id, switch_id))
                else:
                    failure_start = _time(switch_failure.get("at", snapshot["virtual_time"]))
                    failure_end = failure_start + timedelta(minutes=int(switch_failure.get("duration_min", 0)))
                    if failure_start <= start < failure_end:
                        issues.append(_issue("SWITCH_ROUTE_UNAVAILABLE", f"Entry to {resource_id} is unavailable while switch {switch_id} is locked.", train_id, switch_id))
        reservations.append(normalized)

    reserved_route_indexes: dict[str, set[int]] = {}
    for item in reservations:
        if item["resource_type"] == "block":
            route = trains[item["train_id"]].get("route", [])
            reserved_route_indexes.setdefault(item["train_id"], set()).add(route.index(item["resource_id"]))
    for train_id, train in trains.items():
        if train.get("status") == "completed":
            continue
        first_unplanned = max(0, int(train.get("block_index", -1)) + 1)
        missing = [index for index in range(first_unplanned, len(train.get("route", [])))
                   if index not in reserved_route_indexes.get(train_id, set())]
        if missing:
            issues.append(_issue("INCOMPLETE_PLAN", f"Plan omits {len(missing)} remaining route block(s) for {train_id}.", train_id))

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in reservations:
        groups.setdefault((item["resource_type"], item["resource_id"]), []).append(item)
    for (kind, resource_id), items in groups.items():
        if kind == "direction_lock":
            continue
        table = infra["blocks"] if kind == "block" else infra["station_tracks"]
        capacity = int(table[resource_id].get("demo_capacity_trains", 1))
        points = []
        for item in items:
            points.extend(((item["_start"], 1, item), (item["_end"], -1, item)))
        points.sort(key=lambda point: (point[0], point[1]))
        active: list[dict[str, Any]] = []
        for _, delta, item in points:
            if delta < 0:
                active = [candidate for candidate in active if candidate is not item]
            else:
                active.append(item)
                if len(active) > capacity:
                    issues.append(_issue("RESOURCE_CAPACITY", f"{kind} {resource_id} exceeds capacity {capacity}.", item["train_id"], resource_id))
                    break

    by_segment: dict[str, list[dict[str, Any]]] = {}
    for item in reservations:
        if item["resource_type"] == "direction_lock":
            segment_id = item["resource_id"]
        elif item["resource_type"] == "block":
            segment_id = infra["blocks"][item["resource_id"]]["segment_id"]
        else:
            continue
        if infra["segments"].get(segment_id, {}).get("direction_lock") == "one_direction_at_a_time":
            by_segment.setdefault(segment_id, []).append(item)
    for segment_id, items in by_segment.items():
        for index, left in enumerate(items):
            for right in items[index + 1:]:
                overlap = left["_start"] < right["_end"] and right["_start"] < left["_end"]
                left_direction, right_direction = left.get("direction"), right.get("direction")
                if overlap and left["train_id"] != right["train_id"] and left_direction and right_direction and left_direction != right_direction:
                    issues.append(_issue("DIRECTION_LOCK", f"Opposing reservations overlap on segment {segment_id}.", right["train_id"], segment_id))

    route_reservations: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for item in reservations:
        if item["resource_type"] != "block":
            continue
        route = trains[item["train_id"]].get("route", [])
        route_reservations.setdefault(item["train_id"], []).append((route.index(item["resource_id"]), item))
    for train_id, items in route_reservations.items():
        items.sort(key=lambda pair: (pair[0], pair[1]["_start"]))
        for (left_index, left), (right_index, right) in zip(items, items[1:]):
            if left_index < right_index and left["_end"] > right["_start"]:
                issues.append(_issue("ROUTE_ORDER", f"Train {train_id} reserves a later route block before the previous block is released.", train_id, right["resource_id"]))

    now = _time(snapshot["virtual_time"])
    blocks = {b["block_id"]: b for b in snapshot.get("blocks", [])}
    for item in reservations:
        if item["resource_type"] != "block":
            continue
        block_id, train_id = item["resource_id"], item["train_id"]
        block_state = blocks.get(block_id)
        closure_known = False
        train = trains[train_id]
        for incident in incident_rows:
            if incident.get("type") == "BLOCK_CLOSURE" and incident.get("block_id") == block_id:
                closure_known = True
                start = _time(incident.get("at", snapshot["virtual_time"]))
                end = start + timedelta(minutes=int(incident.get("duration_min", 0)))
                if start <= item["_start"] < end:
                    issues.append(_issue("BLOCK_CLOSED", f"Entry occurs during closure {incident.get('incident_id')} for {block_id}.", train_id, block_id))
            if incident.get("type") == "SIGNAL_FAILURE":
                signal_ids = train.get("entry_signals", [])
                route = train.get("route", [])
                block_index = route.index(block_id) if block_id in route else -1
                signal_id = signal_ids[block_index] if 0 <= block_index < len(signal_ids) else None
                if signal_id and signal_id == incident.get("signal_id"):
                    start = _time(incident.get("at", snapshot["virtual_time"]))
                    end = start + timedelta(minutes=int(incident.get("duration_min", 0)))
                    if start <= item["_start"] < end:
                        issues.append(_issue("SIGNAL_NOT_CLEAR", f"Entry occurs during failed signal {signal_id}.", train_id, signal_id))
        if item["_start"] <= now:
            route = train.get("route", [])
            route_index = route.index(block_id) if block_id in route else -1
            signal_ids = train.get("entry_signals", [])
            signal_id = signal_ids[route_index] if 0 <= route_index < len(signal_ids) else None
            signal_state = next((s for s in snapshot.get("signals", []) if s.get("signal_id") == signal_id), None)
            if signal_state and signal_state.get("aspect") != "CLEAR":
                issues.append(_issue("SIGNAL_NOT_CLEAR", f"Signal {signal_id} is {signal_state.get('aspect')} at the planned entry time.", train_id, signal_id))
        if block_state and block_state.get("closed") and not closure_known and item["_start"] <= now:
            issues.append(_issue("BLOCK_CLOSED", f"Reservation enters currently closed block {block_id}.", train_id, block_id))
        if block_state and block_state.get("occupied_by") not in (None, train_id):
            occupant = trains.get(block_state["occupied_by"])
            release = now
            if occupant:
                index = int(occupant.get("block_index", -1))
                durations = occupant.get("block_seconds", [])
                if 0 <= index < len(durations):
                    remaining = remaining_block_seconds(occupant)
                    release = now + timedelta(seconds=remaining)
                else:
                    release = item["_end"]
            if item["_start"] < release:
                issues.append(_issue("BLOCK_OCCUPIED", f"Block {block_id} remains occupied by {block_state.get('occupied_by')} at the planned entry time.", train_id, block_id))

    return ValidationResult(not issues, tuple(issues))
