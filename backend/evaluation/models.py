"""Observed simulation results, deliberately separate from DispatchPlan."""
from dataclasses import asdict, dataclass, field
from typing import Any


class JsonContract:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrainRunResult(JsonContract):
    train_id: str
    scheduled_final_arrival: str | None = None
    actual_final_arrival: str | None = None
    final_delay_min: float | None = None
    delay_at_incident_min: float | None = None
    added_delay_after_incident_min: float | None = None
    priority_weight: float = 1
    holding_minutes: float = 0
    full_stop_count: int = 0
    full_stop_avoided: bool | None = None
    energy_proxy_units: float | None = None
    completed: bool = False
    termination_reason: str = "OUTSIDE_HORIZON"
    category: str | None = None


@dataclass
class DispatchRunResult(JsonContract):
    run_id: str
    scenario_id: str
    seed: int
    dataset_version: str
    policy: str
    initial_snapshot_version: int
    started_at_virtual: str
    finished_at_virtual: str
    initial_conditions: dict
    plan_id: str | None = None
    plan_policy: str | None = None
    planning_config: dict = field(default_factory=dict)
    movement_rules_id: str | None = None
    status: str = "NOT_EXECUTED"
    train_results: list[TrainRunResult] = field(default_factory=list)
    total_arrival_delay_min: float | None = None
    added_delay_after_incident_min: float | None = None
    weighted_delay_min: float | None = None
    completed_delay_subtotal_min: float | None = None
    conflict_count: int | None = None
    stop_count: int | None = None
    full_stop_avoided_count: int | None = None
    energy_proxy_units: float | None = None
    planner_ms: float = 0
    simulation_ms: float | None = None
    valid: bool = False
    safety_scope_complete: bool = False
    validation: dict = field(default_factory=dict)
    runtime_violations: list[dict] = field(default_factory=list)
    runtime_events: list[dict] = field(default_factory=list)
    resource_observations: list[dict] = field(default_factory=list)
    fallback_count: int = 0
    auto_fifo_timeout_count: int = 0
    fallback_reason: str | None = None
    termination_reason: str | None = None
    source_type: str = "SIMULATED_DEMO"
    source: str = "RUNTIME_EVALUATION"
    energy_proxy_label: str = "dimensionless; unavailable without observed speed telemetry"


@dataclass
class CompareResult(JsonContract):
    scenario_id: str | None
    seed: int | None
    dataset_version: str | None
    comparable: bool
    status: str
    fifo: DispatchRunResult | None = None
    cp_sat: DispatchRunResult | None = None
    human: DispatchRunResult | None = None
    improvement_vs_fifo_pct: float | None = None
    human_minus_cp_sat_delay_min: float | None = None
    validation: dict = field(default_factory=dict)
    source: str = "RUNTIME_EVALUATION"
