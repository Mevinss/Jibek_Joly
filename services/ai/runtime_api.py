"""One-port, stateful synthetic dispatch demo built on the existing simulator.

The action candidates are bounded human holds evaluated on independent engine
forks. An advisory CP-SAT plan is reported separately and is never applied when
station-track occupancy remains unverified.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.app import active
from backend.eta.service import get_station_arrivals
from backend.planner.models import PlanningConfig
from backend.planner.service import build_cp_sat_plan, build_fifo_plan
from backend.simulator.engine import Simulator
from backend.simulator.state_contract import canonical_from_backend_snapshot, topology
from backend.speed_profile import build_speed_profile
from backend.validator.resources import validate_human_decision
from .demo.simulation import geometry

router = APIRouter(prefix="/api/runtime", tags=["unified-dispatch-demo"])
PLAN_CONFIG = PlanningConfig(horizon_seconds=1200, time_limit_seconds=1)
PREVIEW_SECONDS = 1200


class IncidentRequest(BaseModel):
    type: Literal["TRAIN_DELAY", "SIGNAL_FAILURE", "SWITCH_FAILURE", "BLOCK_CLOSURE"]
    resource_id: str
    duration_min: int = Field(5, ge=1, le=60)
    run_id: str
    snapshot_version: int


class DecisionRequest(BaseModel):
    option_id: Literal["A", "B", "C"]
    run_id: str
    snapshot_version: int
    horizon_minutes: Literal[10, 20, 30] = 20


class ControlRequest(BaseModel):
    running: bool
    speed: Literal[1, 10, 60] = 1


def canonical(simulator: Simulator, run_id: str) -> dict:
    state = canonical_from_backend_snapshot(simulator.snapshot().to_dict(),
                                            run_id=run_id, data_root=simulator.data_root)
    state["snapshot_id"] = f"{run_id}:{state['snapshot_version']}"
    state["simulation_time"] = state["virtual_time"]
    return state


def register_active_incidents(simulator: Simulator) -> None:
    """Restore dynamic incidents from the persisted canonical engine snapshot."""
    allowed = simulator.scenarios[simulator.scenario_id]["incident_ids"]
    for row in simulator.active_incidents.values():
        identifier = row["incident_id"]
        if identifier not in simulator.incident_defs:
            simulator.incident_defs[identifier] = deepcopy(row)
        if identifier not in allowed:
            allowed.append(identifier)


def fork(engine_state: dict) -> Simulator:
    clone = Simulator(engine_state["snapshot"]["scenario_id"])
    clone.restore_state(deepcopy(engine_state))
    register_active_incidents(clone)
    return clone


def health(state: dict) -> dict:
    trains = state["trains"]
    known = [float(row["delay_min"]) for row in trains if row.get("delay_min") is not None]
    average = sum(known) / len(known) if known else None
    waiting = sum(row.get("status") in ("waiting", "held", "delayed") for row in trains)
    conflicts = sum(bool(row["state_conflict"]) for row in state["blocks"])
    factors = [
        {"key": "mean_delay_min", "value": average, "penalty": min(40., average * 4) if average is not None else None},
        {"key": "waiting_trains", "value": waiting, "penalty": min(20., waiting * 2.)},
        {"key": "active_incidents", "value": len(state["active_incidents"]),
         "penalty": min(20., len(state["active_incidents"]) * 5.)},
        {"key": "block_conflicts", "value": conflicts, "penalty": min(20., conflicts * 10.)},
    ]
    score = round(100 - sum(row["penalty"] for row in factors), 1) if all(row["penalty"] is not None for row in factors) else None
    return {"status": "AVAILABLE" if score is not None else "UNAVAILABLE", "source_type": "DERIVED",
            "score": score, "factors": [{"key": row["key"], "points": row["penalty"], "value": row["value"]} for row in factors],
            "method": "DEMO_HEALTH_100_MINUS_CAPPED_DELAY_WAIT_INCIDENT_CONFLICT_PENALTIES",
            "scope": "snapshot-only; not calibrated or observed run evaluation"}


def involved(state: dict, incident: dict) -> list[str]:
    key = next((name for name in ("train_id", "block_id", "signal_id", "switch_id") if incident.get(name)), None)
    if key == "train_id":
        return [incident[key]]
    trains = []
    for train in state["trains"]:
        if train.get("status") == "completed":
            continue
        next_index = max(0, int(train.get("block_index", -1)))
        if key == "block_id" and incident[key] in train.get("route", [])[next_index:]:
            trains.append(train["train_id"])
        elif key == "signal_id" and incident[key] in train.get("entry_signals", [])[next_index:]:
            trains.append(train["train_id"])
        elif key == "switch_id" and incident[key] in train.get("entry_switches", [])[next_index:]:
            trains.append(train["train_id"])
    return trains


def hold(simulator: Simulator, train_id: str, minutes: int) -> None:
    train = simulator.trains[train_id]
    until = simulator.virtual_time + timedelta(minutes=minutes)
    if train.block_index < 0:
        train.departure_shift_seconds += minutes * 60
        train.delay_min = round(train.departure_shift_seconds / 60, 2)
        train.status = "delayed"
    else:
        previous = datetime.fromisoformat(train.hold_until) if train.hold_until else simulator.virtual_time
        train.hold_until = max(previous, until).isoformat()
        train.status = "held"


def project(engine_state: dict, run_id: str, action: dict | None, seconds: int) -> dict:
    simulator = fork(engine_state)
    if action is not None:
        hold(simulator, action["train_id"], action["hold_minutes"])
    simulator.advance(seconds)
    state = canonical(simulator, run_id)
    delays = {row["train_id"]: row.get("delay_min") for row in state["trains"]}
    weights = {"intercity": 3, "regional": 2, "freight": 1}
    weighted = sum((row.get("delay_min") or 0) * weights.get(row.get("category"), 1) for row in state["trains"])
    total = sum(row.get("delay_min") or 0 for row in state["trains"])
    return {"state": state, "metrics": {"total_delay_min": round(total, 2),
            "weighted_delay_units": round(weighted, 2),
            "conflicts": sum(row["state_conflict"] for row in state["blocks"]),
            "delays_by_train": delays, "quality": health(state)}}


def projected_eta(state: dict, train_ids: list[str]) -> dict[str, str | None]:
    """Person 3 ETA at each affected train's next station, from one fork."""
    by_id = {row["train_id"]: row for row in state["trains"]}
    stations = {by_id[train_id].get("next_station_id") for train_id in train_ids if train_id in by_id}
    arrivals = {}
    for station_id in stations - {None}:
        try:
            result = get_station_arrivals(state, station_id).to_dict()
        except (ValueError, KeyError):
            continue
        arrivals.update({row["train_id"]: row.get("eta") for row in result["arrivals"]})
    return {train_id: arrivals.get(train_id) for train_id in train_ids}


def analysis_from(engine_state: dict, run_id: str) -> dict:
    state = canonical(fork(engine_state), run_id)
    incidents = state["active_incidents"]
    latest = incidents[-1] if incidents else None
    affected = involved(state, latest) if latest else []
    fifo = build_fifo_plan(state, config=PLAN_CONFIG)
    cp_sat = build_cp_sat_plan(state, config=PLAN_CONFIG)
    baseline = project(engine_state, run_id, None, PREVIEW_SECONDS)
    candidates = [("A", None)]
    hold_minutes = min(5, int(latest.get("duration_min", 5))) if latest else 5
    for option_id, train_id in zip(("B", "C"), affected[:2]):
        candidates.append((option_id, {"action": "HOLD_TRAIN", "train_id": train_id,
                                       "hold_minutes": hold_minutes}))
    options = []
    for option_id, action in candidates:
        validation = ({"valid": True, "reason_code": "NO_ACTION"} if action is None else
                      validate_human_decision(state, {"action": "HOLD_TRAIN",
                          "train_id": action["train_id"], "snapshot_version": state["snapshot_version"],
                          "run_id": run_id}).to_dict())
        result = baseline if action is None else project(engine_state, run_id, action, PREVIEW_SECONDS)
        options.append({"id": option_id, "action": action, "validation": validation,
                        "metrics": {key: value for key, value in result["metrics"].items() if key != "delays_by_train"},
                        "affected_train_ids": affected,
                        "source_type": "SIMULATED_DEMO", "scope": "20-minute independent simulator fork"})
    feasible = [row for row in options if row["validation"]["valid"]]
    recommended = min(feasible, key=lambda row: (row["metrics"]["weighted_delay_units"], row["id"])) if feasible else None
    return {"run_id": run_id, "snapshot_id": state["snapshot_id"],
            "snapshot_version": state["snapshot_version"], "simulation_time": state["virtual_time"],
            "source_type": "SIMULATED_DEMO", "network_train_count": len(state["trains"]),
            "optimization_scope_train_ids": affected, "incident": latest,
            "options": options, "recommended_option_id": recommended["id"] if recommended else None,
            "recommendation_basis": "LOWEST_20_MIN_WEIGHTED_DELAY_INTERCITY_3_REGIONAL_2_FREIGHT_1",
            "planner": {"fifo": {"status": fifo.solver_status, "valid": fifo.valid,
                                    "fully_validated": fifo.fully_validated},
                        "cp_sat": {"status": cp_sat.solver_status, "valid": cp_sat.valid,
                                   "fully_validated": cp_sat.fully_validated,
                                   "solver_wall_time_ms": cp_sat.solver_wall_time_ms}},
            "warning": "CP-SAT is advisory and not applied when station-track occupancy is unverified"}


def require_identity(rt, run_id: str, version: int) -> None:
    if rt.run_id != run_id or rt.simulator.version != version:
        raise HTTPException(409, "STALE_RUN_OR_SNAPSHOT")


async def persist(rt, entries: list[dict]) -> None:
    stored, elapsed = await asyncio.to_thread(rt.store.append, rt.simulator.scenario_id,
                                               rt.run_id, entries, rt.simulator.export_state())
    rt.metrics.observe("SQLite_write_ms", elapsed)
    await rt.broadcast(rt.public_event(stored[-1]))


@router.get("/state")
async def state():
    rt = active()
    async with rt.lock:
        return canonical(rt.simulator, rt.run_id) | {"running": rt.running, "speed": rt.speed}


@router.get("/topology")
def infrastructure():
    return topology(geometry=geometry())


@router.get("/plan")
async def planner_advice():
    rt = active()
    async with rt.lock:
        state = canonical(rt.simulator, rt.run_id)
    plan = await run_in_threadpool(build_cp_sat_plan, state, config=PLAN_CONFIG)
    return plan.to_dict() | {"snapshot_id": state["snapshot_id"], "source_type": "SIMULATED_DEMO"}


@router.get("/stream")
async def stream(request: Request):
    rt = active()

    async def events():
        previous = None
        while not await request.is_disconnected():
            async with rt.lock:
                current = canonical(rt.simulator, rt.run_id) | {"running": rt.running, "speed": rt.speed}
            marker = (current["snapshot_id"], current["running"], current["speed"])
            if marker != previous:
                previous = marker
                payload = {"state": current, "sent_at": datetime.now(timezone.utc).isoformat()}
                yield "event: state\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
            else:
                yield ": heartbeat\n\n"
            await asyncio.sleep(.25)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/control")
async def control(request: ControlRequest):
    rt = active()
    async with rt.lock:
        rt.running = request.running
        rt.speed = request.speed
        rt.store.update_control(rt.simulator.scenario_id, rt.running, rt.speed)
        return {"running": rt.running, "speed": rt.speed, "snapshot_id": f"{rt.run_id}:{rt.simulator.version}"}


@router.post("/reset")
async def reset(scenario_id: str = "SCN-ALL"):
    rt = active()
    async with rt.lock:
        try:
            rt.simulator.reset(scenario_id)
        except KeyError:
            raise HTTPException(404, "UNKNOWN_SCENARIO") from None
        rt.run_id = rt.store.start_run(scenario_id)
        rt.running = False
        rt.speed = 1
        await persist(rt, [{"type": "RUN_RESET", "virtual_time": rt.simulator.snapshot().virtual_time,
                            "scenario_id": scenario_id}])
        return canonical(rt.simulator, rt.run_id)


@router.post("/incidents")
async def create_incident(request: IncidentRequest):
    rt = active()
    async with rt.lock:
        require_identity(rt, request.run_id, request.snapshot_version)
        key = {"TRAIN_DELAY": "train_id", "SIGNAL_FAILURE": "signal_id",
               "SWITCH_FAILURE": "switch_id", "BLOCK_CLOSURE": "block_id"}[request.type]
        table = {"train_id": rt.simulator.trains, "signal_id": rt.simulator.signals,
                 "switch_id": rt.simulator.switches, "block_id": rt.simulator.blocks}[key]
        if request.resource_id not in table:
            raise HTTPException(422, "UNKNOWN_RESOURCE")
        if any(row["type"] == request.type and row.get(key) == request.resource_id
               for row in rt.simulator.active_incidents.values()):
            raise HTTPException(409, "INCIDENT_ALREADY_ACTIVE")
        incident = {"incident_id": "UI-" + uuid4().hex[:12].upper(), "type": request.type,
                    key: request.resource_id, "at": rt.simulator.snapshot().virtual_time,
                    "duration_min": request.duration_min, "source_type": "SIMULATED_DEMO"}
        rt.simulator.incident_defs[incident["incident_id"]] = incident
        rt.simulator.scenarios[rt.simulator.scenario_id]["incident_ids"].append(incident["incident_id"])
        rt.simulator.advance(1)
        await persist(rt, [{"type": "INCIDENT_CREATED", "virtual_time": rt.simulator.snapshot().virtual_time,
                            "incident": incident}, *rt.simulator.events])
        return {"incident": incident, "state": canonical(rt.simulator, rt.run_id)}


@router.get("/analysis")
async def analyze():
    rt = active()
    async with rt.lock:
        export, run_id = deepcopy(rt.simulator.export_state()), rt.run_id
    return await run_in_threadpool(analysis_from, export, run_id)


@router.post("/preview")
async def preview(request: DecisionRequest):
    rt = active()
    async with rt.lock:
        require_identity(rt, request.run_id, request.snapshot_version)
        export, run_id = deepcopy(rt.simulator.export_state()), rt.run_id
    analysis = await run_in_threadpool(analysis_from, export, run_id)
    option = next((row for row in analysis["options"] if row["id"] == request.option_id), None)
    if option is None or not option["validation"]["valid"]:
        raise HTTPException(422, "OPTION_UNAVAILABLE")
    horizon_seconds = request.horizon_minutes * 60
    projected = await run_in_threadpool(project, export, run_id, option["action"], horizon_seconds)
    baseline = await run_in_threadpool(project, export, run_id, None, horizon_seconds)
    async with rt.lock:
        require_identity(rt, request.run_id, request.snapshot_version)
    before_eta = projected_eta(baseline["state"], analysis["optimization_scope_train_ids"])
    after_eta = projected_eta(projected["state"], analysis["optimization_scope_train_ids"])
    impacts = [{"train_id": train_id,
                "without_action_delay_min": baseline["metrics"]["delays_by_train"].get(train_id),
                "with_action_delay_min": projected["metrics"]["delays_by_train"].get(train_id),
                "without_action_eta": before_eta.get(train_id), "with_action_eta": after_eta.get(train_id)}
               for train_id in analysis["optimization_scope_train_ids"]]
    return {"snapshot_id": analysis["snapshot_id"], "option_id": request.option_id,
            "current": canonical(fork(export), run_id), "projected": projected["state"],
            "baseline_metrics": baseline["metrics"], "metrics": projected["metrics"],
            "delta_total_delay_min": round(projected["metrics"]["total_delay_min"] - baseline["metrics"]["total_delay_min"], 2),
            "train_impacts": impacts, "source_type": "SIMULATED_DEMO",
            "applied": False, "horizon_seconds": horizon_seconds}


@router.post("/apply")
async def apply(request: DecisionRequest):
    if request.option_id == "A":
        raise HTTPException(422, "NO_ACTION_CANNOT_BE_APPLIED")
    rt = active()
    async with rt.lock:
        require_identity(rt, request.run_id, request.snapshot_version)
        export, run_id = deepcopy(rt.simulator.export_state()), rt.run_id
    analysis = await run_in_threadpool(analysis_from, export, run_id)
    option = next((row for row in analysis["options"] if row["id"] == request.option_id), None)
    if option is None or not option["validation"]["valid"] or option["action"] is None:
        raise HTTPException(422, "OPTION_UNAVAILABLE")
    async with rt.lock:
        require_identity(rt, request.run_id, request.snapshot_version)
        before = canonical(rt.simulator, rt.run_id)
        decision = {"action": "HOLD_TRAIN", "train_id": option["action"]["train_id"],
                    "snapshot_version": before["snapshot_version"], "run_id": rt.run_id}
        checked = validate_human_decision(before, decision)
        if not checked.valid:
            raise HTTPException(422, checked.reason_code)
        hold(rt.simulator, option["action"]["train_id"], option["action"]["hold_minutes"])
        rt.simulator.advance(1)
        rt.store.log_human_action(rt.simulator.scenario_id, rt.run_id, "dashboard",
                                  json.dumps(option["action"]), True, "VALIDATED_HOLD", before["snapshot_version"])
        await persist(rt, [{"type": "DECISION_APPLIED", "virtual_time": rt.simulator.snapshot().virtual_time,
                            "option_id": request.option_id, "action": option["action"],
                            "previous_snapshot_id": before["snapshot_id"]}, *rt.simulator.events])
        return {"applied": True, "source_type": "SIMULATED_DEMO", "option_id": request.option_id,
                "before": before, "after": canonical(rt.simulator, rt.run_id)}


@router.get("/stations/{station_id}/arrivals")
async def station_arrivals(station_id: str):
    rt = active()
    async with rt.lock:
        state = canonical(rt.simulator, rt.run_id)
    try:
        return get_station_arrivals(state, station_id).to_dict() | {"snapshot_id": state["snapshot_id"]}
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/trains/{train_id}/speed-profile")
async def train_speed_profile(train_id: str):
    rt = active()
    async with rt.lock:
        snapshot = rt.simulator.snapshot().to_dict()
        identity = f"{rt.run_id}:{rt.simulator.version}"
        data_root = rt.simulator.data_root
    try:
        profile = await run_in_threadpool(build_speed_profile, snapshot, train_id, data_root)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    return profile | {"snapshot_id": identity, "source_type": "SIMULATED_DEMO"}


@router.get("/health-index")
async def health_index():
    rt = active()
    async with rt.lock:
        state = canonical(rt.simulator, rt.run_id)
    return health(state) | {"snapshot_id": state["snapshot_id"]}


@router.get("/history")
async def history():
    rt = active()
    async with rt.lock:
        scenario = rt.simulator.scenario_id
        current = rt.simulator.snapshot().virtual_time
        start = rt.simulator.scenarios[scenario]["start_time"]
        rows = rt.store.history(scenario, start, current, rt.run_id)
        return {"run_id": rt.run_id, "events": [row for row in rows if row["type"] != "STATE"][-100:],
                "source_type": "SIMULATED_DEMO"}


@router.get("/replay")
async def replay(at: datetime = Query(...)):
    rt = active()
    async with rt.lock:
        snapshot = rt.store.replay(rt.simulator.scenario_id, at.isoformat(), rt.run_id)
        run_id = rt.run_id
        data_root = rt.simulator.data_root
    if snapshot is None:
        raise HTTPException(404, "REPLAY_SNAPSHOT_NOT_FOUND")
    state = canonical_from_backend_snapshot(snapshot, run_id=run_id, data_root=data_root)
    state["snapshot_id"] = f"{run_id}:{state['snapshot_version']}"
    return {"state": state, "replay": True, "source_type": "SIMULATED_DEMO"}
