"""Read-only dashboard bridge for the existing synthetic simulator, planner and analytics.

The full timetable and the shortened executable scenario have different cohorts.
Every response retains that distinction; no result is copied between them.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.analytics.service import quality_index
from backend.analytics.what_if import what_if
from backend.connections.service import ConnectionGraph, cascade_from_snapshot
from backend.eta.service import get_station_arrivals
from backend.evaluation.demo import short_route_demo
from backend.evaluation.service import compare_policies
from backend.planner.models import PlanningConfig
from backend.planner.service import build_cp_sat_plan, build_fifo_plan
from backend.speed_profile.advisory import build_speed_advice
from .demo.simulation import snapshot
from .demo.state_adapter import canonical_from_demo_snapshot

router = APIRouter(prefix="/api/dashboard", tags=["synthetic-dashboard"])
SHORT_CONFIG = PlanningConfig(horizon_seconds=600, time_limit_seconds=1)
FULL_CONFIG = PlanningConfig(horizon_seconds=600, time_limit_seconds=1)


class DashboardContext(BaseModel):
    elapsed_s: float = Field(0, ge=0, le=86400)
    incident: Literal["none", "closure", "restriction", "chaos"] = "none"
    incident_at_s: float = Field(0, ge=0, le=86400)
    seed: int = Field(42, ge=0, le=99999999)


class DashboardWhatIf(BaseModel):
    incident_type: str
    resource_id: str
    start_time: str | None = None
    duration_min: int = Field(15, ge=1, le=60)
    scenario_id: str | None = None
    seed: int | None = None
    snapshot_version: int | None = None


def full_state(context: DashboardContext):
    demo = snapshot(context.elapsed_s, context.incident, context.incident_at_s)
    return canonical_from_demo_snapshot(demo, context.seed)


@lru_cache(maxsize=1)
def short_comparison():
    return compare_policies(short_route_demo(), config=SHORT_CONFIG)


@lru_cache(maxsize=1)
def short_plan():
    return build_fifo_plan(short_route_demo(), config=SHORT_CONFIG)


def compare_payload(result, cohort_size: int):
    return {**result.to_dict(), "source_type": "SIMULATED_DEMO", "cohort_size": cohort_size,
            "scope": "SHORT_ROUTE_ENGINE_RUN" if cohort_size == 3 else "FULL_TIMETABLE_NOT_EXECUTABLE"}


def advice_for(state, train_id: str, plan):
    train = next((row for row in state["trains"] if row["train_id"] == train_id), None)
    if train is None:
        raise HTTPException(404, "TRAIN_NOT_FOUND")
    next_index = max(0, int(train.get("block_index", -1)) + 1)
    route = train.get("route", [])
    if not route:
        raise HTTPException(422, "TRAIN_ROUTE_UNAVAILABLE")
    target = route[min(next_index, len(route) - 1)]
    return build_speed_advice(state, train_id, plan, target_resource_id=target,
                              distance_to_control_point_km=None,
                              segment_speed_limit_kmh=None).to_dict() | {"source_type": "SIMULATED_DEMO"}


@router.get("/short/state")
def short_state():
    return short_route_demo()


@router.post("/plan")
def full_plan(context: DashboardContext):
    return build_cp_sat_plan(full_state(context), config=FULL_CONFIG).to_dict()


@router.get("/short/plan")
def short_dispatch_plan(policy: Literal["FIFO", "CP_SAT"] = "CP_SAT"):
    state = short_route_demo()
    return (build_fifo_plan(state, config=SHORT_CONFIG) if policy == "FIFO"
            else build_cp_sat_plan(state, config=SHORT_CONFIG)).to_dict()


@router.get("/compare")
def full_compare(elapsed_s: float = Query(0, ge=0, le=86400),
                 incident: Literal["none", "closure", "restriction", "chaos"] = "none",
                 incident_at_s: float = Query(0, ge=0, le=86400),
                 seed: int = Query(42, ge=0, le=99999999)):
    state = full_state(DashboardContext(elapsed_s=elapsed_s, incident=incident,
                                        incident_at_s=incident_at_s, seed=seed))
    return compare_payload(compare_policies(state, config=FULL_CONFIG), len(state["trains"]))


@router.get("/short/compare")
def short_compare():
    return compare_payload(short_comparison(), 3)


@router.get("/stations/{station_id}/arrivals")
def full_station_arrivals(station_id: str, elapsed_s: float = Query(0, ge=0, le=86400),
                          incident: Literal["none", "closure", "restriction", "chaos"] = "none",
                          incident_at_s: float = Query(0, ge=0, le=86400),
                          seed: int = Query(42, ge=0, le=99999999)):
    state = full_state(DashboardContext(elapsed_s=elapsed_s, incident=incident,
                                        incident_at_s=incident_at_s, seed=seed))
    try:
        return get_station_arrivals(state, station_id).to_dict()
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/short/stations/{station_id}/arrivals")
def short_station_arrivals(station_id: str):
    try:
        return get_station_arrivals(short_route_demo(), station_id, short_plan()).to_dict()
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/short/trains/{train_id}/speed-advice")
def short_speed_advice(train_id: str):
    return advice_for(short_route_demo(), train_id, short_plan())


@router.get("/trains/{train_id}/speed-advice")
def full_speed_advice(train_id: str, elapsed_s: float = Query(0, ge=0, le=86400),
                      incident: Literal["none", "closure", "restriction", "chaos"] = "none",
                      incident_at_s: float = Query(0, ge=0, le=86400),
                      seed: int = Query(42, ge=0, le=99999999)):
    state = full_state(DashboardContext(elapsed_s=elapsed_s, incident=incident,
                                        incident_at_s=incident_at_s, seed=seed))
    plan = build_cp_sat_plan(state, config=FULL_CONFIG)
    return advice_for(state, train_id, plan)


@router.get("/short/cascade")
def short_cascade(train_id: str):
    state = short_route_demo()
    train = next((row for row in state["trains"] if row["train_id"] == train_id), None)
    if train is None:
        raise HTTPException(404, "TRAIN_NOT_FOUND")
    try:
        result = cascade_from_snapshot(state, ConnectionGraph([], "SIMULATED_DEMO"), train_id,
                                       float(train.get("delay_min") or 0), plan=short_plan())
        return result.to_dict()
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/short/quality")
def short_quality():
    return quality_index(short_comparison().fifo).to_dict() | {"source_type": "SIMULATED_DEMO"}


@router.post("/short/what-if")
def short_what_if(request: DashboardWhatIf):
    kinds = {"TRAIN_DELAY": "EXTRA_DELAY", "SIGNAL_FAILURE": "SIGNAL_FAILURE",
             "BLOCK_CLOSURE": "BLOCK_CLOSURE"}
    if request.incident_type not in kinds:
        raise HTTPException(422, "WHAT_IF_KIND_UNSUPPORTED")
    state = short_route_demo()
    if request.scenario_id is not None and request.scenario_id != state["scenario_id"]:
        raise HTTPException(409, "SCENARIO_ID_MISMATCH")
    if request.seed is not None and request.seed != state["seed"]:
        raise HTTPException(409, "SEED_MISMATCH")
    if request.start_time and request.start_time != state["virtual_time"][:16]:
        raise HTTPException(422, "START_TIME_MUST_MATCH_SNAPSHOT")
    if request.snapshot_version is not None and request.snapshot_version != state["snapshot_version"]:
        raise HTTPException(409, "SNAPSHOT_VERSION_MISMATCH")
    try:
        return what_if(state, kinds[request.incident_type], request.resource_id,
                       request.duration_min, config=SHORT_CONFIG).to_dict()
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
