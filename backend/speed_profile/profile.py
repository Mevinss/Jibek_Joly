"""Advisory speed-limit profile; it does not model train dynamics or energy."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "kz_demo"


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def build_speed_profile(
    snapshot: dict[str, Any],
    train_id: str,
    data_root: Path = DATA,
) -> dict[str, Any]:
    """Return the lower of the demo line and train caps along the route.

    This is a limit-only advisory profile, not a physical speed optimization.
    energy_proxy_units stays null until an agreed formula and calibration exist.
    """
    data_root = Path(data_root)
    train = next((t for t in snapshot.get("trains", []) if t.get("train_id") == train_id), None)
    if train is None:
        raise KeyError(f"unknown train {train_id!r}")
    blocks = {r["block_id"]: r for r in _read(data_root / "KZ/blocks.csv")}
    segments = {r["segment_id"]: r for r in _read(data_root / "KZ/segments.csv")}
    speed_rows = {r["segment_id"]: r for r in _read(data_root / "KZ/line_speeds.csv")}
    speeds = {key: int(float(row["demo_limit_kmh"])) for key, row in speed_rows.items()}
    services = {r["train_id"]: r for r in _read(data_root / "KZ/train_services.csv")}
    params = {r["category"]: int(float(r["demo_max_speed_kmh"])) for r in _read(data_root / "mock/train_parameters.csv")}
    service = services.get(train_id)
    if service is None:
        raise KeyError(f"no demo service metadata for {train_id!r}")
    train_cap = params.get(service["category"])
    if train_cap is None:
        raise ValueError(f"no demo maximum speed for category {service['category']!r}")

    profile = []
    distance = 0.0
    seen_segments: set[str] = set()
    for block_id in train.get("route", []):
        block = blocks.get(block_id)
        if not block:
            raise ValueError(f"unknown block {block_id!r}")
        segment_id = block["segment_id"]
        if segment_id in seen_segments:
            continue
        seen_segments.add(segment_id)
        segment = segments[segment_id]
        line_cap = speeds.get(segment_id)
        if line_cap is None:
            raise ValueError(f"no demo line-speed limit for segment {segment_id!r}")
        cap = min(train_cap, line_cap)
        reverse = service["direction"] == "reverse"
        profile.append({
            "segment_id": segment_id,
            "from_station_id": segment["to_station_id"] if reverse else segment["from_station_id"],
            "to_station_id": segment["from_station_id"] if reverse else segment["to_station_id"],
            "distance_from_km": round(distance, 2),
            "distance_to_km": round(distance + float(segment["demo_distance_km"]), 2),
            "line_limit_kmh": line_cap,
            "train_limit_kmh": train_cap,
            "recommended_speed_kmh": cap,
            "source_type": speed_rows[segment_id].get("source_type", "SIMULATED_DEMO"),
        })
        distance += float(segment["demo_distance_km"])
    return {
        "train_id": train_id,
        "status": "LIMIT_ONLY_ILLUSTRATION",
        "profile_type": "advisory_limit_profile",
        "profile": profile,
        "energy_proxy_units": None,
        "energy_reason": "Not calculated: no agreed energy_proxy_units formula or calibrated physical model.",
        "limitations": [
            "Recommended values are only the minimum of the fixture train cap and line cap.",
            "No acceleration, braking, gradients, dwell, or arrival objective is modeled.",
            "This is not a physical model and does not control a train.",
        ],
    }
