"""Canonical, read-only v2 state projection for the simulator and demo adapters.

ScenarioSnapshot v1 remains the persisted movement format. This module is the
single authority for v2 field names and their meaning; it makes no decisions.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, TypedDict

from .engine import DATA, read_csv

SCHEMA_VERSION = "2.0"


class CanonicalTrainState(TypedDict, total=False):
    train_id: str
    train_number: str | None
    category: str | None
    direction: str | None
    route_id: str | None
    route: list[str]
    origin_station_id: str | None
    destination_station_id: str | None
    current_segment_id: str | None
    current_block_id: str | None
    route_progress_0_1: float
    block_progress_0_1: float
    progress: float  # Deprecated v1 alias for route_progress_0_1.
    speed_kmh: float | None
    delay_min: float
    next_station_id: str | None
    scheduled_arrival: str | None
    estimated_arrival: str | None
    estimated_arrival_source: str | None
    data_mode: str
    source_type: str
    updated_at: str
    position_block_id: str | None
    position_km: float | None
    ai_train_type: str | None
    ai_priority: int | None
    min_technical_time_min: float | None
    time_reserve_min: float | None
    deterministic_wait_s: float | None
    restriction_extra_s: float | None
    source_domain: str | None
    next_block_closed: bool | None


class CanonicalBlockState(TypedDict, total=False):
    block_id: str
    segment_id: str | None
    capacity: int
    occupied_train_ids: list[str]
    occupied_by: str | None  # Deprecated v1 first-occupant alias.
    closed: bool
    direction_lock: str | None
    speed_limit_kmh: float | None
    entry_signal_id: str | None
    state_conflict: bool
    direction_lock_rule: str | None
    num_platform_tracks: int | None
    is_passing_loop: bool | None
    is_node: bool | None


class CanonicalScenarioSnapshot(TypedDict):
    schema_version: str
    scenario_id: str
    seed: int
    run_id: str | None
    dataset_version: str
    virtual_time: str
    snapshot_version: int
    source_type: str
    trains: list[CanonicalTrainState]
    blocks: list[CanonicalBlockState]
    station_tracks: list[dict[str, Any]]
    signals: list[dict[str, Any]]
    switches: list[dict[str, Any]]
    active_incidents: list[dict[str, Any]]


def _fraction(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 6)


@lru_cache(maxsize=4)
def infrastructure(data_root: str = str(DATA)) -> dict[str, Any]:
    root = Path(data_root)
    files = (
        "KZ/stations.csv", "KZ/segments.csv", "KZ/blocks.csv",
        "KZ/station_tracks.csv", "KZ/train_services.csv", "KZ/run_stops.csv",
        "mock/signals.csv", "mock/switches.csv",
    )
    digest = hashlib.sha256()
    for name in files:
        digest.update(name.encode("utf-8"))
        digest.update((root / name).read_bytes())
    rows = {name: read_csv(root / name) for name in files}
    return {
        "dataset_version": "sha256:" + digest.hexdigest()[:16],
        "stations": rows["KZ/stations.csv"],
        "segments": {r["segment_id"]: r for r in rows["KZ/segments.csv"]},
        "blocks": {r["block_id"]: r for r in rows["KZ/blocks.csv"]},
        "tracks": rows["KZ/station_tracks.csv"],
        "services": {r["train_id"]: r for r in rows["KZ/train_services.csv"]},
        "stops": rows["KZ/run_stops.csv"],
        "signals": rows["mock/signals.csv"],
        "switches": rows["mock/switches.csv"],
    }


def canonical_from_backend_snapshot(
    snapshot: dict[str, Any], *, run_id: str | None = None,
    data_root: Path = DATA,
) -> CanonicalScenarioSnapshot:
    """Project a v1 snapshot without changing it or fabricating unknown state."""
    infra = infrastructure(str(Path(data_root).resolve()))
    now = snapshot["virtual_time"]
    if datetime.fromisoformat(now).tzinfo is None:
        raise ValueError("virtual_time requires an offset")
    source = snapshot.get("source_type", "SIMULATED_DEMO")
    blocks_by_id = {row["block_id"]: row for row in snapshot["blocks"]}
    occupants: dict[str, set[str]] = {block_id: set() for block_id in blocks_by_id}
    for block_id, row in blocks_by_id.items():
        occupants[block_id].update(row.get("occupied_train_ids") or [])
        if row.get("occupied_by"):
            occupants[block_id].add(row["occupied_by"])
    for train in snapshot["trains"]:
        if train.get("block_id") in occupants and train.get("status") != "completed":
            occupants[train["block_id"]].add(train["train_id"])

    stops_by_train: dict[str, list[dict]] = {}
    for stop in infra["stops"]:
        stops_by_train.setdefault(stop["train_id"], []).append(stop)
    trains: list[CanonicalTrainState] = []
    for row in snapshot["trains"]:
        train_id = row["train_id"]
        service = infra["services"].get(train_id, {})
        route = row.get("route", [])
        index = int(row.get("block_index", -1))
        duration = (row.get("block_seconds") or [])[index] if 0 <= index < len(row.get("block_seconds") or []) else 0
        if row.get("status") == "completed":
            block_progress, route_progress = 1.0, 1.0
        elif index < 0 or not route:
            block_progress, route_progress = 0.0, 0.0
        else:
            block_progress = _fraction(float(row.get("block_progress_0_1", row.get("block_elapsed", 0) / duration if duration else 0)))
            route_progress = _fraction(float(row.get("route_progress_0_1", (index + block_progress) / len(route))))
        current_block = row.get("block_id")
        route_block = current_block or (route[0] if route else None)
        segment_id = infra["blocks"].get(route_block, {}).get("segment_id") if route_block else None
        segment = infra["segments"].get(segment_id, {})
        origin = service.get("origin_station_id") or None
        destination = service.get("destination_station_id") or None
        if segment:
            first, second = segment["from_station_id"], segment["to_station_id"]
            direction = service.get("direction")
            next_station = second if direction == "forward" else first if direction == "reverse" else None
        else:
            next_station = None
        if row.get("status") == "completed":
            next_station = None
        scheduled_arrival = next((s["scheduled_arrival"] for s in stops_by_train.get(train_id, [])
                                  if s["station_id"] == next_station and s["scheduled_arrival"]), None)
        trains.append({
            **row, "train_id": train_id, "train_number": service.get("public_train_number") or None,
            "category": service.get("category") or None, "direction": service.get("direction") or None,
            "route_id": service.get("pattern_id") or None, "route": route,
            "origin_station_id": origin, "destination_station_id": destination,
            "current_segment_id": infra["blocks"].get(current_block, {}).get("segment_id") if current_block else None,
            "current_block_id": current_block, "route_progress_0_1": route_progress,
            "block_progress_0_1": block_progress, "progress": route_progress,
            "speed_kmh": row.get("speed_kmh"), "delay_min": float(row.get("delay_min", 0)),
            "next_station_id": next_station, "scheduled_arrival": scheduled_arrival,
            "estimated_arrival": row.get("estimated_arrival"), "data_mode": source,
            "source_type": source, "updated_at": now,
        })

    blocks: list[CanonicalBlockState] = []
    for block_id, old in blocks_by_id.items():
        definition = infra["blocks"].get(block_id, {})
        segment_id = definition.get("segment_id")
        train_ids = sorted(occupants[block_id])
        capacity = int(definition.get("demo_capacity_trains", old.get("capacity", 1)))
        blocks.append({
            **old, "block_id": block_id, "segment_id": segment_id, "capacity": capacity,
            "occupied_train_ids": train_ids, "occupied_by": train_ids[0] if train_ids else None,
            "closed": bool(old.get("closed", False)),
            # Fixture rule is not the live direction currently holding a lock.
            "direction_lock": old.get("direction_lock"),
            "direction_lock_rule": infra["segments"].get(segment_id, {}).get("direction_lock") or None,
            "speed_limit_kmh": old.get("speed_limit_kmh"),
            "entry_signal_id": old.get("entry_signal_id"),
            "state_conflict": len(train_ids) > capacity,
        })

    failed_signals = {incident.get("signal_id") for incident in snapshot.get("active_incidents", [])
                      if incident.get("type") == "SIGNAL_FAILURE"}
    signals_by_id = {row["signal_id"]: row for row in infra["signals"]}
    signals = [{**row, "block_id": signals_by_id.get(row["signal_id"], {}).get("block_id"),
                "failed": row["signal_id"] in failed_signals, "updated_at": now}
               for row in snapshot["signals"]]
    switches_by_id = {row["switch_id"]: row for row in infra["switches"]}
    switches = [{**row, "locked": bool(row.get("failed", False)),
                 "available_routes": switches_by_id.get(row["switch_id"], {}).get("controlled_tracks", "").split("|")
                 if switches_by_id.get(row["switch_id"], {}).get("controlled_tracks") else None}
                for row in snapshot["switches"]]
    tracks = [{"station_id": row["station_id"], "track_id": row["station_track_id"],
               "capacity": int(row["demo_capacity_trains"]), "occupied_train_ids": [],
               "available": None, "occupancy_source": "UNAVAILABLE"}
              for row in infra["tracks"]]
    return {
        "schema_version": SCHEMA_VERSION, "scenario_id": snapshot["scenario_id"],
        "seed": int(snapshot["seed"]), "run_id": run_id, "dataset_version": infra["dataset_version"],
        "virtual_time": now, "snapshot_version": int(snapshot["version"]),
        "source_type": source, "trains": trains, "blocks": blocks,
        "station_tracks": tracks, "signals": signals, "switches": switches,
        "active_incidents": [dict(row) for row in snapshot.get("active_incidents", [])],
    }


def topology(*, geometry: dict[str, Any] | None = None,
             data_root: Path = DATA) -> dict[str, Any]:
    """Stable fixture IDs and optional approximate reference geometry."""
    infra = infrastructure(str(Path(data_root).resolve()))
    geo_stations = {row["id"]: row for row in (geometry or {}).get("stations", [])}
    geo_blocks = {row["properties"]["id"]: row for row in (geometry or {}).get("features", [])}
    stations = [{"station_id": row["station_id"], "name": row["name_kk"],
                 "coordinates": geo_stations.get(row["station_id"], {}).get("coordinates"),
                 "geometry_source": geo_stations.get(row["station_id"], {}).get("coordinate_source")}
                for row in infra["stations"]]
    segments = [{"segment_id": row["segment_id"], "from_station_id": row["from_station_id"],
                 "to_station_id": row["to_station_id"], "direction_lock": row["direction_lock"]}
                for row in infra["segments"].values()]
    blocks = [{"block_id": row["block_id"], "segment_id": row["segment_id"],
               "capacity": int(row["demo_capacity_trains"]),
               "geometry": geo_blocks.get(row["block_id"], {}).get("geometry")}
              for row in infra["blocks"].values()]
    tracks = [{"station_id": row["station_id"], "track_id": row["station_track_id"],
               "capacity": int(row["demo_capacity_trains"])} for row in infra["tracks"]]
    signals = [{"signal_id": row["signal_id"], "block_id": row["block_id"],
                "entry_direction_from": row["entry_direction_from"]} for row in infra["signals"]]
    switches = [{"switch_id": row["switch_id"], "station_id": row["station_id"],
                 "available_routes": row["controlled_tracks"].split("|")}
                for row in infra["switches"]]
    return {"schema_version": "1.0", "dataset_version": infra["dataset_version"],
            "source_type": "SIMULATED_DEMO",
            "geometry_source": "EXTERNAL_REFERENCE_APPROXIMATE" if geometry else "UNAVAILABLE",
            "stations": stations, "segments": segments, "blocks": blocks,
            "station_tracks": tracks, "signals": signals, "switches": switches}
