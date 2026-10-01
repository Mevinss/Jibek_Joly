"""Optional read-only snapshot providers; no fixture substituted for live state."""
from copy import deepcopy
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.connections.service import ConnectionEdge, ConnectionGraph, CascadingDelayResult, cascade_delay
from backend.eta.service import TrainETA, StationArrivalsResult, get_station_arrivals, get_train_eta
from backend.planner.models import PlanningConfig
from .service import quality_index, QualityIndexResult
from .what_if import what_if, WhatIfResult


class CascadeRequest(BaseModel):
    edges: list[dict]
    root_train_id: str
    root_delay_min: float
    source_type: str = "SYNTHETIC_DEMO"
    virtual_time: str | None = None
    max_depth: int = 4
    horizon_min: float = 60


class WhatIfRequest(BaseModel):
    snapshot: dict
    kind: str
    target_id: str
    minutes: float
    config: dict = Field(default_factory=dict)


def create_analytics_router(snapshot_provider, *, plan_provider=None, run_provider=None, infrastructure=None, **execution_options):
    router = APIRouter(prefix="/api", tags=["advisory-analytics"])

    def current():
        snapshot = snapshot_provider()
        if snapshot is None:
            raise HTTPException(503, "CURRENT_SNAPSHOT_UNAVAILABLE")
        return deepcopy(snapshot), deepcopy(plan_provider() if plan_provider else None)

    def checked(call):
        try:
            result = call()
            return result.to_dict() if hasattr(result, "to_dict") else result
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/stations/{station_id}/arrivals", response_model=StationArrivalsResult)
    def station_arrivals(station_id: str):
        snapshot, plan = current()
        return checked(lambda: get_station_arrivals(snapshot, station_id, plan, infrastructure=infrastructure))

    @router.get("/trains/{train_id}/eta", response_model=TrainETA)
    def train_eta(train_id: str, station_id: str | None = None):
        snapshot, plan = current()
        return checked(lambda: get_train_eta(snapshot, train_id, station_id, plan, infrastructure=infrastructure))

    @router.post("/analytics/cascade", response_model=CascadingDelayResult)
    def cascade(request: CascadeRequest):
        return checked(lambda: cascade_delay(ConnectionGraph([ConnectionEdge(**e) for e in request.edges], request.source_type),
            request.root_train_id, request.root_delay_min, virtual_time=request.virtual_time,
            max_depth=request.max_depth, horizon_min=request.horizon_min))

    @router.get("/quality-index", response_model=QualityIndexResult)
    def quality():
        run = run_provider() if run_provider else None
        if run is None:
            raise HTTPException(503, "OBSERVED_RUN_UNAVAILABLE")
        snapshot, _ = current()
        from backend.evaluation.service import digest
        if run.initial_conditions["snapshot_hash"] != digest(snapshot):
            raise HTTPException(409, "RUN_DOES_NOT_MATCH_CURRENT_SNAPSHOT")
        return checked(lambda: quality_index(run))

    @router.post("/what-if", response_model=WhatIfResult)
    def counterfactual(request: WhatIfRequest):
        return checked(lambda: what_if(request.snapshot, request.kind, request.target_id, request.minutes,
            config=PlanningConfig(**request.config), infrastructure=infrastructure, **execution_options))

    return router
