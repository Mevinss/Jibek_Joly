"""Deterministic evaluation helpers for completed policy runs."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable


def _delay_for_run(run: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    if run.get("completed") is not True and str(run.get("status", "")).upper() != "COMPLETED":
        return None, None, None
    trains = run.get("trains")
    if not isinstance(trains, list) or not trains:
        return None, None, None
    total = 0.0
    added = 0.0
    weighted = 0.0
    has_weights = True
    for train in trains:
        scheduled = train.get("scheduled_final_arrival")
        actual = train.get("actual_final_arrival")
        if not scheduled or not actual or train.get("completed") is not True:
            return None, None, None
        scheduled_at = datetime.fromisoformat(scheduled)
        actual_at = datetime.fromisoformat(actual)
        if scheduled_at.tzinfo is None or actual_at.tzinfo is None:
            raise ValueError("arrival timestamps must include timezone offsets")
        delay = max(0.0, (actual_at - scheduled_at).total_seconds() / 60)
        total += delay
        onset_delay = train.get("delay_at_incident_min")
        if onset_delay is not None:
            added += max(0.0, delay - float(onset_delay))
        weight = train.get("priority_weight")
        if weight is None:
            has_weights = False
        else:
            weighted += delay * float(weight)
    return round(total, 2), round(added, 2), round(weighted, 2) if has_weights else None


def evaluate_runs(runs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compare completed runs only when they share scenario, seed and snapshot version.

    Each run.train record needs scheduled_final_arrival and actual_final_arrival.
    An unvalidated conflict count and an incomplete run remain null.
    """
    runs = list(runs)
    by_policy = {run.get("policy"): run for run in runs}
    if len(by_policy) != len(runs):
        raise ValueError("each policy may appear only once")
    identities = {
        (run.get("scenario_id"), run.get("seed"), run.get("snapshot_version"))
        for run in runs
    }
    same_snapshot = (
        len(identities) == 1
        and all(None not in identity for identity in identities)
    )
    results: dict[str, Any] = {}
    for run in runs:
        delay, added, weighted = _delay_for_run(run)
        validation = run.get("validation")
        valid = validation.get("valid") if isinstance(validation, dict) else None
        conflict_count = run.get("conflict_count") if valid is True else None
        decisions = run.get("human_decisions", [])
        results[run.get("policy", "UNKNOWN")] = {
            "status": run.get("status", "UNKNOWN"),
            "total_arrival_delay_min": delay,
            "added_delay_after_incident_min": added if delay is not None else None,
            "weighted_delay_min": weighted if delay is not None else None,
            "conflict_count": conflict_count,
            "valid": valid,
            "solver_time_ms": run.get("solver_time_ms"),
            "fallback_reason": run.get("fallback_reason"),
            "auto_fifo_timeout_count": sum(
                1 for item in decisions
                if item.get("action") == "AUTO_FIFO_TIMEOUT"
            ),
        }
    fifo = results.get("FIFO", {}).get("total_arrival_delay_min")
    cp = results.get("CP_SAT", {}).get("total_arrival_delay_min")
    improvement = None if not same_snapshot or fifo in (None, 0) or cp is None else round(100 * (fifo - cp) / fifo, 2)
    identity = next(iter(identities)) if same_snapshot and identities else (None, None, None)
    return {
        "scenario_id": identity[0],
        "seed": identity[1],
        "snapshot_version": identity[2],
        "same_initial_snapshot": same_snapshot,
        "reproducible_comparison": same_snapshot and {run.get("policy") for run in runs} == {"HUMAN", "FIFO", "CP_SAT"},
        "improvement_vs_fifo_pct": improvement,
        "results": results,
    }
