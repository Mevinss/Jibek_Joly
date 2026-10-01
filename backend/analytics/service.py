"""Transparent configurable demo index and evidence-based runtime summaries."""
from collections import Counter
from dataclasses import dataclass, field
import math

from backend.evaluation.models import JsonContract
from backend.planner.context import timestamp


@dataclass(frozen=True)
class QualityFactorConfig:
    name: str
    weight: float
    cap: float


DEFAULT_FACTORS = (QualityFactorConfig("mean_final_delay_min", .5, 20),
                   QualityFactorConfig("stops_per_train", .25, 2),
                   QualityFactorConfig("invalid_run", .25, 1))


@dataclass
class QualityIndexResult(JsonContract):
    score: float | None
    factors: list[dict] = field(default_factory=list)
    status: str = "UNAVAILABLE"
    method: str = "100_MINUS_WEIGHTED_NORMALIZED_PENALTIES"
    calibration: str = "CONFIGURABLE_DEMO_INDEX_NOT_SCIENTIFICALLY_CALIBRATED"


def quality_index(run, factors=DEFAULT_FACTORS):
    if not factors or len({f.name for f in factors}) != len(factors):
        raise ValueError("unique factors required")
    if any(not math.isfinite(f.weight) or f.weight < 0 or not math.isfinite(f.cap) or f.cap <= 0 for f in factors) or not math.isclose(sum(f.weight for f in factors), 1, abs_tol=1e-9):
        raise ValueError("factor weights must sum to one; positive finite caps required")
    count = len(run.train_results)
    values = dict(mean_final_delay_min=run.total_arrival_delay_min / count if count and run.total_arrival_delay_min is not None else None,
        added_delay_after_incident_min=run.added_delay_after_incident_min,
        stops_per_train=run.stop_count / count if count and run.stop_count is not None else None,
        energy_proxy_units=run.energy_proxy_units, planner_ms=run.planner_ms,
        invalid_run=0 if run.valid and run.safety_scope_complete else 1)
    output = []
    for f in factors:
        if f.name not in values:
            raise ValueError("unsupported quality factor: " + f.name)
        value = values[f.name]
        normalized = min(1, max(0, value / f.cap)) if value is not None else None
        output.append(dict(name=f.name, weight=f.weight, value=value, cap=f.cap, normalized=normalized,
            contribution=100 * f.weight * normalized if normalized is not None else None,
            reason="MISSING_OBSERVATIONS" if value is None else "Penalty clipped to [0,1] using documented configurable cap."))
    available = run.status == "COMPLETED" and all(f["contribution"] is not None for f in output)
    return QualityIndexResult(100 - sum(f["contribution"] for f in output) if available else None,
        output, "AVAILABLE" if available else "UNAVAILABLE")


def build_analytics(run):
    seconds = (timestamp(run.finished_at_virtual) - timestamp(run.started_at_virtual)).total_seconds()
    groups = {}
    for row in run.resource_observations:
        groups.setdefault((row["resource_type"], row["resource_id"]), []).append((timestamp(row["start_time"]), timestamp(row["end_time"])))
    utilization = []
    for (kind, rid), intervals in sorted(groups.items()):
        union = []
        for left, right in sorted(intervals):
            if union and left <= union[-1][1]:
                union[-1] = (union[-1][0], max(right, union[-1][1]))
            else:
                union.append((left, right))
        busy = sum((b - a).total_seconds() for a, b in union)
        utilization.append(dict(resource_type=kind, resource_id=rid, occupied_seconds=busy,
            occupied_time_fraction=busy / seconds if seconds > 0 else None, basis="OBSERVED_OCCUPIED_TIME_UNION"))
    categories = {}
    for train in run.train_results:
        item = categories.setdefault(train.category or "UNKNOWN", dict(completed_count=0, incomplete_count=0, completed_delay_min=0.0))
        if train.completed and train.final_delay_min is not None:
            item["completed_count"] += 1
            item["completed_delay_min"] += train.final_delay_min
        else:
            item["incomplete_count"] += 1
    reasons = Counter(e.get("reason", e["type"]) for e in run.runtime_events)
    incident_events = [e for e in run.runtime_events if e["type"].startswith("INCIDENT_")]
    return dict(source="RUNTIME_EVALUATION", source_type=run.source_type, run_id=run.run_id,
        resource_utilization=utilization,
        bottleneck_blocks=sorted([u for u in utilization if u["resource_type"] == "block"], key=lambda u: (-u["occupied_seconds"], u["resource_id"]))[:5],
        delay_reasons=dict(reasons), delay_reason_scope="Observed wait states; un-attributed waits are not assigned a causal incident.",
        incident_impact=dict(added_delay_after_incident_min=run.added_delay_after_incident_min, events=incident_events,
            causal_attribution="NOT_ESTABLISHED"), category_delay=categories, stop_count=run.stop_count,
        full_stop_avoided_count=run.full_stop_avoided_count, energy_proxy_units=run.energy_proxy_units,
        energy_proxy_label=run.energy_proxy_label, planner_fallback_count=run.fallback_count,
        validator_rejection_count=len(run.validation.get("violations", [])), runtime_violations=run.runtime_violations)
