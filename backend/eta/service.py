"""Deterministic ETA from validated reservations or explicitly labelled schedule."""
from dataclasses import dataclass, field
from datetime import timedelta
import math

from backend.evaluation.models import JsonContract
from backend.planner.context import PlanningContext, timestamp
from backend.validator.resources import validate_plan


@dataclass
class TrainETA(JsonContract):
    train_id: str
    station_id: str | None
    eta: str | None = None
    minutes_remaining: float | None = None
    scheduled_arrival: str | None = None
    delay_min: float | None = None
    recommended_track: str | None = None
    track_status: str = "UNKNOWN"
    source: str = "UNAVAILABLE"
    status: str = "UNAVAILABLE"
    reason: str = "TIMING_DATA_MISSING"
    safety_scope_complete: bool = False
    train_number: str | None = None
    category: str | None = None
    confidence: str = "DETERMINISTIC_DEMO_ESTIMATE_NOT_CALIBRATED"


@dataclass
class StationArrivalsResult(JsonContract):
    station_id: str
    virtual_time: str
    arrivals: list[TrainETA] = field(default_factory=list)
    source_type: str = "SIMULATED_DEMO"


def _targets(train, infra):
    targets = {train.get("next_station_id"), train.get("destination_station_id")}
    targets.update(s["station_id"] for s in train.get("station_stops", []))
    for bid, signal in zip(train.get("route", []), train.get("entry_signals", [])):
        block = infra["blocks"].get(bid, {})
        seg = infra["segments"].get(block.get("segment_id"), {})
        direction = infra.get("signals", {}).get(signal, {}).get("entry_direction_from")
        if direction == seg.get("from_station_id"):
            targets.add(seg.get("to_station_id"))
        elif direction == seg.get("to_station_id"):
            targets.add(seg.get("from_station_id"))
    return targets - {None}


def get_train_eta(snapshot, train_id, station_id=None, plan=None, *, infrastructure=None):
    train = next((t for t in snapshot["trains"] if t["train_id"] == train_id), None)
    if train is None:
        raise KeyError(train_id)
    station_id = station_id or train.get("next_station_id") or train.get("destination_station_id")
    result = TrainETA(train_id, station_id, train_number=train.get("train_number"), category=train.get("category"))
    infra = infrastructure if infrastructure is not None else PlanningContext._fixture()
    if station_id is None or station_id not in _targets(train, infra):
        result.reason = "STATION_NOT_ON_KNOWN_ROUTE"
        return result
    scheduled = train.get("scheduled_arrival") if station_id == train.get("next_station_id") else None
    if station_id == train.get("destination_station_id"):
        scheduled = train.get("scheduled_final_arrival") or scheduled
    if not scheduled:
        stops = [s for s in infra.get("stops", []) if s["train_id"] == train_id and s["station_id"] == station_id and s.get("scheduled_arrival")]
        scheduled = stops[0]["scheduled_arrival"] if stops else None
    result.scheduled_arrival = scheduled
    if train.get("status", "").lower() == "completed":
        result.reason = "ALREADY_COMPLETED_ARRIVAL_NOT_OBSERVED"
        return result
    eta = None
    if plan is not None:
        data = plan.to_dict() if hasattr(plan, "to_dict") else plan
        checked = validate_plan(snapshot, data, infrastructure)
        result.safety_scope_complete = checked.fully_validated
        if not checked.valid:
            result.reason = "INVALID_OR_STALE_PLAN"
            return result
        selected = next((p for p in data["train_plans"] if p["train_id"] == train_id), None)
        if selected:
            station_rows = [s for s in selected["selected_station_tracks"] if s["station_id"] == station_id]
            if station_rows:
                row = min(station_rows, key=lambda s: timestamp(s["start_time"]))
                eta = row["start_time"]
                track = next((s for s in snapshot["station_tracks"] if s.get("track_id", s.get("station_track_id")) == row["track_id"]), None)
                if track and track.get("available") is True and track.get("occupancy_source") != "UNAVAILABLE":
                    result.recommended_track, result.track_status = row["track_id"], "PLAN_RESERVED"
            if eta is None and station_id == train.get("destination_station_id"):
                eta = selected["final_arrival_time"]
            if eta is None:
                # Arrival at segment boundary, not at every intermediate block.
                for row in selected["resource_reservations"]:
                    if row["resource_type"] != "block":
                        continue
                    idx = row["route_index"]
                    bid = row["resource_id"]
                    segment_id = infra["blocks"][bid]["segment_id"]
                    following = train["route"][idx + 1] if idx + 1 < len(train["route"]) else None
                    if following and infra["blocks"][following]["segment_id"] == segment_id:
                        continue
                    seg = infra["segments"][segment_id]
                    direction = infra["signals"].get(train["entry_signals"][idx], {}).get("entry_direction_from")
                    target = seg.get("to_station_id") if direction == seg.get("from_station_id") else seg.get("from_station_id") if direction == seg.get("to_station_id") else None
                    if target == station_id:
                        eta = row["traversal_end_time"]
                        break
        if eta is None or timestamp(eta) > timestamp(data["planning_horizon_end"]):
            result.reason = "STATION_OUTSIDE_PLAN_HORIZON"
            return result
        result.source, result.reason = "PLAN_BASED", "VALIDATED_RESERVATION_TIMING"
    elif scheduled and train.get("delay_min") is not None:
        delay = float(train["delay_min"])
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("delay_min must be finite and nonnegative")
        eta = (timestamp(scheduled) + timedelta(minutes=delay)).isoformat()
        result.source, result.reason = "SCHEDULE_FALLBACK", "SCHEDULE_PLUS_CURRENT_DELAY; future resource waits not modelled"
    if eta is not None:
        remaining = (timestamp(eta) - timestamp(snapshot["virtual_time"])).total_seconds() / 60
        if remaining < 0:
            result.source, result.reason = "UNAVAILABLE", "ESTIMATE_IN_PAST"
            return result
        result.eta, result.minutes_remaining, result.status = eta, remaining, "AVAILABLE"
        if scheduled:
            result.delay_min = max(0, (timestamp(eta) - timestamp(scheduled)).total_seconds() / 60)
    return result


def get_station_arrivals(snapshot, station_id, plan=None, *, infrastructure=None):
    infra = infrastructure if infrastructure is not None else PlanningContext._fixture()
    arrivals = [get_train_eta(snapshot, t["train_id"], station_id, plan, infrastructure=infra)
                for t in snapshot["trains"] if station_id in _targets(t, infra) and t.get("status", "").lower() != "completed"]
    arrivals.sort(key=lambda a: (a.eta is None, timestamp(a.eta) if a.eta else timestamp(snapshot["virtual_time"]), a.train_id))
    return StationArrivalsResult(station_id, snapshot["virtual_time"], arrivals)
