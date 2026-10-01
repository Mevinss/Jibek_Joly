"""Explicit, decision-free bridge between demo playback, canonical v2 and AI input."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from backend.simulator.state_contract import (
    CanonicalScenarioSnapshot,
    canonical_from_backend_snapshot,
)


def canonical_from_demo_snapshot(
    demo: dict[str, Any], seed: int, *, run_id: str | None = None,
) -> CanonicalScenarioSnapshot:
    """Preserve visible positions and *all* occupants without applying a plan.

    The existing planner-v1 bridge supplies route/block metadata. Its legacy
    ``progress`` means current-block progress. Canonical ``progress`` always
    means route progress; the two explicit v2 fields remove that ambiguity.
    """
    from .integration import platform_snapshot

    platform = platform_snapshot(demo, seed)
    result = canonical_from_backend_snapshot(platform, run_id=run_id)
    observed_trains = {row["train_id"]: row for row in demo["state"]["trains"]}
    display = {row["train_id"]: row for row in demo["display"]}
    observed_blocks = {row["id"]: row for row in demo["state"]["infra"]["blocks"]}
    for train in result["trains"]:
        raw = observed_trains[train["train_id"]]
        shown = display[train["train_id"]]
        train.update({
            "speed_kmh": raw["speed"], "delay_min": raw["delay_s"] / 60,
            "next_station_id": shown["next_station"] if train.get("status") != "completed" else None,
            "scheduled_arrival": shown.get("scheduled_arrival") if train.get("status") != "completed" else None,
            "estimated_arrival": (datetime.fromisoformat(demo["ts"]) +
                                  timedelta(seconds=shown["eta_s"])).isoformat()
                                 if shown.get("eta_s") is not None else None,
            "estimated_arrival_source": "DERIVED" if shown.get("eta_s") is not None else None,
            "position_block_id": raw["position"]["block_id"],
            "position_km": raw["position"]["km"],
            "ai_train_type": raw["type"], "ai_priority": raw["priority"],
            "min_technical_time_min": raw["min_technical_time_min"],
            "time_reserve_min": raw["time_reserve_min"],
            "deterministic_wait_s": raw.get("deterministic_wait_s"),
            "restriction_extra_s": raw.get("restriction_extra_s", 0),
            "source_domain": raw.get("source_domain"),
            "next_block_closed": raw.get("next_block_closed", False),
        })
    for block in result["blocks"]:
        raw = observed_blocks[block["block_id"]]
        block.update({"speed_limit_kmh": raw["speed_limit"],
                      "num_platform_tracks": raw["num_platform_tracks"],
                      "is_passing_loop": raw["is_passing_loop"],
                      "is_node": raw["is_node"]})
    # Playback reports no live signal/switch state. Keep stable resource IDs,
    # but do not present simulator-template aspects as observed demo aspects.
    if not demo["state"]["infra"].get("signals"):
        for signal in result["signals"]:
            signal.update(aspect=None, failed=None, updated_at=None,
                          state_source="UNAVAILABLE")
    if not demo["state"]["infra"].get("switches"):
        for switch in result["switches"]:
            switch.update(position=None, locked=None, failed=None,
                          state_source="UNAVAILABLE")
    if demo.get("incident_active") and demo.get("incident") in ("restriction", "chaos"):
        result["active_incidents"].append({
            "incident_id": "UI-" + demo["incident"].upper(),
            "type": "SPEED_RESTRICTION" if demo["incident"] == "restriction" else "CHAOS_DEMO",
            "at": demo["ts"], "source_type": "SIMULATED_DEMO",
        })
    return result


def planner_snapshot_from_canonical(state: CanonicalScenarioSnapshot) -> dict[str, Any]:
    """Compatibility projection until Person 2 reads block_progress_0_1 itself.

    The v1 planner interprets ``progress`` as a current-block fraction. Reject
    capacity conflicts because its single ``occupied_by`` cannot express them.
    """
    conflicting = [b["block_id"] for b in state["blocks"] if b["state_conflict"]]
    if conflicting:
        raise ValueError("planner-v1 cannot represent occupied blocks: " + ", ".join(conflicting))
    trains = deepcopy(state["trains"])
    for train in trains:
        train["progress"] = train["block_progress_0_1"]
    return {"scenario_id": state["scenario_id"], "seed": state["seed"],
            "virtual_time": state["virtual_time"], "version": state["snapshot_version"],
            "source_type": state["source_type"], "trains": trains,
            "blocks": deepcopy(state["blocks"]), "station_tracks": deepcopy(state["station_tracks"]),
            "signals": deepcopy(state["signals"]), "switches": deepcopy(state["switches"]),
            "active_incidents": deepcopy(state["active_incidents"])}


def ai_state_from_canonical(state: CanonicalScenarioSnapshot) -> dict[str, Any]:
    """Reconstruct an AI State only when its measured/demo inputs are present.

    Backend-only snapshots lack speed and technical-time observations. Refuse
    those instead of silently making up ML features.
    """
    trains = []
    for train in state["trains"]:
        required = ("position_block_id", "position_km", "speed_kmh", "ai_train_type",
                    "ai_priority", "min_technical_time_min", "time_reserve_min")
        missing = [key for key in required if train.get(key) is None]
        if missing:
            raise ValueError(f"{train['train_id']} has no AI input fields: {', '.join(missing)}")
        trains.append({
            "train_id": train["train_id"], "type": train["ai_train_type"],
            "priority": train["ai_priority"],
            "position": {"block_id": train["position_block_id"], "km": train["position_km"]},
            "speed": train["speed_kmh"], "delay_s": train["delay_min"] * 60,
            "ts": train["updated_at"],
            "min_technical_time_min": train["min_technical_time_min"],
            "time_reserve_min": train["time_reserve_min"],
            "deterministic_wait_s": train.get("deterministic_wait_s"),
            "restriction_extra_s": train.get("restriction_extra_s", 0),
            "source_domain": train.get("source_domain"),
            "next_block_closed": train.get("next_block_closed", False),
        })
    blocks = []
    for block in state["blocks"]:
        required = ("speed_limit_kmh", "num_platform_tracks", "is_passing_loop", "is_node")
        missing = [key for key in required if block.get(key) is None]
        if missing:
            raise ValueError(f"{block['block_id']} has no AI input fields: {', '.join(missing)}")
        blocks.append({
            "id": block["block_id"], "occupied": bool(block["occupied_train_ids"]),
            "closed": block["closed"], "speed_limit": block["speed_limit_kmh"],
            "block_load": len(block["occupied_train_ids"]),
            "num_platform_tracks": block["num_platform_tracks"],
            "is_passing_loop": block["is_passing_loop"],
            "is_node": block["is_node"],
        })
    return {"trains": trains, "infra": {"blocks": blocks,
            "signals": state["signals"], "switches": state["switches"]}}
