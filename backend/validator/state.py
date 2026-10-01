"""Read explicit occupancy/progress without mutating Person 1's contract."""
from __future__ import annotations

import math


def occupants(resource: dict) -> list[str]:
    if "occupied_train_ids" in resource:
        return list(resource["occupied_train_ids"])
    return [resource["occupied_by"]] if resource.get("occupied_by") else []


def remaining_block_seconds(train: dict) -> int:
    index = int(train.get("block_index", -1))
    durations = train.get("block_seconds", [])
    if not 0 <= index < len(durations):
        raise ValueError("current block has no traversal duration")
    duration = float(durations[index])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("invalid current block duration")
    if "block_progress_0_1" in train:
        progress = float(train["block_progress_0_1"])
    elif "block_elapsed" in train:
        progress = float(train["block_elapsed"]) / duration
    else:
        # Conservative compatibility: a v1 caller without explicit elapsed data
        # reserves a whole block. Deprecated route `progress` is never used.
        progress = 0.0
    if not math.isfinite(progress) or not 0 <= progress <= 1 or duration <= 0:
        raise ValueError("invalid current block duration/progress")
    return max(0, math.ceil(duration * (1 - progress)))
