"""Independent fork execution and strict runtime comparison."""
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import hashlib
import json
from time import perf_counter

from backend.planner.apply import prepare_fork_schedule
from backend.planner.context import PlanningContext, timestamp
from backend.planner.models import PlanningConfig
from backend.planner.service import build_cp_sat_plan, build_fifo_plan
from backend.speed_profile.advisory import energy_proxy
from backend.validator.resources import validate_plan
from .models import CompareResult, DispatchRunResult, TrainRunResult
from .runtime import ExecutorUnavailable, BlockRouteEngineFork


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def aggregate_energy(components: list[dict] | None) -> float | None:
    """Measured components only; advice-before/after estimates are not observations."""
    return None if components is None else round(sum(energy_proxy(**c) for c in components), 8)


def execute_plan(snapshot: dict, plan, *, policy=None, infrastructure=None,
                 executor_factory=BlockRouteEngineFork, incident_id=None, human_decisions=()) -> DispatchRunResult:
    initial = deepcopy(snapshot)
    data = deepcopy(plan.to_dict() if hasattr(plan, "to_dict") else plan)
    config = PlanningConfig(**data["config"])
    checked = validate_plan(initial, data, infrastructure)
    conditions = dict(scenario_id=initial["scenario_id"], seed=initial["seed"],
        dataset_version=initial["dataset_version"], initial_snapshot_version=initial["snapshot_version"],
        snapshot_hash=digest(initial), incidents_hash=digest([initial["active_incidents"], initial.get("planned_incidents", [])]),
        rules_hash=digest(dict(executor=getattr(executor_factory, "rules_id", None), infrastructure=infrastructure, config=asdict(config))),
        cohort=sorted(t["train_id"] for t in initial["trains"] if t["status"].lower() != "completed"), incident_id=incident_id)
    result = DispatchRunResult(run_id=f"{initial.get('run_id') or 'FORK'}:{policy or data['policy']}:{data['plan_id']}",
        scenario_id=initial["scenario_id"], seed=initial["seed"], dataset_version=initial["dataset_version"],
        policy=policy or data["policy"], initial_snapshot_version=initial["snapshot_version"],
        started_at_virtual=initial["virtual_time"], finished_at_virtual=initial["virtual_time"],
        initial_conditions=conditions, plan_id=data["plan_id"], plan_policy=data["policy"],
        planning_config=asdict(config), movement_rules_id=getattr(executor_factory, "rules_id", None),
        validation=checked.to_dict(), planner_ms=data["solver_wall_time_ms"],
        fallback_count=int(data["fallback_used"]), fallback_reason=data["fallback_reason"],
        auto_fifo_timeout_count=sum(d.get("action") == "AUTO_FIFO_TIMEOUT" for d in human_decisions))
    if not checked.valid or not checked.fully_validated:
        result.status = "INVALID_PLAN" if not checked.valid else "UNVERIFIED_PLAN"
        result.termination_reason = "FORK_PLAN_UNVERIFIED"
        result.conflict_count = len(checked.violations) if not checked.valid else None
        return result
    if not conditions["cohort"]:
        result.termination_reason = "NO_ELIGIBLE_TRAINS"
        return result
    if not getattr(executor_factory, "rules_id", None):
        raise ValueError("executor_factory must declare a stable rules_id")
    schedule = prepare_fork_schedule(initial, data, infrastructure=infrastructure)
    try:
        fork = executor_factory(deepcopy(initial), deepcopy(data), deepcopy(schedule))
    except (ExecutorUnavailable, KeyError) as exc:
        result.status, result.termination_reason = "EXECUTOR_UNAVAILABLE", str(exc)
        return result
    ctx = PlanningContext(initial, config, infrastructure)
    by_id = {t["train_id"]: t for t in initial["trains"]}
    if len(by_id) != len(initial["trains"]):
        raise ValueError("duplicate canonical train IDs")
    incidents = initial["active_incidents"] + initial.get("planned_incidents", [])
    selected = next((i for i in incidents if i["incident_id"] == incident_id), None) if incident_id else min(incidents, key=lambda i: timestamp(i["at"]), default=None)
    if incident_id and selected is None:
        raise ValueError("unknown baseline incident_id")
    baseline_at = timestamp(selected["at"]) if selected else None
    measurements = {}
    for tid in conditions["cohort"]:
        row = by_id[tid]
        due = ctx.due.get(tid)
        baseline = row.get("delay_at_incident_min") if baseline_at and baseline_at < ctx.base else None
        if baseline_at == ctx.base:
            baseline = row.get("delay_min")
        measurements[tid] = TrainRunResult(tid, scheduled_final_arrival=row.get("scheduled_final_arrival") or (ctx.iso(due) if due is not None else None),
            delay_at_incident_min=baseline, priority_weight=ctx.weights[tid], category=row.get("category"))
    previous = fork.snapshot()
    if any(previous.get(k) != initial[k] for k in ("scenario_id", "seed", "virtual_time")):
        raise ValueError("fork did not preserve initial provenance")
    if previous.get("version", previous.get("snapshot_version")) != initial["snapshot_version"]:
        raise ValueError("fork did not preserve snapshot version")
    if {t["train_id"] for t in previous["trains"]} != set(by_id):
        raise ValueError("fork did not preserve train cohort")
    violations = {}
    monitoring_complete = True
    observed_since = {t["train_id"]: previous["virtual_time"] for t in previous["trains"] if t.get("block_id")}
    last_blocks = {t["train_id"]: t.get("block_id") for t in previous["trains"]}
    last_indices = {t["train_id"]: t.get("block_index") for t in previous["trains"]}
    began = perf_counter()
    for _ in range(config.horizon_seconds):
        frame = fork.advance(1)
        monitoring_complete = monitoring_complete and isinstance(frame.get("runtime_violations"), list)
        at = timestamp(frame["virtual_time"])
        if at != timestamp(previous["virtual_time"]) + timedelta(seconds=1):
            raise ValueError("fork must advance exactly one virtual second")
        old = {t["train_id"]: t for t in previous["trains"]}
        for row in frame["trains"]:
            tid = row["train_id"]
            if tid not in measurements:
                continue
            measure = measurements[tid]
            if baseline_at and timestamp(previous["virtual_time"]) < baseline_at <= at:
                measure.delay_at_incident_min = row.get("delay_min")
            if row["status"].lower() in {"held", "waiting"} and not measure.completed:
                measure.holding_minutes += 1 / 60
                if old[tid]["status"].lower() == "running":
                    measure.full_stop_count += 1
                result.runtime_events.append(dict(type="WAIT_OBSERVED", train_id=tid, at=frame["virtual_time"],
                    status=row["status"], reason="UNATTRIBUTED_MOVEMENT_WAIT"))
            if row.get("block_id") != last_blocks[tid] or row.get("block_index") != last_indices[tid]:
                if last_blocks[tid]:
                    result.resource_observations.append(dict(resource_type="block", resource_id=last_blocks[tid], train_id=tid,
                        start_time=observed_since.pop(tid), end_time=frame["virtual_time"]))
                if row.get("block_id"):
                    observed_since[tid] = frame["virtual_time"]
                last_blocks[tid] = row.get("block_id")
                last_indices[tid] = row.get("block_index")
            if row["status"].lower() == "completed" and not measure.completed:
                measure.completed, measure.termination_reason = True, "DESTINATION_REACHED"
                measure.actual_final_arrival = frame["virtual_time"]
                if measure.scheduled_final_arrival:
                    measure.final_delay_min = max(0, (at - timestamp(measure.scheduled_final_arrival)).total_seconds() / 60)
                    if measure.delay_at_incident_min is not None:
                        measure.added_delay_after_incident_min = max(0, measure.final_delay_min - measure.delay_at_incident_min)
            # A future station-capable executor can supply measured telemetry.
            if "energy_components" in row:
                measure.energy_proxy_units = aggregate_energy(row["energy_components"])
            if "full_stop_avoided" in row:
                measure.full_stop_avoided = row["full_stop_avoided"]
        for violation in frame.get("runtime_violations", []):
            violations[digest(violation)] = deepcopy(violation)
        result.runtime_events.extend(deepcopy(frame.get("events", [])))
        previous = frame
        if all(m.completed for m in measurements.values()):
            break
    result.simulation_ms = round((perf_counter() - began) * 1000, 3)
    result.finished_at_virtual = previous["virtual_time"]
    for tid, start in observed_since.items():
        result.resource_observations.append(dict(resource_type="block", resource_id=last_blocks[tid], train_id=tid,
            start_time=start, end_time=result.finished_at_virtual, censored=True))
    result.train_results = list(measurements.values())
    result.runtime_violations = list(violations.values())
    result.conflict_count = len(checked.violations) + len(violations) if monitoring_complete else None
    result.valid = checked.valid and not violations and monitoring_complete
    result.safety_scope_complete = checked.fully_validated and monitoring_complete
    result.status = "COMPLETED" if all(m.completed for m in result.train_results) else "HORIZON_REACHED"
    result.termination_reason = "ALL_ELIGIBLE_TRAINS_COMPLETED" if result.status == "COMPLETED" else "OUTSIDE_HORIZON"
    known = [m.final_delay_min for m in result.train_results if m.final_delay_min is not None]
    result.completed_delay_subtotal_min = sum(known) if known else None
    # The comparable total requires the entire initial cohort and known final schedules.
    if result.status == "COMPLETED" and len(known) == len(result.train_results):
        result.total_arrival_delay_min = sum(known)
        result.weighted_delay_min = sum(m.final_delay_min * m.priority_weight for m in result.train_results)
        added = [m.added_delay_after_incident_min for m in result.train_results]
        result.added_delay_after_incident_min = sum(added) if all(v is not None for v in added) else None
    result.stop_count = sum(m.full_stop_count for m in result.train_results)
    avoided = [m.full_stop_avoided for m in result.train_results]
    result.full_stop_avoided_count = sum(avoided) if all(v is not None for v in avoided) else None
    energy = [m.energy_proxy_units for m in result.train_results]
    result.energy_proxy_units = sum(energy) if all(v is not None for v in energy) else None
    return result


def assert_same_initial_conditions(runs):
    keys = ("scenario_id", "seed", "dataset_version", "initial_snapshot_version", "snapshot_hash", "incidents_hash", "rules_hash", "cohort", "incident_id")
    checks = {key: bool(runs) and all(key in r.initial_conditions and r.initial_conditions.get(key) == runs[0].initial_conditions.get(key) for r in runs)
              and (key == "incident_id" or runs[0].initial_conditions.get(key) is not None) for key in keys}
    checks["provenance_consistent"] = bool(runs) and all(all(getattr(r, key) == r.initial_conditions.get(key)
        for key in ("scenario_id", "seed", "dataset_version", "initial_snapshot_version")) for r in runs)
    if not all(checks.values()):
        raise ValueError("COMPARISON_NOT_COMPARABLE: " + ", ".join(k for k, v in checks.items() if not v))
    return checks


def compare_runs(runs) -> CompareResult:
    runs = list(runs)
    mapped = {r.policy: r for r in runs}
    if len(mapped) != len(runs) or not set(mapped) <= {"FIFO", "CP_SAT", "HUMAN"}:
        raise ValueError("unique FIFO, CP_SAT and optional HUMAN runs required")
    try:
        checks = assert_same_initial_conditions(runs)
        same = True
    except ValueError as exc:
        checks, same = {"reason": str(exc)}, False
    comparable = same and {"FIFO", "CP_SAT"} <= set(mapped) and all(r.valid and r.status == "COMPLETED" and r.total_arrival_delay_min is not None for r in runs)
    first = runs[0] if runs else None
    result = CompareResult(first.scenario_id if same else None, first.seed if same else None,
        first.dataset_version if same else None, comparable, "COMPARABLE" if comparable else "COMPARISON_NOT_COMPARABLE",
        fifo=mapped.get("FIFO"), cp_sat=mapped.get("CP_SAT"), human=mapped.get("HUMAN"), validation=checks)
    if comparable:
        fifo, cp = result.fifo.total_arrival_delay_min, result.cp_sat.total_arrival_delay_min
        result.improvement_vs_fifo_pct = 100 * (fifo - cp) / fifo if fifo > 0 else None
        if result.human:
            result.human_minus_cp_sat_delay_min = result.human.total_arrival_delay_min - cp
    return result


def compare_policies(snapshot: dict, *, config=None, infrastructure=None,
                     executor_factory=BlockRouteEngineFork, human_plan=None, human_decisions=(), incident_id=None):
    config = config or PlanningConfig()
    runs = []
    for build in (build_fifo_plan, build_cp_sat_plan):
        initial = deepcopy(snapshot)
        plan = build(initial, config=config, infrastructure=infrastructure)
        runs.append(execute_plan(initial, plan, infrastructure=infrastructure,
            executor_factory=executor_factory, incident_id=incident_id))
    if human_plan is not None:
        # HUMAN labels execution of a supplied validated plan; it is not a new solver policy.
        runs.append(execute_plan(deepcopy(snapshot), human_plan, policy="HUMAN", infrastructure=infrastructure,
            executor_factory=executor_factory, incident_id=incident_id, human_decisions=human_decisions))
    return compare_runs(runs)
