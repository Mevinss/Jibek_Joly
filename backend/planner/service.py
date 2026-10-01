"""Rolling-horizon dispatch plans; never apply actions to the live simulator."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict

from .context import PlanningContext
from .models import (DispatchPlan, DispatchRequest, PlanningConfig, ResourceInterval,
                     StationTrackReservation, TrainPlan)


def _fifo(ctx: PlanningContext):
    """Event-driven FIFO. Waiting trains keep their current physical resource."""
    records, current, next_index, ready = [], {}, {}, {}
    released = {}
    for tid, ops in ctx.operations.items():
        next_index[tid], ready[tid] = 0, ops[0].earliest
        if ops[0].existing:
            record = {"op": ops[0], "resource": ops[0].resources[0], "start": 0, "end": None}
            records.append(record)
            current[tid] = record
            next_index[tid], ready[tid] = 1, ops[0].duration

    def release(tid, at):
        item = current.pop(tid)
        item["end"] = at
        key = (item["op"].kind, item["resource"])
        released.setdefault(key, []).append(at)

    at = 0
    while at < ctx.horizon:
        for tid, item in list(current.items()):
            if item["op"].final and ready[tid] <= at:
                release(tid, ready[tid])
        changed = True
        while changed:
            changed = False
            requests = sorted((tid for tid, ops in ctx.operations.items()
                               if next_index[tid] < len(ops) and ready[tid] <= at),
                              key=lambda tid: (ready[tid], -ctx.priorities[tid], tid))
            for tid in requests:
                op = ctx.operations[tid][next_index[tid]]
                if any(a <= at < b for a, b, _ in op.forbidden):
                    continue
                selected = None
                for resource in ctx.available_tracks(op):
                    used = sum(1 for other in current.values() if other["op"].kind == op.kind and other["resource"] == resource)
                    used += sum(1 for end in released.get((op.kind, resource), []) if at < end + ctx.config.headway_seconds)
                    if op.kind == "station_track":
                        used += sum(1 for r, _, end in ctx.fixed_tracks if r == resource and at < end + ctx.config.headway_seconds)
                    if used >= ctx.capacity(op.kind, resource):
                        continue
                    if op.kind == "block" and ctx.locked(op.segment_id):
                        if any(other["op"].train_id != tid and other["op"].segment_id == op.segment_id
                               and other["op"].direction != op.direction for other in current.values()):
                            continue
                        if any(r["end"] is not None and r["op"].train_id != tid and r["op"].segment_id == op.segment_id
                               and r["op"].direction != op.direction and r["end"] <= at < r["end"] + ctx.config.headway_seconds
                               for r in records):
                            continue
                    selected = resource
                    break
                if selected is None:
                    continue
                if tid in current:
                    release(tid, at)
                item = {"op": op, "resource": selected, "start": at, "end": None}
                records.append(item)
                current[tid] = item
                next_index[tid] += 1
                ready[tid] = at + op.duration
                changed = True
                if op.final and ready[tid] == at:
                    release(tid, at)
        events = [ctx.horizon]
        events.extend(r for r in ready.values() if r > at)
        events.extend(end + ctx.config.headway_seconds for times in released.values() for end in times if end + ctx.config.headway_seconds > at)
        events.extend(end + ctx.config.headway_seconds for _, _, end in ctx.fixed_tracks if end + ctx.config.headway_seconds > at)
        events.extend(b for ops in ctx.operations.values() for op in ops for _, b, _ in op.forbidden if b > at)
        at = min(events)
    for tid, item in current.items():
        item["end"] = ready[tid] if item["op"].final else max(ctx.horizon, ready[tid])
    return records, "FEASIBLE", 0.0


def _cp_sat(ctx: PlanningContext):
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    horizon, headway = ctx.horizon, ctx.config.headway_seconds
    max_duration = max((op.duration for ops in ctx.operations.values() for op in ops), default=1)
    bound = horizon + max_duration + headway
    items, groups, objectives, presences = [], {}, [], []
    for tid, ops in ctx.operations.items():
        chain = []
        for op in ops:
            key = f"{tid}:{op.sequence}"
            present = model.new_bool_var("present:" + key)
            start = model.new_int_var(0, horizon - 1, "start:" + key)
            travel_end = model.new_int_var(0, bound, "travel_end:" + key)
            end = model.new_int_var(0, bound, "release:" + key)
            model.add(travel_end == start + op.duration)
            model.add(end >= travel_end)
            model.add(start >= op.earliest).only_enforce_if(present)
            if op.existing:
                model.add(present == 1)
                model.add(start == 0)
            choices = {}
            for resource in ctx.available_tracks(op):
                chosen = model.new_bool_var(f"{key}:{resource}")
                padded_end = model.new_int_var(0, bound + headway, "padded:" + key + resource)
                size = model.new_int_var(0, bound + headway, "size:" + key + resource)
                model.add(padded_end == end + headway)
                model.add(size == padded_end - start)
                interval = model.new_optional_interval_var(start, size, padded_end, chosen, key + resource)
                groups.setdefault((op.kind, resource), []).append(interval)
                choices[resource] = chosen
            model.add(sum(choices.values()) == present)
            for n, (a, b, _) in enumerate(op.forbidden):
                before = model.new_bool_var(f"before:{key}:{n}")
                model.add(start < a).only_enforce_if([present, before])
                model.add(start >= b).only_enforce_if([present, before.Not()])
            item = dict(op=op, present=present, start=start, travel_end=travel_end, end=end, choices=choices)
            chain.append(item)
            items.append(item)
            presences.append(present)
        for i, item in enumerate(chain):
            if i + 1 < len(chain):
                following = chain[i + 1]
                model.add(following["present"] <= item["present"])
                model.add(following["start"] >= item["travel_end"]).only_enforce_if(following["present"])
                model.add(item["end"] == following["start"]).only_enforce_if(following["present"])
                terminal = following["present"].Not()
            else:
                terminal = item["present"]
            if item["op"].final:
                model.add(item["end"] == item["travel_end"])
            else:
                held = model.new_int_var(horizon, bound, f"held:{tid}:{i}")
                model.add_max_equality(held, [horizon, item["travel_end"]])
                model.add(item["end"] == held).only_enforce_if([item["present"], terminal])
        # Project the final arrival from the rolling prefix and the minimum
        # unplanned tail. This is explicitly a lower bound, never a completed run.
        total_remaining = sum(op.duration for op in ops) + ops[-1].tail_seconds
        completion = model.new_int_var(0, horizon + total_remaining + max_duration, "completion:" + tid)
        model.add(completion >= horizon + total_remaining).only_enforce_if(chain[0]["present"].Not())
        for item in chain:
            model.add(completion >= item["travel_end"] + item["op"].tail_seconds).only_enforce_if(item["present"])
            model.add(completion >= horizon + item["op"].duration + item["op"].tail_seconds).only_enforce_if(item["present"].Not())
        if ctx.due[tid] is not None:
            late = model.new_int_var(0, horizon + total_remaining + max_duration + abs(ctx.due[tid]), "late:" + tid)
            model.add_max_equality(late, [0, completion - ctx.due[tid]])
            objectives.append(ctx.weights[tid] * late)
    for resource, tid, release in ctx.fixed_tracks:
        fixed = model.new_fixed_size_interval_var(0, release + headway, f"existing-track:{resource}:{tid}")
        groups.setdefault(("station_track", resource), []).append(fixed)
    for (kind, resource), intervals in groups.items():
        capacity = ctx.capacity(kind, resource)
        if capacity == 1:
            model.add_no_overlap(intervals)
        else:
            model.add_cumulative(intervals, [1] * len(intervals), capacity)
    for i, left in enumerate(items):
        a = left["op"]
        if a.kind != "block" or not ctx.locked(a.segment_id):
            continue
        for right in items[i + 1:]:
            b = right["op"]
            if b.kind != "block" or a.train_id == b.train_id or a.segment_id != b.segment_id or a.direction == b.direction:
                continue
            before = model.new_bool_var(f"direction:{i}:{b.train_id}:{b.sequence}")
            model.add(left["end"] + headway <= right["start"]).only_enforce_if([left["present"], right["present"], before])
            model.add(right["end"] + headway <= left["start"]).only_enforce_if([left["present"], right["present"], before.Not()])
    model.minimize(sum(objectives) * (len(presences) + 1) - sum(presences))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = ctx.config.time_limit_seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = int(ctx.snapshot["seed"]) % 2147483647
    status = solver.solve(model)
    status_name = {cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE",
                   cp_model.INFEASIBLE: "INFEASIBLE", cp_model.MODEL_INVALID: "UNKNOWN",
                   cp_model.UNKNOWN: "TIMEOUT"}.get(status, "UNKNOWN")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return [], status_name, solver.wall_time * 1000
    records = [{"op": item["op"], "resource": next(r for r, v in item["choices"].items() if solver.value(v)),
                "start": solver.value(item["start"]), "end": solver.value(item["end"])}
               for item in items if solver.value(item["present"])]
    return records, status_name, solver.wall_time * 1000


def build_dispatch_plan(request: DispatchRequest, *, infrastructure: dict | None = None) -> DispatchPlan:
    if request.policy not in {"FIFO", "CP_SAT"}:
        raise ValueError("policy must be FIFO or CP_SAT")
    ctx = PlanningContext(request.snapshot, request.config, infrastructure)
    state = request.snapshot
    digest = hashlib.sha256(json.dumps({"state": state, "policy": request.policy, "config": asdict(request.config)},
                                      sort_keys=True, allow_nan=False).encode()).hexdigest()[:20]
    plan = DispatchPlan("PLAN-" + digest, state["scenario_id"], state["seed"], state["run_id"],
                        state["dataset_version"], state["snapshot_version"], request.policy,
                        state["virtual_time"], state["virtual_time"], ctx.iso(ctx.horizon), "UNKNOWN",
                        config=asdict(request.config))
    plan.considered_train_ids = sorted(ctx.operations)
    plan.deferred_train_ids = sorted(ctx.deferred)
    plan.diagnostics = {"considered_train_count": len(ctx.operations), "resource_interval_count": 0,
                        "horizon_seconds": ctx.horizon, "solver_time_limit_seconds": request.config.time_limit_seconds}
    records = []
    if ctx.violations:
        plan.solver_status = "INVALID_INPUT"
        plan.validation.violations = ctx.violations
    else:
        try:
            started = time.perf_counter()
            if request.policy == "FIFO":
                records, plan.solver_status, _ = _fifo(ctx)
                plan.solver_wall_time_ms = (time.perf_counter() - started) * 1000
            else:
                records, plan.solver_status, plan.solver_wall_time_ms = _cp_sat(ctx)
        except ImportError:
            plan.solver_status = "UNAVAILABLE"
    for item in sorted(records, key=lambda r: (r["op"].train_id, r["op"].sequence)):
        op = item["op"]
        plan.resource_intervals.append(ResourceInterval(op.kind, item["resource"], op.train_id,
            ctx.iso(item["start"]), ctx.iso(item["end"]), ctx.iso(item["start"] + op.duration),
            op.direction, op.route_index, op.sequence, op.existing,
            not op.final and not any(r["op"].train_id == op.train_id and r["op"].sequence == op.sequence + 1 for r in records)))
    projected = {}
    for tid in sorted(ctx.trains):
        rows = [r for r in plan.resource_intervals if r.train_id == tid]
        train = ctx.trains[tid]
        status = "completed" if train.get("status") == "completed" else "outside_horizon" if tid in ctx.deferred else "deferred"
        tp = TrainPlan(tid, status, list(train.get("route", [])))
        if rows:
            ops = ctx.operations[tid]
            last_op = ops[rows[-1].sequence]
            tp.status = "planned" if last_op.final else "partial_horizon"
            tp.resource_reservations = rows
            tp.resource_sequence = [r.resource_id for r in rows]
            tp.planned_departure = rows[0].start_time
            tp.planned_arrival = rows[-1].traversal_end_time
            tp.final_arrival_time = rows[-1].traversal_end_time if last_op.final else None
            tp.next_route_index = None if last_op.final else last_op.route_index + (0 if last_op.kind == "block" and last_op.tail_seconds > 0 and any(
                o.kind == "station_track" and o.route_index == last_op.route_index for o in ops[rows[-1].sequence + 1:]) else 1)
            initial_wait = max(0, ctx.offset(rows[0].start_time) - ops[0].earliest)
            tp.holding_minutes = (initial_wait + sum(max(0, ctx.offset(r.end_time) - ctx.offset(r.traversal_end_time)) for r in rows)) / 60
            tp.selected_station_tracks = [StationTrackReservation(ctx.infra["station_tracks"][r.resource_id]["station_id"],
                r.resource_id, tid, r.start_time, r.end_time) for r in rows if r.resource_type == "station_track"]
            completion = ctx.offset(rows[-1].traversal_end_time) + last_op.tail_seconds
            next_seq = last_op.sequence + 1
            if next_seq < len(ops):
                completion = max(completion, ctx.horizon + ops[next_seq].duration + ops[next_seq].tail_seconds)
        elif tid in ctx.operations:
            first = ctx.operations[tid][0]
            completion = ctx.horizon + first.duration + first.tail_seconds
        else:
            completion = None
        if completion is not None:
            projected[tid] = {"projected_final_arrival_lower_bound": ctx.iso(completion),
                "weight": ctx.weights[tid], "weighted_delay_seconds_lower_bound":
                ctx.weights[tid] * max(0, completion - ctx.due[tid]) if ctx.due[tid] is not None else None}
        plan.train_plans.append(tp)
    plan.objective_components = {"basis": "weighted_final_arrival_delay_lower_bound_seconds",
        "secondary": "maximize_planned_prefix_operations", "trains": projected,
        "completed_simulation_metric": False}
    plan.diagnostics["resource_interval_count"] = len(plan.resource_intervals)
    if plan.solver_status in {"FEASIBLE", "OPTIMAL"}:
        from backend.validator.resources import validate_plan
        plan.validation = validate_plan(state, plan, ctx.infra)
        plan.valid = plan.validation.valid
        plan.fully_validated = plan.validation.fully_validated
        plan.eligible_for_application = plan.valid and plan.fully_validated
    if not plan.valid:
        plan.fallback_used = True
        plan.fallback_reason = "No active plan returned: " + (plan.solver_status if not records else "VALIDATION_REJECTED")
        plan.resource_intervals = []
        for tp in plan.train_plans:
            tp.resource_reservations = []
            tp.resource_sequence = []
            tp.selected_station_tracks = []
            tp.planned_departure = tp.planned_arrival = tp.final_arrival_time = None
            tp.holding_minutes = 0.0
            tp.next_route_index = None
            tp.status = "rejected"
        plan.diagnostics["resource_interval_count"] = 0
    plan.plan_id = "PLAN-" + hashlib.sha256(json.dumps({"request_hash": digest,
        "intervals": [asdict(r) for r in plan.resource_intervals], "status": plan.solver_status,
        "validation": plan.validation.to_dict()}, sort_keys=True).encode()).hexdigest()[:20]
    return plan


def build_fifo_plan(snapshot, *, config: PlanningConfig | None = None, infrastructure=None) -> DispatchPlan:
    return build_dispatch_plan(DispatchRequest(snapshot, "FIFO", config or PlanningConfig()), infrastructure=infrastructure)


def build_cp_sat_plan(snapshot, *, config: PlanningConfig | None = None, infrastructure=None) -> DispatchPlan:
    return build_dispatch_plan(DispatchRequest(snapshot, "CP_SAT", config or PlanningConfig()), infrastructure=infrastructure)
