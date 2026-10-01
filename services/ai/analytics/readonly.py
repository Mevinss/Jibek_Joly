"""Explicit snapshot-bound data catalog. No model calls or control actions."""
from copy import deepcopy

from backend.analytics.service import quality_index
from backend.evaluation.service import digest
from backend.eta.service import get_train_eta, get_station_arrivals
from backend.validator.resources import validate_plan


class SnapshotAnalyticsTools:
    tool_names = ("get_compare_result", "get_plan_summary", "get_train_eta", "get_station_arrivals", "get_cascade_result", "get_quality_index")
    grounding_rules = (
        "Use only returned values; missing/null means data unavailable.",
        "Connections marked SYNTHETIC_DEMO are illustrative assumptions.",
        "No fuel savings, calibrated safety probabilities or energy conversions may be inferred.",
        "Legacy p_conflict_15m is a next-segment proxy, not validated fifteen-minute risk.")

    def __init__(self, snapshot, *, plan=None, compare=None, cascade=None, run=None, infrastructure=None):
        self.snapshot, self.infrastructure = deepcopy(snapshot), deepcopy(infrastructure)
        self.plan = deepcopy(plan.to_dict() if hasattr(plan, "to_dict") else plan)
        if self.plan and not validate_plan(self.snapshot, self.plan, infrastructure).valid:
            raise ValueError("INVALID_OR_UNRELATED_PLAN")
        self.compare, self.cascade, self.run = deepcopy(compare), deepcopy(cascade), deepcopy(run)
        runs = [r for r in (getattr(compare, "fifo", None), getattr(compare, "cp_sat", None), getattr(compare, "human", None), run) if r is not None]
        if any(r.initial_conditions["snapshot_hash"] != digest(self.snapshot) for r in runs):
            raise ValueError("UNRELATED_RUN_RESULT")
        ids = {t["train_id"] for t in self.snapshot["trains"]}
        if cascade and (cascade.initial_snapshot_hash != digest(self.snapshot) or
                        ({cascade.root_train_id} | {t["train_id"] for t in cascade.affected_trains}) - ids):
            raise ValueError("CASCADE_NOT_BOUND_TO_SNAPSHOT")

    @staticmethod
    def _result(value):
        return value.to_dict() if value is not None else {"status": "UNAVAILABLE", "reason": "DATA_NOT_SUPPLIED"}

    def get_compare_result(self):
        return self._result(self.compare)

    def get_plan_summary(self):
        if self.plan is None:
            return self._result(None)
        return deepcopy({k: self.plan[k] for k in ("plan_id", "policy", "solver_status", "valid", "fully_validated", "validation", "planning_horizon_start", "planning_horizon_end", "train_plans")})

    def get_train_eta(self, train_id, station_id=None):
        return get_train_eta(self.snapshot, train_id, station_id, self.plan, infrastructure=self.infrastructure).to_dict()

    def get_station_arrivals(self, station_id):
        return get_station_arrivals(self.snapshot, station_id, self.plan, infrastructure=self.infrastructure).to_dict()

    def get_cascade_result(self):
        return self._result(self.cascade)

    def get_quality_index(self):
        return self._result(quality_index(self.run) if self.run is not None else None)

    def call(self, tool_name, **arguments):
        if tool_name not in self.tool_names:
            raise ValueError("READ_ONLY_TOOL_NOT_ALLOWED")
        return getattr(self, tool_name)(**arguments)
