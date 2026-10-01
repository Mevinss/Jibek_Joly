"""Typed, JSON-serializable contracts shared by FIFO and CP-SAT v2."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Literal

from backend.simulator.state_contract import CanonicalScenarioSnapshot


@dataclass(frozen=True)
class PlanningConfig:
    horizon_seconds: int = 3600
    time_limit_seconds: float = 5.0
    headway_seconds: int = 0
    category_weights: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if type(self.horizon_seconds) is not int or not 1 <= self.horizon_seconds <= 3600:
            raise ValueError("horizon_seconds must be in [1, 3600]")
        if not math.isfinite(self.time_limit_seconds) or not 0 < self.time_limit_seconds <= 5:
            raise ValueError("time_limit_seconds must be in (0, 5]")
        if type(self.headway_seconds) is not int or not 0 <= self.headway_seconds <= self.horizon_seconds:
            raise ValueError("headway_seconds must be in [0, horizon_seconds]")
        if any(not isinstance(w, int) or not 1 <= w <= 1000 for w in self.category_weights.values()):
            raise ValueError("category weights must be integer values in [1, 1000]")


@dataclass(frozen=True)
class DispatchRequest:
    snapshot: CanonicalScenarioSnapshot
    policy: Literal["FIFO", "CP_SAT"]
    config: PlanningConfig = field(default_factory=PlanningConfig)


@dataclass(frozen=True)
class Violation:
    type: str
    reason: str
    resource_id: str | None = None
    train_ids: list[str] = field(default_factory=list)
    start: str | None = None
    end: str | None = None


@dataclass
class DispatchValidation:
    valid: bool = False
    fully_validated: bool = False
    violations: list[Violation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    validation_scope: list[str] = field(default_factory=list)
    unverified_scope: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResourceInterval:
    resource_type: str
    resource_id: str
    train_id: str
    start_time: str
    end_time: str
    traversal_end_time: str
    direction: str | None
    route_index: int
    sequence: int
    existing_occupancy: bool = False
    release_requires_replan: bool = False


@dataclass(frozen=True)
class StationTrackReservation:
    station_id: str
    track_id: str
    train_id: str
    start_time: str
    end_time: str


@dataclass
class TrainPlan:
    train_id: str
    status: str
    route: list[str]
    resource_sequence: list[str] = field(default_factory=list)
    planned_departure: str | None = None
    planned_arrival: str | None = None
    final_arrival_time: str | None = None
    holding_minutes: float = 0.0
    selected_station_tracks: list[StationTrackReservation] = field(default_factory=list)
    resource_reservations: list[ResourceInterval] = field(default_factory=list)
    next_route_index: int | None = None


@dataclass
class DispatchPlan:
    plan_id: str
    scenario_id: str
    seed: int
    run_id: str | None
    dataset_version: str
    snapshot_version: int
    policy: str
    created_at: str
    planning_horizon_start: str
    planning_horizon_end: str
    solver_status: str
    solver_wall_time_ms: float = 0.0
    schema_version: str = "dispatch-2.0"
    advisory: bool = True
    source_type: str = "SIMULATED_DEMO"
    valid: bool = False
    fully_validated: bool = False
    eligible_for_application: bool = False
    fallback_used: bool = False
    fallback_reason: str | None = None
    train_plans: list[TrainPlan] = field(default_factory=list)
    resource_intervals: list[ResourceInterval] = field(default_factory=list)
    validation: DispatchValidation = field(default_factory=DispatchValidation)
    considered_train_ids: list[str] = field(default_factory=list)
    deferred_train_ids: list[str] = field(default_factory=list)
    objective_components: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
