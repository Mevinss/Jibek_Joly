"""CP-SAT interval scheduler. Input is explicit so API adapters can preserve contracts."""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from ..validator.resources import load_infrastructure


def build_snapshot_block_operations(
    snapshot: dict[str, Any],
    *,
    horizon_seconds: int = 24 * 60 * 60,
    infrastructure: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Expand remaining snapshot routes into block intervals.

    Station dwell windows are not in ScenarioSnapshot v1; this builder therefore
    makes a block-only plan. Callers may add explicit station_track operations.
    """
    infra = infrastructure or load_infrastructure()
    base = datetime.fromisoformat(snapshot["virtual_time"])
    if base.tzinfo is None:
        raise ValueError("snapshot.virtual_time must include a timezone offset.")
    operations: list[dict[str, Any]] = []
    for train in snapshot.get("trains", []):
        if train.get("status") == "completed":
            continue
        route = train.get("route", [])
        durations = train.get("block_seconds", [])
        block_index = int(train.get("block_index", -1))
        first = max(0, block_index + 1)
        if first >= len(route):
            continue
        if block_index < 0:
            start_at = datetime.fromisoformat(train["planned_start"])
            start_at += timedelta(seconds=int(train.get("departure_shift_seconds", 0)))
            earliest = max(0, math.ceil((start_at - base).total_seconds()))
        else:
            current_duration = durations[block_index] if block_index < len(durations) else 0
            remaining = max(0, math.ceil(int(current_duration) * (1 - float(train.get("progress", 0)))))
            earliest = remaining
            if train.get("hold_until"):
                held_until = datetime.fromisoformat(train["hold_until"])
                earliest = max(earliest, math.ceil((held_until - base).total_seconds()))
        for index in range(first, len(route)):
            block_id = route[index]
            block = infra["blocks"].get(block_id)
            if block is None:
                raise ValueError(f"unknown route block {block_id!r}")
            duration = int(durations[index]) if index < len(durations) else 0
            if duration <= 0:
                raise ValueError(f"missing positive block duration at {train['train_id']}:{index}")
            signal_ids = train.get("entry_signals", [])
            signal_id = signal_ids[index] if index < len(signal_ids) else None
            switch_ids = train.get("entry_switches", [])
            switch_id = switch_ids[index] if index < len(switch_ids) else None
            required_tracks = train.get("required_tracks", [])
            required = required_tracks[index] if index < len(required_tracks) else None
            signal = infra["signals"].get(signal_id, {}) if signal_id else {}
            operation = {
                "operation_id": f"{train['train_id']}:{index}:{block_id}",
                "train_id": train["train_id"], "resource_type": "block",
                "resource_id": block_id, "duration_seconds": duration,
                "earliest_start_offset": earliest,
                "latest_start_offset": max(earliest, horizon_seconds - duration),
                "route_index": index, "segment_id": block["segment_id"],
                "entry_signal_id": signal_id,
                "direction": signal.get("entry_direction_from"),
            }
            if switch_id:
                operation["switch_id"] = switch_id
                if required:
                    operation["required_switch_position"] = required.split("-")[-1]
            operations.append(operation)
    return operations


def solve_intervals(
    snapshot: dict[str, Any],
    operations: list[dict[str, Any]],
    *,
    time_limit_seconds: float = 5.0,
    horizon_seconds: int = 24 * 60 * 60,
    infrastructure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Schedule caller-provided block/track intervals and return an unvalidated plan.

    Operation fields: operation_id, train_id, resource_type (block or
    station_track), resource_id, duration_seconds, earliest_start_offset,
    optional latest_start_offset, direction, segment_id, entry_signal_id,
    switch_id, required_switch_position, and route_index.
    Route order is enforced for operations that include route_index. All offsets
    are seconds from snapshot.virtual_time; reservations use half-open intervals.
    """
    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:
        raise RuntimeError("CP-SAT requires the 'ortools' Python package.") from exc

    if not 0 < time_limit_seconds <= 5:
        raise ValueError("time_limit_seconds must be in (0, 5].")
    if horizon_seconds <= 0:
        raise ValueError("horizon_seconds must be positive.")
    base = datetime.fromisoformat(snapshot["virtual_time"])
    if base.tzinfo is None:
        raise ValueError("snapshot.virtual_time must include a timezone offset.")
    infra = infrastructure or load_infrastructure()
    trains = {train["train_id"]: train for train in snapshot.get("trains", [])}
    switches = {switch["switch_id"]: switch for switch in snapshot.get("switches", [])}
    blocks = {block["block_id"]: block for block in snapshot.get("blocks", [])}
    incident_rows = snapshot.get("active_incidents", []) + snapshot.get("planned_incidents", [])
    model = cp_model.CpModel()
    starts: dict[str, Any] = {}
    ends: dict[str, Any] = {}
    intervals: dict[str, Any] = {}
    by_resource: dict[tuple[str, str], list[Any]] = {}
    direction_items: dict[str, list[dict[str, Any]]] = {}
    train_route_ops: dict[str, list[tuple[int, str]]] = {}
    operation_by_id: dict[str, dict[str, Any]] = {}

    def infeasible(reason: str) -> dict[str, Any]:
        return {
            "policy": "CP_SAT", "status": "INFEASIBLE", "valid": False,
            "reason": reason, "scenario_id": snapshot.get("scenario_id"),
            "seed": snapshot.get("seed"), "snapshot_version": snapshot.get("version"),
            "solver_wall_time_seconds": 0.0, "reservations": [],
        }

    for op in operations:
        op_id = op.get("operation_id")
        train_id = op.get("train_id")
        kind = op.get("resource_type")
        resource_id = op.get("resource_id")
        if not op_id or op_id in operation_by_id:
            return infeasible(f"Missing or duplicate operation_id: {op_id!r}.")
        if train_id not in trains:
            return infeasible(f"Unknown train: {train_id!r}.")
        if kind not in {"block", "station_track"}:
            return infeasible(f"Unsupported resource_type: {kind!r}.")
        table = infra["blocks"] if kind == "block" else infra["station_tracks"]
        if resource_id not in table:
            return infeasible(f"Unknown {kind}: {resource_id!r}.")
        duration = int(op.get("duration_seconds", 0))
        earliest = max(0, int(op.get("earliest_start_offset", 0)))
        latest = min(horizon_seconds - duration, int(op.get("latest_start_offset", horizon_seconds - duration)))
        if duration <= 0 or earliest > latest:
            return infeasible(f"Invalid duration or time window for operation {op_id}.")
        switch_id = op.get("switch_id")
        switch = switches.get(switch_id) if switch_id else None
        start = model.new_int_var(earliest, latest, f"start_{op_id}")
        end = model.new_int_var(earliest + duration, latest + duration, f"end_{op_id}")
        interval = model.new_interval_var(start, duration, end, f"interval_{op_id}")
        operation_by_id[op_id] = op
        starts[op_id], ends[op_id], intervals[op_id] = start, end, interval
        by_resource.setdefault((kind, resource_id), []).append(interval)
        segment_id = op.get("segment_id")
        if segment_id is None and kind == "block":
            segment_id = infra["blocks"][resource_id]["segment_id"]
        direction = op.get("direction")
        if direction is None and op.get("entry_signal_id"):
            signal = infra["signals"].get(op["entry_signal_id"], {})
            direction = signal.get("entry_direction_from")
        if segment_id and direction:
            direction_items.setdefault(segment_id, []).append({
                "op_id": op_id, "train_id": train_id, "direction": direction,
                "start": start, "end": end,
            })
        if op.get("route_index") is not None:
            train_route_ops.setdefault(train_id, []).append((int(op["route_index"]), op_id))

    # Route order is fixed; solver only chooses feasible times.
    for route in train_route_ops.values():
        route.sort()
        for (_, previous), (_, current) in zip(route, route[1:]):
            model.add(starts[current] >= ends[previous])

    # Capacities for exclusive blocks and station tracks.
    for (kind, resource_id), items in by_resource.items():
        table = infra["blocks"] if kind == "block" else infra["station_tracks"]
        capacity = int(table[resource_id].get("demo_capacity_trains", 1))
        if capacity == 1:
            model.add_no_overlap(items)
        else:
            model.add_cumulative(items, [1] * len(items), capacity)

    # Opposing traffic may not overlap on a direction-locked segment.
    for segment_id, items in direction_items.items():
        if infra["segments"].get(segment_id, {}).get("direction_lock") != "one_direction_at_a_time":
            continue
        for index, left in enumerate(items):
            for right in items[index + 1:]:
                if left["train_id"] != right["train_id"] and left["direction"] != right["direction"]:
                    before = model.new_bool_var(f"{left['op_id']}_before_{right['op_id']}")
                    model.add(left["end"] <= right["start"]).only_enforce_if(before)
                    model.add(right["end"] <= left["start"]).only_enforce_if(before.Not())

    # Snapshot occupancy reserves the current block until its estimated remaining
    # block time. This is the simulator's block_seconds/progress, not a movement copy.
    occupied_intervals: dict[str, list[Any]] = {}
    for train in trains.values():
        block_id = train.get("block_id")
        if not block_id or block_id not in infra["blocks"]:
            continue
        represented = any(
            op.get("train_id") == train["train_id"]
            and op.get("resource_type") == "block"
            and op.get("resource_id") == block_id
            for op in operations
        )
        if represented:
            continue
        index = int(train.get("block_index", -1))
        durations = train.get("block_seconds", [])
        if index < 0 or index >= len(durations):
            release = horizon_seconds
        else:
            release = min(horizon_seconds, max(1, math.ceil(
                int(durations[index]) * (1 - float(train.get("progress", 0)))
            )))
        fixed = model.new_fixed_size_interval_var(0, release, f"occupied_{train['train_id']}_{block_id}")
        occupied_intervals.setdefault(block_id, []).append(fixed)
    for (kind, resource_id), items in by_resource.items():
        if kind == "block" and resource_id in occupied_intervals:
            model.add_no_overlap(items + occupied_intervals[resource_id])

    # A train already on a single-track segment keeps its direction lock until
    # its current block is expected to clear.
    for train in trains.values():
        block_id = train.get("block_id")
        if not block_id or block_id not in infra["blocks"]:
            continue
        segment_id = infra["blocks"][block_id]["segment_id"]
        if infra["segments"].get(segment_id, {}).get("direction_lock") != "one_direction_at_a_time":
            continue
        index = int(train.get("block_index", -1))
        signal_ids = train.get("entry_signals", [])
        signal_id = signal_ids[index] if 0 <= index < len(signal_ids) else None
        direction = infra["signals"].get(signal_id, {}).get("entry_direction_from")
        durations = train.get("block_seconds", [])
        remaining = horizon_seconds if index < 0 or index >= len(durations) else max(
            1, math.ceil(int(durations[index]) * (1 - float(train.get("progress", 0))))
        )
        if not direction:
            continue
        for item in direction_items.get(segment_id, []):
            if item["train_id"] != train["train_id"] and item["direction"] != direction:
                model.add(item["start"] >= min(horizon_seconds, remaining))

    # Incidents forbid a new entry during their active time. They do not evict a
    # train already in the block, so these are start-time windows, not occupancy
    # intervals.
    forbidden_starts: dict[str, list[tuple[int, int, str]]] = {}
    for incident in incident_rows:
        kind = incident.get("type")
        if kind not in {"BLOCK_CLOSURE", "SIGNAL_FAILURE", "SWITCH_FAILURE"}:
            continue
        block_id = incident.get("block_id")
        if kind == "SIGNAL_FAILURE":
            signal = infra["signals"].get(incident.get("signal_id"))
            block_id = signal.get("block_id") if signal else None
        if kind == "SWITCH_FAILURE":
            block_id = None
        if not block_id:
            continue
        at = datetime.fromisoformat(incident.get("at", snapshot["virtual_time"]))
        finish = at + timedelta(minutes=int(incident.get("duration_min", 0)))
        start_offset = max(0, math.floor((at - base).total_seconds()))
        end_offset = min(horizon_seconds, math.ceil((finish - base).total_seconds()))
        if end_offset <= start_offset:
            continue
        if kind in {"BLOCK_CLOSURE", "SIGNAL_FAILURE"}:
            forbidden_starts.setdefault(block_id, []).append(
                (start_offset, end_offset, str(incident.get("incident_id", block_id)))
            )

    for (kind, resource_id), items in by_resource.items():
        if kind != "block":
            continue
        block_state = blocks.get(resource_id, {})
        known_closure = any(
            incident.get("type") == "BLOCK_CLOSURE"
            and incident.get("block_id") == resource_id
            for incident in incident_rows
        )
        if block_state.get("closed") and not known_closure:
            forbidden_starts.setdefault(resource_id, []).append(
                (0, horizon_seconds, "closed snapshot block")
            )
        for op_id, op in operation_by_id.items():
            if op.get("resource_type") != "block" or op.get("resource_id") != resource_id:
                continue
            signal_id = op.get("entry_signal_id")
            if signal_id is None:
                route_index = op.get("route_index")
                route = trains[op["train_id"]].get("route", [])
                signal_ids = trains[op["train_id"]].get("entry_signals", [])
                if route_index is not None and 0 <= int(route_index) < len(route) and route[int(route_index)] == resource_id and int(route_index) < len(signal_ids):
                    signal_id = signal_ids[int(route_index)]
            for incident in incident_rows:
                if incident.get("type") != "SIGNAL_FAILURE" or incident.get("signal_id") != signal_id:
                    continue
                at = datetime.fromisoformat(incident.get("at", snapshot["virtual_time"]))
                finish = at + timedelta(minutes=int(incident.get("duration_min", 0)))
                start_offset = max(0, math.floor((at - base).total_seconds()))
                end_offset = min(horizon_seconds, math.ceil((finish - base).total_seconds()))
                if end_offset > start_offset:
                    forbidden_starts.setdefault(resource_id, []).append(
                        (start_offset, end_offset, str(incident.get("incident_id", signal_id)))
                    )
            switch_id = op.get("switch_id")
            required_position = op.get("required_switch_position")
            switch_state = switches.get(switch_id) if switch_id else None
            matching_failures = [incident for incident in incident_rows
                                 if incident.get("type") == "SWITCH_FAILURE"
                                 and incident.get("switch_id") == switch_id]
            if switch_id and required_position and switch_state and switch_state.get("position") != required_position:
                if not matching_failures and switch_state.get("failed"):
                    forbidden_starts.setdefault(resource_id, []).append(
                        (0, horizon_seconds, f"switch {switch_id} failed")
                    )
                for incident in matching_failures:
                    at = datetime.fromisoformat(incident.get("at", snapshot["virtual_time"]))
                    finish = at + timedelta(minutes=int(incident.get("duration_min", 0)))
                    start_offset = max(0, math.floor((at - base).total_seconds()))
                    end_offset = min(horizon_seconds, math.ceil((finish - base).total_seconds()))
                    if end_offset > start_offset:
                        forbidden_starts.setdefault(resource_id, []).append(
                            (start_offset, end_offset, str(incident.get("incident_id", switch_id)))
                        )
        for op_id, op in operation_by_id.items():
            if op.get("resource_type") != "block" or op.get("resource_id") != resource_id:
                continue
            for window_index, (window_start, window_end, _label) in enumerate(forbidden_starts.get(resource_id, [])):
                before = model.new_bool_var(f"entry_before_{op_id}_{window_index}")
                model.add(starts[op_id] < window_start).only_enforce_if(before)
                model.add(starts[op_id] >= window_end).only_enforce_if(before.Not())

    if not operations:
        return {
            "policy": "CP_SAT", "status": "OPTIMAL", "valid": None,
            "reason": "No operations supplied.", "scenario_id": snapshot.get("scenario_id"),
            "seed": snapshot.get("seed"), "snapshot_version": snapshot.get("version"),
            "solver_wall_time_seconds": 0.0, "reservations": [],
        }

    # Minimize sum of operation completion offsets; no synthetic quality score.
    model.minimize(sum(ends.values()))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_seconds)
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    status_names = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "TIMEOUT",
    }
    status_name = status_names.get(status, "UNKNOWN")
    result: dict[str, Any] = {
        "policy": "CP_SAT", "status": status_name,
        "scenario_id": snapshot.get("scenario_id"), "seed": snapshot.get("seed"),
        "snapshot_version": snapshot.get("version"),
        "solver_wall_time_seconds": solver.wall_time,
        "solver_time_limit_seconds": float(time_limit_seconds),
        "reservations": [],
    }
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        result.update({"valid": False, "reason": "Solver returned no feasible plan."})
        return result

    for op_id, op in operation_by_id.items():
        start_offset, end_offset = solver.value(starts[op_id]), solver.value(ends[op_id])
        reservation = {
            "train_id": op["train_id"], "resource_type": op["resource_type"],
            "resource_id": op["resource_id"],
            "start": (base + timedelta(seconds=start_offset)).isoformat(),
            "end": (base + timedelta(seconds=end_offset)).isoformat(),
        }
        segment_id = op.get("segment_id")
        if segment_id is None and op["resource_type"] == "block":
            segment_id = infra["blocks"][op["resource_id"]]["segment_id"]
        direction = op.get("direction")
        signal_id = op.get("entry_signal_id")
        route = trains[op["train_id"]].get("route", [])
        route_index = op.get("route_index")
        if op["resource_type"] == "block" and route_index is None and op["resource_id"] in route:
            route_index = route.index(op["resource_id"])
        if signal_id is None and route_index is not None:
            signal_ids = trains[op["train_id"]].get("entry_signals", [])
            if 0 <= int(route_index) < len(signal_ids):
                signal_id = signal_ids[int(route_index)]
        if direction is None and signal_id:
            direction = infra["signals"].get(signal_id, {}).get("entry_direction_from")
        if direction:
            reservation["direction"] = direction
        if segment_id:
            reservation["segment_id"] = segment_id
        if route_index is not None:
            reservation["route_index"] = int(route_index)
        if signal_id:
            reservation["entry_signal_id"] = signal_id
        result["reservations"].append(reservation)
    result["valid"] = None
    result["reason"] = "Feasible schedule; run backend.validator.validate_plan before use."
    return result


def plan_snapshot(
    snapshot: dict[str, Any],
    *,
    time_limit_seconds: float = 5.0,
    horizon_seconds: int = 24 * 60 * 60,
    infrastructure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create and solve the block-only plan derivable from ScenarioSnapshot v1."""
    infra = infrastructure or load_infrastructure()
    operations = build_snapshot_block_operations(
        snapshot, horizon_seconds=horizon_seconds, infrastructure=infra
    )
    result = solve_intervals(
        snapshot, operations, time_limit_seconds=time_limit_seconds,
        horizon_seconds=horizon_seconds, infrastructure=infra,
    )
    result["scope"] = "BLOCK_ONLY"
    result["limitations"] = [
        "Station-track reservations were not generated because snapshot v1 has no station dwell windows.",
        "Run backend.validator.validate_plan before using any feasible result.",
    ]
    return result
