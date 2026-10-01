"""Validated handoff to a simulation fork; no simulator mutation or live action."""
from __future__ import annotations

from backend.validator.resources import validate_plan
from .models import DispatchPlan


def prepare_fork_schedule(snapshot: dict, plan: DispatchPlan | dict, *, infrastructure=None) -> dict:
    """Return ordered transitions only after revalidating the exact snapshot.

    Person 1 must apply each transition atomically to an isolated fork using
    its movement rules. End-of-horizon reservations never release a held train.
    This payload is not a completed simulation/evaluation result.
    """
    data = plan.to_dict() if isinstance(plan, DispatchPlan) else plan
    checked = validate_plan(snapshot, data, infrastructure)
    if not checked.valid or not getattr(checked, "fully_validated", False):
        raise ValueError("FORK_PLAN_UNVERIFIED: " + str(checked.to_dict()))
    transitions, holds = [], []
    for train in data["train_plans"]:
        previous = None
        for row in train["resource_reservations"]:
            if not row["existing_occupancy"]:
                transitions.append({"at": row["start_time"], "train_id": row["train_id"],
                    "action": "ENTER_RESOURCE", "resource_type": row["resource_type"],
                    "resource_id": row["resource_id"], "release_previous": previous,
                    "minimum_traversal_end": row["traversal_end_time"], "sequence": row["sequence"]})
            previous = {"resource_type": row["resource_type"], "resource_id": row["resource_id"]}
            if row["release_requires_replan"]:
                holds.append({"train_id": row["train_id"], **previous, "replan_by": data["planning_horizon_end"]})
        if train["final_arrival_time"] is not None:
            transitions.append({"at": train["final_arrival_time"], "train_id": train["train_id"],
                "action": "COMPLETE_TRAIN", "release_previous": previous, "sequence": len(train["resource_reservations"])})
    transitions.sort(key=lambda x: (x["at"], 0 if x["action"] == "COMPLETE_TRAIN" else 1, x["train_id"], x["sequence"]))
    return {key: data[key] for key in ("plan_id", "scenario_id", "seed", "run_id", "dataset_version", "snapshot_version", "policy")} | {
        "advisory": True, "scope": "simulation_fork_only", "transitions": transitions,
        "terminal_holds": holds, "simultaneous_transitions": "Apply equal-time transitions atomically as a batch.",
        "validation": checked.to_dict()}
