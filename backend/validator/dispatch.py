"""Independent validation gate for both full-plan policies."""
from __future__ import annotations

from backend.planner.context import PlanningContext, timestamp
from backend.planner.models import DispatchPlan, DispatchValidation, PlanningConfig, Violation
from .state import occupants


def validate_dispatch_plan(snapshot, plan, infrastructure=None) -> DispatchValidation:
    data = plan.to_dict() if isinstance(plan, DispatchPlan) else plan
    try:
        ctx = PlanningContext(snapshot, PlanningConfig(**data["config"]), infrastructure)
    except (KeyError, TypeError, ValueError) as exc:
        return DispatchValidation(violations=[Violation("INVALID_INPUT", str(exc))])
    report = DispatchValidation(violations=list(ctx.violations),
        validation_scope=["BLOCK", "DIRECTION", "INCIDENT", "STATION_TRACK", "ROUTE_ORDER",
                          "MINIMUM_TRAVEL_TIME", "MINIMUM_DWELL", "HEADWAY", "TRAIN_TIME"],
        unverified_scope=sorted(ctx.unverified))
    if "STATION_TRACK_OCCUPANCY" in ctx.unverified:
        report.warnings.append("station_track_occupancy_unverified")

    def fail(code, reason, resource=None, tids=None, start=None, end=None):
        report.violations.append(Violation(code, reason, resource, tids or [], start, end))

    for key in ("scenario_id", "seed", "run_id", "dataset_version", "snapshot_version"):
        if data.get(key) != snapshot.get(key):
            fail("STALE_PLAN", f"Plan {key} does not match snapshot")
    if data.get("planning_horizon_start") != snapshot["virtual_time"] or data.get("planning_horizon_end") != ctx.iso(ctx.horizon):
        fail("HORIZON_MISMATCH", "Plan horizon does not match request")
    if sorted(data.get("considered_train_ids", [])) != sorted(ctx.operations):
        fail("TRAIN_COVERAGE", "Considered train IDs do not match horizon selection")
    if sorted(data.get("deferred_train_ids", [])) != sorted(ctx.deferred):
        fail("TRAIN_COVERAGE", "Deferred train IDs do not match horizon selection")
    if data.get("solver_status") not in {"FEASIBLE", "OPTIMAL"}:
        fail("NO_CANDIDATE", "Solver has no candidate")
    if data.get("policy") not in {"FIFO", "CP_SAT"}:
        fail("UNKNOWN_POLICY", "Unsupported policy")
    normalized, by_train = [], {}
    for row in data.get("resource_intervals", []):
        tid, resource = row.get("train_id"), row.get("resource_id")
        try:
            seq = row["sequence"]
            if not isinstance(seq, int) or seq < 0:
                raise ValueError("sequence must be a nonnegative integer")
            op = ctx.operations[tid][seq]
            start = (timestamp(row["start_time"]) - ctx.base).total_seconds()
            end = (timestamp(row["end_time"]) - ctx.base).total_seconds()
            travel_end = (timestamp(row["traversal_end_time"]) - ctx.base).total_seconds()
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            fail("INVALID_INTERVAL", str(exc), resource, [tid])
            continue
        if row.get("resource_type") != op.kind or resource not in op.resources or row.get("route_index") != op.route_index:
            fail("ROUTE_ORDER", "Resource or route position differs from canonical sequence", resource, [tid])
            continue
        if row.get("direction") != op.direction or row.get("existing_occupancy") != op.existing:
            fail("RESOURCE_METADATA", "Direction/existing occupancy differs from canonical state", resource, [tid])
        if not (0 <= start < ctx.horizon and start <= travel_end <= end):
            fail("INVALID_INTERVAL", "Invalid temporal bounds", resource, [tid])
        if not op.existing and start < op.earliest:
            fail("EARLY_DEPARTURE", "Entry precedes train readiness", resource, [tid])
        if op.existing and start != 0:
            fail("RESOURCE_RELEASE", "Current occupancy must start at snapshot time", resource, [tid])
        if travel_end - start < op.duration:
            fail("MINIMUM_DWELL" if op.kind == "station_track" else "MINIMUM_TRAVEL_TIME",
                 "Duration is shorter than configured minimum", resource, [tid])
        if resource not in ctx.available_tracks(op):
            fail("TRACK_UNAVAILABLE", "Station track is unavailable", resource, [tid])
        for a, b, code in op.forbidden:
            if a <= start < b:
                fail(code, "New entry falls inside an unavailable window", resource, [tid], row["start_time"], row["end_time"])
        item = dict(row=row, op=op, start=start, end=end, travel_end=travel_end, resource=resource)
        normalized.append(item)
        by_train.setdefault(tid, []).append(item)
    for tid, ops in ctx.operations.items():
        items = sorted(by_train.get(tid, []), key=lambda r: r["op"].sequence)
        sequences = [r["op"].sequence for r in items]
        if sequences != list(range(len(items))):
            fail("ROUTE_ORDER", "Reservations must form a continuous, duplicate-free route prefix", tids=[tid])
        if ops[0].existing and (not items or not items[0]["op"].existing):
            fail("RESOURCE_RELEASE", "Initial occupancy omitted", tids=[tid])
        for left, right in zip(items, items[1:]):
            if left["end"] != right["start"] or left["travel_end"] > right["start"]:
                fail("TRAIN_TEMPORAL_CONSISTENCY", "Train must retain its resource until the next entry", right["resource"], [tid])
        if items:
            last = items[-1]
            if not last["op"].final and last["end"] < max(ctx.horizon, last["travel_end"]):
                fail("RESOURCE_RELEASE", "A partial-horizon train cannot vanish from its last resource", last["resource"], [tid])
            for index, item in enumerate(items):
                expected_hold = index == len(items) - 1 and not item["op"].final
                if item["row"].get("release_requires_replan", False) != expected_hold:
                    fail("RESOURCE_RELEASE", "Terminal holding metadata differs from the route prefix", item["resource"], [tid])
    groups = {}
    for item in normalized:
        groups.setdefault((item["op"].kind, item["resource"]), []).append(item)
    for track, tid, end in ctx.fixed_tracks:
        groups.setdefault(("station_track", track), []).append(dict(start=0, end=end, row={"train_id": tid}))
    for (kind, resource), items in groups.items():
        points = []
        for i, item in enumerate(items):
            end = item["end"] + ctx.config.headway_seconds
            if end > item["start"]:
                points.extend([(item["start"], 1, i), (end, -1, i)])
        active = set()
        for at, delta, i in sorted(points):
            if delta == -1:
                active.discard(i)
            else:
                active.add(i)
                if len(active) > ctx.capacity(kind, resource):
                    tids = sorted({items[j]["row"]["train_id"] for j in active})
                    fail("BLOCK_OVERLAP" if kind == "block" else "STATION_TRACK_OVERLAP",
                         "Capacity including release/headway buffer exceeded", resource, tids,
                         ctx.iso(at), ctx.iso(min(items[j]["end"] + ctx.config.headway_seconds for j in active)))
                    break
    for i, left in enumerate(normalized):
        a = left["op"]
        if a.kind != "block" or not ctx.locked(a.segment_id):
            continue
        for right in normalized[i + 1:]:
            b = right["op"]
            if b.kind == "block" and a.train_id != b.train_id and a.segment_id == b.segment_id and a.direction != b.direction:
                if left["start"] < right["end"] + ctx.config.headway_seconds and right["start"] < left["end"] + ctx.config.headway_seconds:
                    fail("DIRECTION_LOCK", "Opposing reservations overlap on a locked segment", a.segment_id, [a.train_id, b.train_id])
    train_plans = data.get("train_plans", [])
    if sorted(t.get("train_id", "") for t in train_plans) != sorted(ctx.trains):
        fail("TRAIN_COVERAGE", "Every snapshot train must be present exactly once")
    for tp in train_plans:
        tid = tp.get("train_id")
        rows = sorted(by_train.get(tid, []), key=lambda r: r["op"].sequence)
        if tp.get("resource_reservations", []) != [r["row"] for r in rows]:
            fail("PLAN_METADATA", "Train reservations differ from global reservations", tids=[tid])
        if tp.get("resource_sequence", []) != [r["resource"] for r in rows]:
            fail("PLAN_METADATA", "Train resource sequence differs from reservations", tids=[tid])
        final = rows[-1]["row"]["traversal_end_time"] if rows and rows[-1]["op"].final else None
        if tp.get("final_arrival_time") != final:
            fail("PLAN_METADATA", "Final arrival requires the final route resource", tids=[tid])
        if tid not in ctx.trains:
            continue
        if tp.get("route") != ctx.trains[tid].get("route", []):
            fail("PLAN_METADATA", "Train route differs from canonical input", tids=[tid])
        expected_departure = rows[0]["row"]["start_time"] if rows else None
        expected_arrival = rows[-1]["row"]["traversal_end_time"] if rows else None
        if tp.get("planned_departure") != expected_departure or tp.get("planned_arrival") != expected_arrival:
            fail("PLAN_METADATA", "Train departure/arrival differs from reservations", tids=[tid])
        holding = (max(0, rows[0]["start"] - ctx.operations[tid][0].earliest)
                   + sum(r["end"] - r["travel_end"] for r in rows)) / 60 if rows else 0.0
        if tp.get("holding_minutes") != holding:
            fail("PLAN_METADATA", "Holding minutes differ from reservations", tids=[tid])
        tracks = [{"station_id": ctx.infra["station_tracks"][r["resource"]]["station_id"],
                   "track_id": r["resource"], "train_id": tid, "start_time": r["row"]["start_time"],
                   "end_time": r["row"]["end_time"]} for r in rows if r["op"].kind == "station_track"]
        if tp.get("selected_station_tracks", []) != tracks:
            fail("PLAN_METADATA", "Selected station tracks differ from reservations", tids=[tid])
    report.valid = not report.violations
    report.fully_validated = report.valid and not report.unverified_scope
    return report


def validate_canonical_human_decision(snapshot, decision, infrastructure=None):
    from .resources import ValidationResult, _issue, load_infrastructure, validate_human_decision
    from copy import deepcopy
    version = snapshot["snapshot_version"]
    tid, resource = decision.get("train_id"), decision.get("resource_id")

    def result(code, reason):
        return ValidationResult(False, (_issue(code, reason, tid, resource),), version, resource, snapshot.get("run_id"))

    if decision.get("snapshot_version") != version or (snapshot.get("run_id") is not None and decision.get("run_id") != snapshot["run_id"]):
        return result("STALE_SNAPSHOT", "Snapshot version or run_id is stale")
    if decision.get("scenario_id", snapshot["scenario_id"]) != snapshot["scenario_id"]:
        return result("STALE_SNAPSHOT", "Scenario differs from current snapshot")
    for block in snapshot["blocks"]:
        if block.get("state_conflict") or len(occupants(block)) > int(block.get("capacity", 1)):
            return result("INITIAL_CAPACITY_CONFLICT", "Initial state already exceeds block capacity")
    infra = infrastructure or load_infrastructure()
    train = next((t for t in snapshot["trains"] if t["train_id"] == tid), None)
    if train and decision.get("action") == "GRANT_ENTRY":
        from .state import remaining_block_seconds
        now = timestamp(snapshot["virtual_time"])
        if train.get("status") == "completed":
            return result("NO_NEXT_BLOCK", "Train has completed its route")
        if train.get("hold_until") and timestamp(train["hold_until"]) > now:
            return result("TRAIN_HELD", "Train is held until the configured time")
        if train.get("current_block_id"):
            if remaining_block_seconds(train) > 0:
                return result("MINIMUM_TRAVEL_TIME", "Train has not reached the next resource")
        elif train.get("planned_start"):
            from datetime import timedelta
            departure = timestamp(train["planned_start"]) + timedelta(seconds=train.get("departure_shift_seconds", 0))
            if departure > now:
                return result("EARLY_DEPARTURE", "Train is not ready for departure")
        index = int(train.get("block_index", -1)) + 1
        if resource is None and 0 <= index < len(train.get("route", [])):
            resource = train["route"][index]
        switch_ids = train.get("entry_switches", [])
        switch_id = switch_ids[index] if 0 <= index < len(switch_ids) else None
        switch = next((s for s in snapshot["switches"] if s["switch_id"] == switch_id), None)
        if switch_id and (not switch or switch.get("position") is None or switch.get("failed") is None):
            return result("SWITCH_STATE_UNKNOWN", "Switch position/failure state is unavailable")
        required_tracks = train.get("required_tracks", [])
        required = required_tracks[index] if 0 <= index < len(required_tracks) else None
        if switch and required:
            if switch.get("available_routes") is not None and required not in switch["available_routes"]:
                return result("SWITCH_ROUTE_UNAVAILABLE", "Required track is not an available switch route")
            if switch.get("locked") and switch["position"] not in (required, required.split("-")[-1]):
                return result("SWITCH_ROUTE_UNAVAILABLE", "Switch is locked in another position")
        signal_ids = train.get("entry_signals", [])
        signal_id = signal_ids[index] if 0 <= index < len(signal_ids) else None
        signal = next((s for s in snapshot["signals"] if s["signal_id"] == signal_id), None)
        if signal and signal.get("failed"):
            return result("SIGNAL_NOT_CLEAR", "The entry signal has failed")
    if decision.get("action") == "SELECT_STATION_TRACK":
        track = next((r for r in snapshot["station_tracks"] if r.get("track_id") == resource), None)
        if not track or track.get("occupancy_source") == "UNAVAILABLE" or track.get("available") is None:
            return result("STATION_TRACK_STATE_UNKNOWN", "Station track occupancy is unverified")
        if track.get("available") is False or len([t for t in occupants(track) if t != tid]) >= int(track.get("capacity", 1)):
            return result("STATION_TRACK_OCCUPIED", "Station track is unavailable")
        if train and train.get("next_station_id") and track.get("station_id") != train["next_station_id"]:
            return result("ROUTE_TRACK_MISMATCH", "Station track does not belong to the next station")
    # Reuse the existing human action checks after a decision-free compatibility
    # projection. Canonical occupancy is checked in full before this projection.
    legacy = deepcopy(snapshot)
    legacy["version"] = version
    for train in legacy["trains"]:
        train["block_id"] = train.get("current_block_id")
    for block in legacy["blocks"]:
        others = [t for t in occupants(block) if t != tid]
        block["occupied_by"] = others[0] if len(others) >= int(block.get("capacity", 1)) else None
    for track in legacy["station_tracks"]:
        track["station_track_id"] = track.get("track_id")
        track["occupied_by"] = None  # Full capacity already checked above.
    legacy.pop("schema_version", None)
    checked = validate_human_decision(legacy, decision, infra)
    return ValidationResult(checked.valid, checked.issues, version, resource, snapshot.get("run_id"))
