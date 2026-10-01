"""Deterministic FIFO dispatch ordering for a ScenarioSnapshot."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "kz_demo"


def load_demo_priorities(data_root: Path = DATA) -> dict[str, int]:
    """Resolve category priorities from the checked-in synthetic demo tables."""
    data_root = Path(data_root)
    with (data_root / "KZ/train_services.csv").open(encoding="utf-8-sig", newline="") as stream:
        services = list(csv.DictReader(stream))
    with (data_root / "mock/train_parameters.csv").open(encoding="utf-8-sig", newline="") as stream:
        categories = {row["category"]: int(row["priority"]) for row in csv.DictReader(stream)}
    return {
        row["train_id"]: categories[row["category"]]
        for row in services
        if row["category"] in categories
    }


def order_requests(
    requests: list[dict[str, Any]],
    priorities: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Sort by requested_at, then higher numeric priority, then train_id.

    Priority is optional because ScenarioSnapshot v1 does not yet carry it.
    """
    priorities = priorities or {}

    def key(request: dict[str, Any]) -> tuple[datetime, int, str]:
        train_id = request["train_id"]
        when = datetime.fromisoformat(request["requested_at"])
        if when.tzinfo is None:
            raise ValueError("requested_at must include a timezone offset")
        priority = int(priorities.get(train_id, request.get("priority", 0)))
        return when, -priority, train_id

    return sorted((dict(request) for request in requests), key=key)


def plan_fifo(
    snapshot: dict[str, Any],
    requests: list[dict[str, Any]] | None = None,
    priorities: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Return a reproducible dispatch order, not a full movement simulation.

    The current snapshot lacks run-stop dwell windows and explicit priorities;
    callers may provide requests and priority metadata until the simulator
    handoff exposes them.
    """
    trains = {train["train_id"]: train for train in snapshot.get("trains", [])}
    if requests is None:
        requests = [
            {"train_id": train["train_id"], "requested_at": train.get("planned_start")}
            for train in snapshot.get("trains", [])
            if train.get("status") != "completed" and train.get("planned_start")
        ]
    resolved_priorities = dict(priorities) if priorities is not None else load_demo_priorities()
    ordered = order_requests(requests, resolved_priorities)
    return {
        "policy": "FIFO",
        "status": "DISPATCH_ORDER_ONLY",
        "scenario_id": snapshot.get("scenario_id"),
        "seed": snapshot.get("seed"),
        "snapshot_version": snapshot.get("version"),
        "source_type": snapshot.get("source_type"),
        "ordered_train_ids": [item["train_id"] for item in ordered],
        "requests": [
            {
                **item,
                "priority": int(resolved_priorities.get(
                    item["train_id"], item.get("priority", 0)
                )),
                "known_to_snapshot": item["train_id"] in trains,
            }
            for item in ordered
        ],
        "limitations": [
            "No movement intervals were generated; this result is only a deterministic request order.",
            "ScenarioSnapshot v1 does not include train priority or station dwell windows.",
        ],
    }
