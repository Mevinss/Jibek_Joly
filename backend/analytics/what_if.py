"""Counterfactual snapshot clones; never access or mutate a live simulator."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
import math

from backend.evaluation.models import CompareResult, JsonContract
from backend.evaluation.service import compare_policies, digest
from backend.planner.context import timestamp


@dataclass
class WhatIfResult(JsonContract):
    kind: str
    base: CompareResult
    scenario: CompareResult
    delta: dict
    original_snapshot_unchanged: bool
    source_type: str = "SIMULATED_DEMO"


def perturb_snapshot(snapshot, kind, target_id, minutes):
    if not math.isfinite(minutes) or not 0 < minutes <= 60:
        raise ValueError("minutes must be in (0, 60]")
    changed = deepcopy(snapshot)
    now = timestamp(changed["virtual_time"])
    if kind in {"EXTRA_DELAY", "CONNECTION_WAIT"}:
        train = next((t for t in changed["trains"] if t["train_id"] == target_id), None)
        if train is None or train["status"].lower() == "completed":
            raise ValueError("unknown or completed train")
        if train["block_index"] < 0:
            train["departure_shift_seconds"] = train.get("departure_shift_seconds", 0) + math.ceil(minutes * 60)
            train["delay_min"] = train.get("delay_min", 0) + minutes
        else:
            start = max(now, timestamp(train["hold_until"])) if train.get("hold_until") else now
            train["hold_until"] = (start + timedelta(minutes=minutes)).isoformat()
    elif kind in {"BLOCK_CLOSURE", "SIGNAL_DELAY"}:
        if not float(minutes).is_integer():
            raise ValueError("engine incident duration must be whole minutes")
        table, key = ("blocks", "block_id") if kind == "BLOCK_CLOSURE" else ("signals", "signal_id")
        resource = next((r for r in changed[table] if r[key] == target_id), None)
        if resource is None:
            raise ValueError("unknown resource")
        if kind == "BLOCK_CLOSURE":
            resource["closed"] = True
        else:
            resource["failed"], resource["aspect"] = True, "STOP"
        changed["active_incidents"].append(dict(incident_id="WHAT-IF-" + digest([kind, target_id, minutes])[:12],
            type="BLOCK_CLOSURE" if kind == "BLOCK_CLOSURE" else "SIGNAL_FAILURE", at=changed["virtual_time"],
            duration_min=int(minutes), source_type="SYNTHETIC_DEMO", **{key: target_id}))
    else:
        raise ValueError("unsupported what-if kind")
    return changed


def what_if(snapshot, kind, target_id, minutes, **compare_options):
    before = digest(snapshot)
    changed = perturb_snapshot(snapshot, kind, target_id, minutes)
    base = compare_policies(deepcopy(snapshot), **compare_options)
    scenario = compare_policies(changed, **compare_options)
    delta = {}
    for policy in ("fifo", "cp_sat", "human"):
        a, b = getattr(base, policy), getattr(scenario, policy)
        # Across different scenarios this is a counterfactual delta, not SAME SNAPSHOT comparison.
        delta[policy] = b.total_arrival_delay_min - a.total_arrival_delay_min if a and b and a.valid and b.valid and a.total_arrival_delay_min is not None and b.total_arrival_delay_min is not None else None
    return WhatIfResult(kind, base, scenario, delta, digest(snapshot) == before)
